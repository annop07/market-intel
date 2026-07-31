"""End-to-end pipeline: ingest JSONL → embed → analyse → write the report.

This is what CI runs nightly, and it is the same code path as the API — it just
skips the HTTP hop.

    uv run python -m scripts.pipeline --input ../data/raw/*.jsonl --report
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.contract import Product
from app.storage import get_catalogue
from app.vectorstore import get_vector_store

HISTORY_COLUMNS = [
    "product_id", "day", "price", "currency", "price_base", "in_stock", "seen_at",
]


def load_history(path: Path) -> int:
    """Read price history collected by earlier runs.

    CI runners are ephemeral: without this, every nightly run would start from an
    empty database and the market would look brand new every morning. The file is
    CSV and committed to the repo, so the history is diffable instead of a binary
    blob nobody can inspect.
    """
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as fh:
        return get_catalogue().import_snapshots(csv.DictReader(fh))


def save_history(path: Path) -> int:
    rows = get_catalogue().export_snapshots()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def ingest_files(patterns: list[str], batch_size: int = 200) -> tuple[int, int, int]:
    cat = get_catalogue()
    store = get_vector_store()
    products = reviews = vectors = 0

    paths = sorted({p for pattern in patterns for p in glob.glob(pattern)})
    if not paths:
        raise SystemExit(f"no files matched {patterns}")

    for path in paths:
        batch: list[Product] = []
        skipped = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    batch.append(Product.model_validate(json.loads(line)))
                except Exception as exc:  # a bad row must not kill the crawl
                    skipped += 1
                    print(f"  ! {path}: skipping malformed row: {exc}", file=sys.stderr)
                if len(batch) >= batch_size:
                    p, r, v = _flush(cat, store, batch)
                    products, reviews, vectors = products + p, reviews + r, vectors + v
                    batch = []
        if batch:
            p, r, v = _flush(cat, store, batch)
            products, reviews, vectors = products + p, reviews + r, vectors + v
        print(f"✓ {path}{'' if not skipped else f' ({skipped} malformed rows skipped)'}")

    return products, reviews, vectors


def _flush(cat, store, batch: list[Product]) -> tuple[int, int, int]:
    p, r = cat.upsert_products(batch)
    v = store.index_products(batch)
    return p, r, v


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", default=["../data/raw/*.jsonl"],
                        help="JSONL files or globs produced by the collector")
    parser.add_argument("--report", action="store_true", help="also generate the executive report")
    parser.add_argument("--category", default=None, help="scope the report to one category")
    parser.add_argument("--review-limit", type=int, default=100,
                        help="max reviews sent through aspect extraction")
    parser.add_argument("--model", default=None, help="override LLM_MODEL")
    parser.add_argument("--language", default="en", choices=["en", "th"],
                        help="language the report prose is written in")
    parser.add_argument("--history", default="../history/price-history.csv",
                        help="CSV of price snapshots, carried between runs")
    parser.add_argument("--no-history", action="store_true",
                        help="skip loading and writing the history file")
    args = parser.parse_args()

    products, reviews, vectors = ingest_files(args.input)
    cat = get_catalogue()
    print(
        f"\ningested {products} products / {reviews} reviews, indexed {vectors} vectors\n"
        f"catalogue now holds {cat.count_products()} products, {cat.count_reviews()} reviews"
    )

    history_path = Path(args.history)
    if not args.no_history:
        # Load after ingest: snapshots are keyed to products, so the catalogue
        # has to exist before its history can attach to it.
        loaded = load_history(history_path)
        written = save_history(history_path)
        days = cat.snapshot_days()
        print(
            f"history: loaded {loaded} prior snapshots, saved {written} to "
            f"{history_path} ({len(days)} day(s): {days[0] if days else '—'} → "
            f"{days[-1] if days else '—'})"
        )

    if not args.report:
        return

    if not get_settings().llm_configured:
        raise SystemExit("OPENAI_API_KEY is not set — cannot generate the report")

    # Imported here so ingest-only runs never need the LLM stack.
    from app.analysis.report import build_report
    from app.main import save_report

    print(f"\ngenerating {args.language} report for {args.category or 'all categories'}…")
    report = build_report(cat, category=args.category, review_limit=args.review_limit,
                          model=args.model, language=args.language)
    path: Path = save_report(report)
    print(f"✓ {path}")
    print(
        f"  {report.reviews_analysed} reviews → {report.sentiment.mentions_kept} verified "
        f"mentions ({report.sentiment.mentions_discarded} discarded), "
        f"{report.citations_dropped} bad citations stripped, "
        f"{report.usage.get('total_tokens', 0)} tokens"
    )


if __name__ == "__main__":
    main()
