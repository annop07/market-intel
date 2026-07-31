"""Price & feature intelligence — arithmetic only, no LLM.

Everything here is reproducible: the same catalogue always yields the same
numbers. The model's job downstream is to explain these figures, not to invent
them. Any claim in the final report that involves a number traces back to a
function in this file.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.storage import Catalogue


class BrandPosition(BaseModel):
    brand: str
    products: int
    avg_price: float
    min_price: float
    max_price: float
    price_index: float | None = Field(
        default=None, description="100 = category median price"
    )
    avg_rating: float | None = None
    reviews: int = 0
    in_stock_pct: float | None = None
    avg_discount_pct: float | None = None
    value_score: float | None = Field(
        default=None, description="rating points per 100 currency units"
    )


class PriceGap(BaseModel):
    lower_price: float
    upper_price: float
    gap: float
    gap_pct: float
    below: str
    above: str


class PriceIntelligence(BaseModel):
    category: str | None = None
    distribution: dict
    brands: list[BrandPosition]
    gaps: list[PriceGap] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)


def analyse_pricing(
    cat: Catalogue, category: str | None = None, language: str = "en"
) -> PriceIntelligence:
    distribution = cat.price_distribution(category)
    brands = [BrandPosition(**_brand_row(r)) for r in cat.brand_stats(category)]
    products = cat.products(category=category)

    return PriceIntelligence(
        category=category,
        distribution=distribution,
        brands=brands,
        gaps=_price_gaps(products),
        observations=_observations(brands, distribution, products, language),
    )


def _brand_row(row: dict) -> dict:
    keep = {
        k: row.get(k)
        for k in (
            "brand", "products", "avg_price", "min_price", "max_price",
            "price_index", "avg_rating", "reviews", "in_stock_pct", "avg_discount_pct",
        )
    }
    # Value = quality per unit of price. Comparable only within a category,
    # which is why the caller always scopes this to one.
    if keep.get("avg_rating") and keep.get("avg_price"):
        keep["value_score"] = round(100 * keep["avg_rating"] / keep["avg_price"], 2)
    return keep


def _price_gaps(products: list[dict], top: int = 3) -> list[PriceGap]:
    """Find the widest unoccupied price bands — candidate white space.

    A large jump between two neighbouring products means nobody is selling at
    that price point in this category.
    """
    priced = sorted(
        (p for p in products if p["price_base"] > 0), key=lambda p: p["price_base"]
    )
    gaps: list[PriceGap] = []
    for lower, upper in zip(priced, priced[1:]):
        gap = upper["price_base"] - lower["price_base"]
        if gap <= 0:
            continue
        gaps.append(
            PriceGap(
                lower_price=round(lower["price_base"], 2),
                upper_price=round(upper["price_base"], 2),
                gap=round(gap, 2),
                gap_pct=round(100 * gap / lower["price_base"], 1),
                below=f'{lower["brand"]} — {lower["title"]}',
                above=f'{upper["brand"]} — {upper["title"]}',
            )
        )
    gaps.sort(key=lambda g: g.gap, reverse=True)
    return gaps[:top]


# These findings are strings a human reads, so they follow the report language.
# The brand names and figures inside them do not change — only the sentence around
# them does, which keeps a Thai report from mixing two languages mid-page.
TEMPLATES = {
    "en": {
        "price_leader": (
            "{premium} is the price leader at {premium_price:.2f} average "
            "({index:.0f} vs category median = 100); {value} anchors the low end "
            "at {value_price:.2f}."
        ),
        "best_rated": (
            "{brand} holds the highest average rating ({rating:.2f}) across "
            "{products} product(s)."
        ),
        "best_value": (
            "{brand} offers the most rating per unit of price (value score {score:.2f})."
        ),
        "deepest_discount": (
            "{brand} discounts hardest, averaging {pct:.1f}% off list."
        ),
        "out_of_stock": (
            "{count} of {total} listings are out of stock ({pct:.0f}%) — demand the "
            "incumbents are not currently serving."
        ),
        "spread": (
            "Prices span {min:.2f}–{max:.2f} (median {median:.2f}, p90 {p90:.2f})."
        ),
    },
    "th": {
        "price_leader": (
            "{premium} ตั้งราคาสูงสุดในหมวดนี้ เฉลี่ย {premium_price:.2f} "
            "(ดัชนี {index:.0f} เทียบมัธยฐาน = 100) ส่วน {value} ยึดฝั่งราคาต่ำที่ {value_price:.2f}"
        ),
        "best_rated": (
            "{brand} มีคะแนนรีวิวเฉลี่ยสูงสุด ({rating:.2f}) จากสินค้า {products} รายการ"
        ),
        "best_value": (
            "{brand} ให้คะแนนต่อเงินหนึ่งหน่วยคุ้มที่สุด (value score {score:.2f})"
        ),
        "deepest_discount": "{brand} ลดราคาหนักที่สุด เฉลี่ย {pct:.1f}% จากราคาเต็ม",
        "out_of_stock": (
            "สินค้า {count} จาก {total} รายการ ({pct:.0f}%) ของหมด "
            "— เป็นดีมานด์ที่เจ้าตลาดเดิมยังตอบไม่ได้"
        ),
        "spread": "ราคากระจายตัว {min:.2f}–{max:.2f} (มัธยฐาน {median:.2f}, p90 {p90:.2f})",
    },
}


def _observations(
    brands: list[BrandPosition],
    distribution: dict,
    products: list[dict],
    language: str = "en",
) -> list[str]:
    """Rule-based findings. Deliberately boring, and always true of the data."""
    out: list[str] = []
    if not brands or not distribution.get("count"):
        return out
    T = TEMPLATES.get(language, TEMPLATES["en"])

    ranked = sorted(brands, key=lambda b: b.avg_price, reverse=True)
    premium, value = ranked[0], ranked[-1]
    if premium.brand != value.brand:
        out.append(
            T["price_leader"].format(
                premium=premium.brand,
                premium_price=premium.avg_price,
                index=premium.price_index or 0,
                value=value.brand,
                value_price=value.avg_price,
            )
        )

    rated = [b for b in brands if b.avg_rating]
    if rated:
        best = max(rated, key=lambda b: b.avg_rating)
        out.append(
            T["best_rated"].format(
                brand=best.brand, rating=best.avg_rating, products=best.products
            )
        )
        scored = [b for b in rated if b.value_score]
        if scored:
            champ = max(scored, key=lambda b: b.value_score)
            if champ.brand != best.brand:
                out.append(
                    T["best_value"].format(brand=champ.brand, score=champ.value_score)
                )

    discounting = [b for b in brands if b.avg_discount_pct]
    if discounting:
        deepest = max(discounting, key=lambda b: b.avg_discount_pct)
        out.append(
            T["deepest_discount"].format(
                brand=deepest.brand, pct=deepest.avg_discount_pct
            )
        )

    out_of_stock = [p for p in products if not p["in_stock"]]
    if out_of_stock:
        out.append(
            T["out_of_stock"].format(
                count=len(out_of_stock),
                total=len(products),
                pct=100 * len(out_of_stock) / len(products),
            )
        )

    spread = distribution.get("max", 0) - distribution.get("min", 0)
    if spread and distribution.get("median"):
        out.append(
            T["spread"].format(
                min=distribution["min"],
                max=distribution["max"],
                median=distribution["median"],
                p90=distribution["p90"],
            )
        )
    return out
