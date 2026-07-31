"""SQLite catalogue — the single source of truth for every number in a report.

Design note: the LLM never computes statistics. Prices, medians, discount depth
and stock rates come out of SQL here; the model only gets those figures handed
to it and writes the narrative around them. That split is what makes the report
reproducible — rerun it and the numbers are identical.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

from app.config import get_settings
from app.contract import Product, Review

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    url           TEXT,
    title         TEXT NOT NULL,
    brand         TEXT,
    category      TEXT,
    price         REAL NOT NULL,
    currency      TEXT NOT NULL,
    price_base    REAL NOT NULL,   -- price converted to the base currency
    list_price    REAL,
    rating        REAL,
    rating_count  INTEGER DEFAULT 0,
    in_stock      INTEGER DEFAULT 1,
    description   TEXT,
    features      TEXT,            -- JSON object
    collected_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);

-- One row per product per day: what it cost and whether it was in stock.
-- The products table only ever holds the latest state, so this is the table
-- that makes "the market" something with a shape over time rather than a
-- snapshot. Last observation of the day wins, which keeps a catalogue of
-- ~600 products at ~220k rows a year — small enough to keep forever.
CREATE TABLE IF NOT EXISTS price_snapshots (
    product_id  TEXT NOT NULL,
    day         TEXT NOT NULL,   -- YYYY-MM-DD, UTC
    price       REAL NOT NULL,
    currency    TEXT NOT NULL,
    price_base  REAL NOT NULL,
    in_stock    INTEGER NOT NULL,
    seen_at     TEXT NOT NULL,
    PRIMARY KEY (product_id, day)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_day ON price_snapshots(day);

CREATE TABLE IF NOT EXISTS reviews (
    id          TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rating      REAL,
    title       TEXT,
    body        TEXT NOT NULL,
    author      TEXT,
    posted_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
"""


