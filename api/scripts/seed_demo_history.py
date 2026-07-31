"""Generate a SYNTHETIC price history for demos and screenshots.

Why this exists: trend analysis needs at least two crawls, and the sandbox
sources this project collects from have static prices — so a real history takes
real days to accumulate. This script fabricates one so the dashboard and the
report's "what changed" section can be shown before then.

It writes to a SEPARATE database (default ./data/demo.db) and never touches the
collected one. Nothing here is real market data, and no report built from it
should be presented as such.

    uv run python -m scripts.seed_demo_history
    DATABASE_PATH=./data/demo.db uv run uvicorn app.main:app --port 8001
"""
from __future__ import annotations

import argparse
import random
import shutil
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from app.config import get_settings


def seed(source: Path, target: Path, days: int, seed_value: int) -> tuple[int, int]:
    if not source.exists():
        raise SystemExit(f"no collected catalogue at {source} — run the pipeline first")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    rng = random.Random(seed_value)  # reproducible: same demo every time

    products = conn.execute(
        "SELECT id, price, currency, price_base, in_stock FROM products"
    ).fetchall()

    conn.execute("DELETE FROM price_snapshots")
    today = date.today()
    rows = 0

    for product in products:
        price = product["price"]
        base = product["price_base"]
        in_stock = bool(product["in_stock"])
        ratio = base / price if price else 1.0

        # Walk backwards from today's real price so the latest day matches the
        # catalogue, then let the past drift away from it.
        history: list[tuple[str, float, bool]] = [(today.isoformat(), price, in_stock)]
        for offset in range(1, days):
            day = today - timedelta(days=offset)
            roll = rng.random()
            if roll < 0.06:  # a promo that has since ended
                price = price / rng.uniform(0.80, 0.92)
            elif roll < 0.12:  # a price rise that has since happened
                price = price / rng.uniform(1.05, 1.15)
            else:
                price *= rng.uniform(0.998, 1.002)  # noise
            if rng.random() < 0.04:
                in_stock = not in_stock
            history.append((day.isoformat(), round(price, 2), in_stock))

        for day, day_price, day_stock in history:
            seen_at = datetime.combine(
                date.fromisoformat(day), time(6, 0), tzinfo=timezone.utc
            )
            conn.execute(
                """
                INSERT INTO price_snapshots (product_id, day, price, currency,
                    price_base, in_stock, seen_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    product["id"], day, day_price, product["currency"],
                    round(day_price * ratio, 4), int(day_stock), seen_at.isoformat(),
                ),
            )
            rows += 1

    conn.commit()
    conn.close()
    return len(products), rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None, help="collected DB to copy from")
    parser.add_argument("--target", default="./data/demo.db", help="demo DB to write")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=20260731)
    args = parser.parse_args()

    source = Path(args.source or get_settings().database_path)
    products, rows = seed(source, Path(args.target), args.days, args.seed)

    print(
        f"⚠️  SYNTHETIC DATA — {rows} generated snapshots for {products} products "
        f"over {args.days} days,\n    written to {args.target}. "
        f"The collected database at {source} is untouched.\n"
        f"    Never present a report built from this as real market data.",
        file=sys.stderr,
    )
    print(f"DATABASE_PATH={args.target} uv run uvicorn app.main:app --port 8001")


if __name__ == "__main__":
    main()
