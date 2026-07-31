"""Tests for the deterministic half of the system — no API key required."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.analysis.pricing import analyse_pricing
from app.contract import Price, Product, Review
from app.storage import Catalogue


def make_product(
    pid: str, brand: str, price: float, *, currency="USD", category="laptops",
    rating=4.0, list_price=None, in_stock=True, reviews=(),
) -> Product:
    return Product(
        id=pid,
        source="test",
        title=f"{brand} {pid}",
        brand=brand,
        category=category,
        price=Price(amount=price, currency=currency),
        list_price=Price(amount=list_price, currency=currency) if list_price else None,
        rating=rating,
        in_stock=in_stock,
        collected_at=datetime.now(timezone.utc),
        reviews=[
            Review(id=f"{pid}#r{i}", product_id=pid, rating=r, body=body)
            for i, (r, body) in enumerate(reviews)
        ],
    )


@pytest.fixture
def cat() -> Catalogue:
    catalogue = Catalogue(":memory:")
    yield catalogue
    catalogue.close()


def test_upsert_is_idempotent(cat: Catalogue):
    products = [make_product("p1", "Acme", 100, reviews=[(5, "great")])]

    cat.upsert_products(products)
    cat.upsert_products(products)

    # Re-running the collector must not duplicate rows — that is what stable
    # ids in the Go model are for.
    assert cat.count_products() == 1
    assert cat.count_reviews() == 1


def test_upsert_updates_changed_price(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)])
    cat.upsert_products([make_product("p1", "Acme", 80)])

    assert cat.products()[0]["price"] == 80


def test_prices_are_converted_to_base_currency(cat: Catalogue):
    cat.upsert_products([
        make_product("usd", "Acme", 100, currency="USD"),
        make_product("gbp", "Beta", 100, currency="GBP"),
    ])

    by_id = {p["id"]: p for p in cat.products()}
    assert by_id["usd"]["price_base"] == 100
    # GBP is worth more than USD, so the same nominal price must rank higher.
    assert by_id["gbp"]["price_base"] > by_id["usd"]["price_base"]


def test_price_distribution_percentiles(cat: Catalogue):
    cat.upsert_products([make_product(f"p{i}", "Acme", float(i)) for i in range(1, 11)])

    dist = cat.price_distribution()

    assert dist["count"] == 10
    assert dist["min"] == 1 and dist["max"] == 10
    assert dist["median"] == 5.5
    assert dist["p25"] < dist["median"] < dist["p90"]


def test_brand_stats_price_index_is_relative_to_median(cat: Catalogue):
    cat.upsert_products([
        make_product("cheap", "Value", 50),
        make_product("mid", "Middle", 100),
        make_product("dear", "Premium", 150),
    ])

    stats = {row["brand"]: row for row in cat.brand_stats()}

    assert stats["Middle"]["price_index"] == 100  # the median brand is the index base
    assert stats["Premium"]["price_index"] > 100
    assert stats["Value"]["price_index"] < 100


def test_brand_stats_discount_depth(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 75, list_price=100)])

    assert cat.brand_stats()[0]["avg_discount_pct"] == 25.0


def test_reviews_are_ordered_worst_first(cat: Catalogue):
    cat.upsert_products([
        make_product("p1", "Acme", 10, reviews=[(5, "loved it"), (1, "broke instantly")])
    ])

    bodies = [r["body"] for r in cat.reviews()]

    # Complaints carry the competitive signal, so a limited review budget
    # spends itself on them first.
    assert bodies[0] == "broke instantly"


def test_reviews_filter_by_category_and_brand(cat: Catalogue):
    cat.upsert_products([
        make_product("p1", "Acme", 10, category="laptops", reviews=[(3, "acme laptop")]),
        make_product("p2", "Beta", 10, category="phones", reviews=[(3, "beta phone")]),
    ])

    assert [r["body"] for r in cat.reviews(category="phones")] == ["beta phone"]
    assert [r["body"] for r in cat.reviews(brand="Acme")] == ["acme laptop"]


def test_pricing_finds_widest_gap(cat: Catalogue):
    cat.upsert_products([
        make_product("a", "Acme", 10),
        make_product("b", "Beta", 12),
        make_product("c", "Gamma", 90),  # the market has nothing between 12 and 90
    ])

    gaps = analyse_pricing(cat).gaps

    assert gaps[0].lower_price == 12 and gaps[0].upper_price == 90


def test_pricing_observations_name_the_price_leader(cat: Catalogue):
    cat.upsert_products([
        make_product("a", "Value", 10, rating=3.0),
        make_product("b", "Premium", 200, rating=4.9),
    ])

    intel = analyse_pricing(cat)

    assert intel.observations, "rule-based observations should not be empty"
    assert any("Premium" in o for o in intel.observations)
    assert any("Value" in o for o in intel.observations)


def test_pricing_on_empty_catalogue_does_not_crash(cat: Catalogue):
    intel = analyse_pricing(cat)

    assert intel.distribution == {"count": 0}
    assert intel.brands == [] and intel.observations == []


def test_value_score_rewards_rating_per_currency_unit(cat: Catalogue):
    cat.upsert_products([
        make_product("a", "Cheap", 50, rating=4.0),
        make_product("b", "Dear", 200, rating=4.4),
    ])

    brands = {b.brand: b for b in analyse_pricing(cat).brands}

    assert brands["Cheap"].value_score > brands["Dear"].value_score
