"""What moved since last time — the difference between a snapshot and a watch.

Everything here is arithmetic over the snapshot table: no LLM, no inference.
A price cut is a price cut because two numbers differ, and the report agent is
handed that fact rather than asked to spot it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field

from app.storage import Catalogue

# A 1% wobble is noise (rounding, FX, a coupon); below this a "change" would
# fill the report with movement nobody would act on.
DEFAULT_MIN_MOVE_PCT = 2.0


class PriceMove(BaseModel):
    product_id: str
    title: str
    brand: str
    from_price: float
    to_price: float
    change: float
    change_pct: float
    direction: str  # "down" | "up"
    from_day: str
    to_day: str
    url: str = ""


class StockFlip(BaseModel):
    product_id: str
    title: str
    brand: str
    in_stock: bool = Field(description="the state it flipped TO")
    day: str


class CatalogueEntry(BaseModel):
    product_id: str
    title: str
    brand: str
    price: float
    day: str


class MarketChanges(BaseModel):
    category: str | None = None
    days: int
    baseline_day: str | None = None
    latest_day: str | None = None
    days_observed: int = 0
    has_history: bool = Field(
        default=False, description="false until the catalogue has been crawled twice"
    )
    median_before: float | None = None
    median_after: float | None = None
    median_change_pct: float | None = None
    price_moves: list[PriceMove] = Field(default_factory=list)
    stock_flips: list[StockFlip] = Field(default_factory=list)
    new_products: list[CatalogueEntry] = Field(default_factory=list)
    disappeared: list[CatalogueEntry] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)


TEMPLATES = {
    "en": {
        "window": "Comparing {latest} against {baseline} ({days_observed} day(s) observed).",
        "median": (
            "The category median moved {direction} {pct:.1f}% "
            "({before:.2f} → {after:.2f})."
        ),
        "median_flat": "The category median held steady at {after:.2f}.",
        "biggest_cut": (
            "{brand} cut {title} by {pct:.1f}% ({before:.2f} → {after:.2f}) — the "
            "deepest cut in the window."
        ),
        "biggest_rise": (
            "{brand} raised {title} by {pct:.1f}% ({before:.2f} → {after:.2f})."
        ),
        "moves_count": (
            "{cuts} product(s) got cheaper and {rises} got more expensive."
        ),
        "went_out": "{count} product(s) went out of stock, including {example}.",
        "came_back": "{count} product(s) came back in stock.",
        "new": "{count} new listing(s) appeared, including {example}.",
        "gone": "{count} listing(s) disappeared from the catalogue.",
        "quiet": "Nothing moved by more than {threshold:.0f}% in this window.",
    },
    "th": {
        "window": "เทียบข้อมูลวันที่ {latest} กับ {baseline} (เก็บข้อมูลมาแล้ว {days_observed} วัน)",
        "median": "ราคามัธยฐานของหมวดนี้{direction} {pct:.1f}% ({before:.2f} → {after:.2f})",
        "median_flat": "ราคามัธยฐานของหมวดนี้นิ่ง อยู่ที่ {after:.2f}",
        "biggest_cut": (
            "{brand} ลดราคา {title} ลง {pct:.1f}% ({before:.2f} → {after:.2f}) "
            "— ลดหนักที่สุดในช่วงนี้"
        ),
        "biggest_rise": "{brand} ขึ้นราคา {title} {pct:.1f}% ({before:.2f} → {after:.2f})",
        "moves_count": "สินค้าถูกลง {cuts} รายการ และแพงขึ้น {rises} รายการ",
        "went_out": "สินค้า {count} รายการของหมด เช่น {example}",
        "came_back": "สินค้า {count} รายการกลับมามีของแล้ว",
        "new": "มีสินค้าใหม่เข้ามา {count} รายการ เช่น {example}",
        "gone": "สินค้า {count} รายการหายไปจากแคตตาล็อก",
        "quiet": "ไม่มีอะไรขยับเกิน {threshold:.0f}% ในช่วงนี้",
    },
}

# "down" reads naturally in English but Thai needs a verb, not a preposition.
DIRECTION_WORDS = {
    "en": {"down": "down", "up": "up"},
    "th": {"down": "ลดลง", "up": "เพิ่มขึ้น"},
}


def analyse_changes(
    cat: Catalogue,
    category: str | None = None,
    days: int = 7,
    min_move_pct: float = DEFAULT_MIN_MOVE_PCT,
    language: str = "en",
    today: date | None = None,
) -> MarketChanges:
    """Diff the latest crawl against the one closest to `days` ago."""
    all_days = cat.snapshot_days(category)
    changes = MarketChanges(category=category, days=days, days_observed=len(all_days))
    if len(all_days) < 2:
        # One crawl is a snapshot, not a trend. Say so instead of inventing one.
        changes.latest_day = all_days[-1] if all_days else None
        return changes

    latest_day = all_days[-1]
    cutoff = ((today or datetime.now(timezone.utc).date()) - timedelta(days=days)).isoformat()
    # The oldest day still inside the window, or the oldest we have if the
    # window reaches further back than the history does.
    earlier = [d for d in all_days[:-1] if d >= cutoff] or all_days[:-1]
    baseline_day = earlier[0]

    rows = cat.snapshots(category=category, since=baseline_day)
    baseline = {r["product_id"]: r for r in rows if r["day"] == baseline_day}
    latest = {r["product_id"]: r for r in rows if r["day"] == latest_day}

    changes.has_history = True
    changes.baseline_day = baseline_day
    changes.latest_day = latest_day
    changes.median_before = _median([r["price_base"] for r in baseline.values()])
    changes.median_after = _median([r["price_base"] for r in latest.values()])
    if changes.median_before:
        changes.median_change_pct = round(
            100 * (changes.median_after - changes.median_before) / changes.median_before, 2
        )

    for product_id, now in latest.items():
        before = baseline.get(product_id)
        if before is None:
            continue
        if before["price_base"] <= 0:
            continue

        pct = 100 * (now["price_base"] - before["price_base"]) / before["price_base"]
        if abs(pct) >= min_move_pct:
            changes.price_moves.append(
                PriceMove(
                    product_id=product_id,
                    title=now["title"],
                    brand=now["brand"],
                    from_price=round(before["price_base"], 2),
                    to_price=round(now["price_base"], 2),
                    change=round(now["price_base"] - before["price_base"], 2),
                    change_pct=round(pct, 2),
                    direction="up" if pct > 0 else "down",
                    from_day=baseline_day,
                    to_day=latest_day,
                    url=now.get("url", ""),
                )
            )

        if before["in_stock"] != now["in_stock"]:
            changes.stock_flips.append(
                StockFlip(
                    product_id=product_id,
                    title=now["title"],
                    brand=now["brand"],
                    in_stock=now["in_stock"],
                    day=latest_day,
                )
            )

    changes.price_moves.sort(key=lambda m: abs(m.change_pct), reverse=True)

    for product_id, now in latest.items():
        if product_id not in baseline:
            changes.new_products.append(_entry(now))
    for product_id, before in baseline.items():
        if product_id not in latest:
            changes.disappeared.append(_entry(before))

    changes.observations = _observations(changes, min_move_pct, language)
    return changes


def _entry(row: dict) -> CatalogueEntry:
    return CatalogueEntry(
        product_id=row["product_id"],
        title=row["title"],
        brand=row["brand"],
        price=round(row["price_base"], 2),
        day=row["day"],
    )


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def _observations(
    changes: MarketChanges, min_move_pct: float, language: str
) -> list[str]:
    T = TEMPLATES.get(language, TEMPLATES["en"])
    words = DIRECTION_WORDS.get(language, DIRECTION_WORDS["en"])
    out = [
        T["window"].format(
            latest=changes.latest_day,
            baseline=changes.baseline_day,
            days_observed=changes.days_observed,
        )
    ]

    if changes.median_before and changes.median_after:
        if changes.median_change_pct and abs(changes.median_change_pct) >= 0.5:
            out.append(
                T["median"].format(
                    direction=words["down" if changes.median_change_pct < 0 else "up"],
                    pct=abs(changes.median_change_pct),
                    before=changes.median_before,
                    after=changes.median_after,
                )
            )
        else:
            out.append(T["median_flat"].format(after=changes.median_after))

    cuts = [m for m in changes.price_moves if m.direction == "down"]
    rises = [m for m in changes.price_moves if m.direction == "up"]
    if cuts or rises:
        out.append(T["moves_count"].format(cuts=len(cuts), rises=len(rises)))
    if cuts:
        deepest = cuts[0]
        out.append(
            T["biggest_cut"].format(
                brand=deepest.brand, title=deepest.title, pct=abs(deepest.change_pct),
                before=deepest.from_price, after=deepest.to_price,
            )
        )
    if rises:
        steepest = max(rises, key=lambda m: m.change_pct)
        out.append(
            T["biggest_rise"].format(
                brand=steepest.brand, title=steepest.title, pct=steepest.change_pct,
                before=steepest.from_price, after=steepest.to_price,
            )
        )

    went_out = [f for f in changes.stock_flips if not f.in_stock]
    came_back = [f for f in changes.stock_flips if f.in_stock]
    if went_out:
        out.append(
            T["went_out"].format(
                count=len(went_out), example=f"{went_out[0].brand} {went_out[0].title}"
            )
        )
    if came_back:
        out.append(T["came_back"].format(count=len(came_back)))

    if changes.new_products:
        first = changes.new_products[0]
        out.append(
            T["new"].format(
                count=len(changes.new_products), example=f"{first.brand} {first.title}"
            )
        )
    if changes.disappeared:
        out.append(T["gone"].format(count=len(changes.disappeared)))

    if not changes.price_moves and not changes.stock_flips:
        out.append(T["quiet"].format(threshold=min_move_pct))
    return out