class Catalogue:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI serves requests from a thread pool,
        # and every write below is wrapped in its own short transaction.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    # ---------- writes ----------

    def upsert_products(
        self, products: Iterable[Product], observed_at: datetime | None = None
    ) -> tuple[int, int]:
        """Insert or replace products and their reviews. Returns (products, reviews).

        Every call also records a price snapshot, so re-crawling builds history
        instead of quietly overwriting yesterday's prices.

        `observed_at` exists for backfills and tests; a live crawl leaves it
        unset and is stamped with the time it actually ran.
        """
        settings = get_settings()
        n_products = n_reviews = 0
        seen_at = observed_at or datetime.now(timezone.utc)
        day = seen_at.strftime("%Y-%m-%d")

        with self._tx() as conn:
            for p in products:
                rate = settings.fx_rates.get(p.price.currency, 1.0)
                price_base = round(p.price.amount * rate, 4)
                conn.execute(
                    """
                    INSERT INTO products (id, source, url, title, brand, category, price,
                        currency, price_base, list_price, rating, rating_count, in_stock,
                        description, features, collected_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        price=excluded.price, currency=excluded.currency,
                        price_base=excluded.price_base, list_price=excluded.list_price,
                        rating=excluded.rating, rating_count=excluded.rating_count,
                        in_stock=excluded.in_stock, features=excluded.features,
                        collected_at=excluded.collected_at
                    """,
                    (
                        p.id, p.source, p.url, p.title, p.brand or "(unbranded)",
                        p.category, p.price.amount, p.price.currency,
                        price_base,
                        p.list_price.amount if p.list_price else None,
                        p.rating, p.rating_count, int(p.in_stock), p.description,
                        json.dumps(p.features, ensure_ascii=False),
                        p.collected_at.isoformat() if p.collected_at else None,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO price_snapshots (product_id, day, price, currency,
                        price_base, in_stock, seen_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(product_id, day) DO UPDATE SET
                        price=excluded.price, currency=excluded.currency,
                        price_base=excluded.price_base, in_stock=excluded.in_stock,
                        seen_at=excluded.seen_at
                    """,
                    (
                        p.id, day, p.price.amount, p.price.currency, price_base,
                        int(p.in_stock), seen_at.isoformat(),
                    ),
                )
                n_products += 1

                for r in p.reviews:
                    conn.execute(
                        """
                        INSERT INTO reviews (id, product_id, rating, title, body, author, posted_at)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET body=excluded.body, rating=excluded.rating
                        """,
                        (
                            r.id, r.product_id, r.rating, r.title, r.body, r.author,
                            r.posted_at.isoformat() if r.posted_at else None,
                        ),
                    )
                    n_reviews += 1

        return n_products, n_reviews

    # ---------- reads ----------

    def count_products(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def count_reviews(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

    def categories(self, min_products: int = 1) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT category,
                   COUNT(*) AS products,
                   COUNT(DISTINCT brand) AS brands,
                   ROUND(AVG(price_base), 2) AS avg_price
            FROM products
            WHERE category != ''
            GROUP BY category
            HAVING products >= ?
            ORDER BY products DESC
            """,
            (min_products,),
        ).fetchall()
        return [dict(r) for r in rows]

    def sources(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT p.source,
                   COUNT(DISTINCT p.id) AS products,
                   COUNT(r.id) AS reviews
            FROM products p LEFT JOIN reviews r ON r.product_id = p.id
            GROUP BY p.source ORDER BY products DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def products(
        self,
        category: str | None = None,
        brand: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM products WHERE 1=1"
        args: list = []
        for column, value in (("category", category), ("brand", brand), ("source", source)):
            if value:
                sql += f" AND {column} = ?"
                args.append(value)
        sql += " ORDER BY price_base"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)

        out = []
        for row in self._conn.execute(sql, args).fetchall():
            d = dict(row)
            d["features"] = json.loads(d["features"] or "{}")
            d["in_stock"] = bool(d["in_stock"])
            out.append(d)
        return out

    def reviews(
        self,
        category: str | None = None,
        brand: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Reviews joined to their product, newest and lowest-rated first.

        Low ratings lead deliberately: complaints carry the competitive signal,
        and a fixed budget of reviews per run is better spent on them.
        """
        sql = """
            SELECT r.id, r.product_id, r.rating, r.title, r.body, r.author, r.posted_at,
                   p.title AS product_title, p.brand, p.category, p.source
            FROM reviews r JOIN products p ON p.id = r.product_id
            WHERE 1=1
        """
        args: list = []
        if category:
            sql += " AND p.category = ?"
            args.append(category)
        if brand:
            sql += " AND p.brand = ?"
            args.append(brand)
        sql += " ORDER BY COALESCE(r.rating, 3) ASC, r.posted_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def brand_stats(self, category: str | None = None) -> list[dict]:
        """Per-brand price and quality position — computed, not inferred."""
        sql = """
            SELECT brand,
                   COUNT(*) AS products,
                   ROUND(AVG(price_base), 2) AS avg_price,
                   ROUND(MIN(price_base), 2) AS min_price,
                   ROUND(MAX(price_base), 2) AS max_price,
                   ROUND(AVG(rating), 2) AS avg_rating,
                   SUM(rating_count) AS reviews,
                   ROUND(100.0 * SUM(in_stock) / COUNT(*), 1) AS in_stock_pct,
                   ROUND(AVG(CASE WHEN list_price IS NOT NULL AND list_price > 0
                        THEN 100.0 * (list_price - price) / list_price END), 1) AS avg_discount_pct
            FROM products
            WHERE 1=1
        """
        args: list = []
        if category:
            sql += " AND category = ?"
            args.append(category)
        sql += " GROUP BY brand ORDER BY avg_price DESC"

        rows = [dict(r) for r in self._conn.execute(sql, args).fetchall()]
        prices = [p["price_base"] for p in self.products(category=category)]
        median = statistics.median(prices) if prices else 0.0

        for r in rows:
            # Price index: 100 = the category median. 130 means "30% pricier".
            r["price_index"] = round(100 * r["avg_price"] / median, 1) if median else None
            r["median_price_of_category"] = round(median, 2)
        return rows

    def price_distribution(self, category: str | None = None) -> dict:
        prices = sorted(p["price_base"] for p in self.products(category=category))
        if not prices:
            return {"count": 0}
        return {
            "count": len(prices),
            "currency": get_settings().base_currency,
            "min": round(prices[0], 2),
            "p25": round(_percentile(prices, 25), 2),
            "median": round(statistics.median(prices), 2),
            "p75": round(_percentile(prices, 75), 2),
            "p90": round(_percentile(prices, 90), 2),
            "max": round(prices[-1], 2),
            "mean": round(statistics.fmean(prices), 2),
        }

    # ---------- history ----------

    def snapshot_days(self, category: str | None = None) -> list[str]:
        """Every day the catalogue was observed, oldest first."""
        sql = "SELECT DISTINCT s.day FROM price_snapshots s"
        args: list = []
        if category:
            sql += " JOIN products p ON p.id = s.product_id WHERE p.category = ?"
            args.append(category)
        sql += " ORDER BY s.day"
        return [row["day"] for row in self._conn.execute(sql, args).fetchall()]

    def snapshots(
        self, category: str | None = None, since: str | None = None
    ) -> list[dict]:
        """Raw snapshot rows joined to product identity, oldest first.

        Change detection diffs these in Python rather than in SQL: window
        functions would work, but the diffing rules are the interesting part and
        they are far easier to read — and to test — as plain code.
        """
        sql = """
            SELECT s.product_id, s.day, s.price, s.currency, s.price_base, s.in_stock,
                   p.title, p.brand, p.category, p.source, p.url
            FROM price_snapshots s JOIN products p ON p.id = s.product_id
            WHERE 1=1
        """
        args: list = []
        if category:
            sql += " AND p.category = ?"
            args.append(category)
        if since:
            sql += " AND s.day >= ?"
            args.append(since)
        sql += " ORDER BY s.day, s.product_id"

        rows = []
        for row in self._conn.execute(sql, args).fetchall():
            d = dict(row)
            d["in_stock"] = bool(d["in_stock"])
            rows.append(d)
        return rows

    def daily_series(
        self, category: str | None = None, since: str | None = None
    ) -> list[dict]:
        """Per-day market shape: how many products, the median price, stock rate."""
        by_day: dict[str, list[dict]] = {}
        for row in self.snapshots(category=category, since=since):
            by_day.setdefault(row["day"], []).append(row)

        series = []
        for day, rows in sorted(by_day.items()):
            prices = sorted(r["price_base"] for r in rows)
            series.append(
                {
                    "day": day,
                    "products": len(rows),
                    "median_price": round(statistics.median(prices), 2),
                    "min_price": round(prices[0], 2),
                    "max_price": round(prices[-1], 2),
                    "p90_price": round(_percentile(prices, 90), 2),
                    "in_stock_pct": round(
                        100 * sum(1 for r in rows if r["in_stock"]) / len(rows), 1
                    ),
                }
            )
        return series

    def import_snapshots(self, rows: Iterable[dict]) -> int:
        """Load snapshots collected elsewhere — a previous CI run, say.

        Rows whose product is not in this catalogue are skipped: a snapshot
        without a product would break every join that reads it back.
        """
        known = {row["id"] for row in self._conn.execute("SELECT id FROM products")}
        imported = 0
        with self._tx() as conn:
            for row in rows:
                if row["product_id"] not in known:
                    continue
                conn.execute(
                    """
                    INSERT INTO price_snapshots (product_id, day, price, currency,
                        price_base, in_stock, seen_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(product_id, day) DO NOTHING
                    """,
                    (
                        row["product_id"], row["day"], float(row["price"]),
                        row["currency"], float(row["price_base"]),
                        int(row["in_stock"]), row["seen_at"],
                    ),
                )
                imported += 1
        return imported

    def export_snapshots(self) -> list[dict]:
        """Every snapshot, ordered for a stable diff when committed to git."""
        rows = self._conn.execute(
            """
            SELECT product_id, day, price, currency, price_base, in_stock, seen_at
            FROM price_snapshots ORDER BY day, product_id
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def review_by_id(self, review_id: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT r.*, p.brand, p.category, p.title AS product_title
            FROM reviews r JOIN products p ON p.id = r.product_id WHERE r.id = ?
            """,
            (review_id,),
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self._conn.close()


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile; `statistics.quantiles` needs n >= 2."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


@lru_cache
def get_catalogue() -> Catalogue:
    return Catalogue(get_settings().database_path)
