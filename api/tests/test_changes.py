"""Change detection over the snapshot history — all arithmetic, no LLM."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.analysis.changes import analyse_changes
from app.storage import Catalogue
from tests.test_storage_and_pricing import make_product

TODAY = date(2026, 7, 31)


def at(days_ago: int) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )


@pytest.fixture
def cat() -> Catalogue:
    catalogue = Catalogue(":memory:")
    yield catalogue
    catalogue.close()


def test_a_single_crawl_reports_no_history(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(0))

    changes = analyse_changes(cat, today=TODAY)

    # One observation is a snapshot, not a trend — and must not pretend otherwise.
    assert changes.has_history is False
    assert changes.price_moves == []
    assert changes.days_observed == 1


def test_recrawling_the_same_day_does_not_create_a_second_point(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(0))
    cat.upsert_products([make_product("p1", "Acme", 95)], observed_at=at(0))

    assert cat.snapshot_days() == [TODAY.isoformat()]
    # The last observation of the day wins.
    assert cat.export_snapshots()[0]["price_base"] == 95


def test_detects_a_price_cut(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(3))
    cat.upsert_products([make_product("p1", "Acme", 80)], observed_at=at(0))

    changes = analyse_changes(cat, today=TODAY)

    assert changes.has_history is True
    assert len(changes.price_moves) == 1
    move = changes.price_moves[0]
    assert move.direction == "down"
    assert move.change_pct == -20.0
    assert (move.from_price, move.to_price) == (100, 80)


def test_ignores_movement_below_the_noise_threshold(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(2))
    cat.upsert_products([make_product("p1", "Acme", 101)], observed_at=at(0))

    changes = analyse_changes(cat, today=TODAY, min_move_pct=2.0)

    assert changes.price_moves == []


def test_moves_are_ranked_by_magnitude(cat: Catalogue):
    cat.upsert_products(
        [make_product("small", "Acme", 100), make_product("big", "Beta", 100)],
        observed_at=at(2),
    )
    cat.upsert_products(
        [make_product("small", "Acme", 95), make_product("big", "Beta", 50)],
        observed_at=at(0),
    )

    moves = analyse_changes(cat, today=TODAY).price_moves

    assert [m.product_id for m in moves] == ["big", "small"]


def test_detects_stock_flips_in_both_directions(cat: Catalogue):
    cat.upsert_products(
        [
            make_product("out", "Acme", 100, in_stock=True),
            make_product("back", "Beta", 100, in_stock=False),
        ],
        observed_at=at(1),
    )
    cat.upsert_products(
        [
            make_product("out", "Acme", 100, in_stock=False),
            make_product("back", "Beta", 100, in_stock=True),
        ],
        observed_at=at(0),
    )

    flips = {f.product_id: f.in_stock for f in analyse_changes(cat, today=TODAY).stock_flips}

    assert flips == {"out": False, "back": True}


def test_detects_new_and_disappeared_listings(cat: Catalogue):
    cat.upsert_products(
        [make_product("stays", "Acme", 100), make_product("gone", "Beta", 100)],
        observed_at=at(2),
    )
    cat.upsert_products(
        [make_product("stays", "Acme", 100), make_product("fresh", "Gamma", 120)],
        observed_at=at(0),
    )

    changes = analyse_changes(cat, today=TODAY)

    assert [p.product_id for p in changes.new_products] == ["fresh"]
    assert [p.product_id for p in changes.disappeared] == ["gone"]


def test_median_shift_is_reported(cat: Catalogue):
    cat.upsert_products(
        [make_product("a", "Acme", 100), make_product("b", "Beta", 200)], observed_at=at(5)
    )
    cat.upsert_products(
        [make_product("a", "Acme", 50), make_product("b", "Beta", 100)], observed_at=at(0)
    )

    changes = analyse_changes(cat, today=TODAY)

    assert changes.median_before == 150
    assert changes.median_after == 75
    assert changes.median_change_pct == -50.0


def test_window_picks_the_oldest_day_inside_it(cat: Catalogue):
    for days_ago, price in ((30, 500), (5, 100), (0, 90)):
        cat.upsert_products([make_product("p1", "Acme", price)], observed_at=at(days_ago))

    week = analyse_changes(cat, days=7, today=TODAY)
    month = analyse_changes(cat, days=31, today=TODAY)

    # A 7-day window must not reach back to the 30-day-old price.
    assert week.baseline_day == (TODAY - timedelta(days=5)).isoformat()
    assert week.price_moves[0].change_pct == -10.0
    assert month.baseline_day == (TODAY - timedelta(days=30)).isoformat()
    assert month.price_moves[0].change_pct == -82.0


def test_window_falls_back_to_the_oldest_history_available(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(60))
    cat.upsert_products([make_product("p1", "Acme", 70)], observed_at=at(0))

    changes = analyse_changes(cat, days=7, today=TODAY)

    # Asking for a week of history when only a 60-day-old point exists should
    # compare against that, clearly labelled, rather than report "no change".
    assert changes.baseline_day == (TODAY - timedelta(days=60)).isoformat()
    assert changes.price_moves[0].change_pct == -30.0


def test_daily_series_tracks_the_market_shape(cat: Catalogue):
    cat.upsert_products(
        [make_product("a", "Acme", 100), make_product("b", "Beta", 300)], observed_at=at(1)
    )
    cat.upsert_products(
        [make_product("a", "Acme", 100, in_stock=False), make_product("b", "Beta", 200)],
        observed_at=at(0),
    )

    series = cat.daily_series()

    assert [point["median_price"] for point in series] == [200.0, 150.0]
    assert series[-1]["in_stock_pct"] == 50.0


def test_observations_are_localised(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(2))
    cat.upsert_products([make_product("p1", "Acme", 80)], observed_at=at(0))

    thai = analyse_changes(cat, today=TODAY, language="th").observations
    english = analyse_changes(cat, today=TODAY, language="en").observations

    assert any("ลดราคา" in o for o in thai)
    assert any("cut" in o for o in english)
    # Product and brand names survive translation.
    assert any("Acme" in o for o in thai)


def test_quiet_window_says_so(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(2))
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(0))

    changes = analyse_changes(cat, today=TODAY)

    assert changes.price_moves == []
    assert any("Nothing moved" in o for o in changes.observations)


def test_history_survives_an_export_import_round_trip(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(3))
    cat.upsert_products([make_product("p1", "Acme", 80)], observed_at=at(0))
    exported = cat.export_snapshots()

    # A fresh CI runner: same catalogue, no history until the file is loaded.
    fresh = Catalogue(":memory:")
    fresh.upsert_products([make_product("p1", "Acme", 80)], observed_at=at(0))
    assert not analyse_changes(fresh, today=TODAY).has_history

    fresh.import_snapshots(exported)
    changes = analyse_changes(fresh, today=TODAY)

    assert changes.has_history is True
    assert changes.price_moves[0].change_pct == -20.0
    fresh.close()


def test_import_skips_snapshots_for_unknown_products(cat: Catalogue):
    cat.upsert_products([make_product("p1", "Acme", 100)], observed_at=at(0))

    imported = cat.import_snapshots([
        {
            "product_id": "ghost", "day": "2026-07-01", "price": 10, "currency": "USD",
            "price_base": 10, "in_stock": 1, "seen_at": "2026-07-01T00:00:00+00:00",
        }
    ])

    assert imported == 0
    assert len(cat.export_snapshots()) == 1
