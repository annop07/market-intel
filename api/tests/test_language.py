"""Language selection: Thai output must be Thai everywhere a human reads it,
while brand names, ids and figures stay untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.analysis.pricing import analyse_pricing
from app.analysis.report import ExecutiveReport, Finding, Recommendation
from app.analysis.sentiment import AspectSummary, SentimentReport, _squash
from app.render import report_to_markdown
from app.storage import Catalogue
from tests.test_storage_and_pricing import make_product


def has_thai(text: str) -> bool:
    return any("฀" <= ch <= "๿" for ch in text)


@pytest.fixture
def cat() -> Catalogue:
    catalogue = Catalogue(":memory:")
    catalogue.upsert_products([
        make_product("a", "Realme", 200, rating=4.2),
        make_product("b", "Apple", 800, rating=3.2, list_price=1000),
    ])
    yield catalogue
    catalogue.close()


def test_observations_are_written_in_thai(cat: Catalogue):
    observations = analyse_pricing(cat, language="th").observations

    assert observations
    assert all(has_thai(o) for o in observations)
    # Brand names must survive translation — they are how a reader ties a
    # finding back to the data.
    assert any("Apple" in o for o in observations)


def test_observations_default_to_english(cat: Catalogue):
    observations = analyse_pricing(cat).observations

    assert observations
    assert not any(has_thai(o) for o in observations)


def test_unknown_language_falls_back_to_english(cat: Catalogue):
    fallback = analyse_pricing(cat, language="jp").observations

    assert fallback == analyse_pricing(cat, language="en").observations


def test_numbers_are_identical_across_languages(cat: Catalogue):
    en = analyse_pricing(cat, language="en")
    th = analyse_pricing(cat, language="th")

    # Only the prose is translated; every computed figure must match exactly.
    assert en.distribution == th.distribution
    assert [b.model_dump() for b in en.brands] == [b.model_dump() for b in th.brands]
    assert [g.model_dump() for g in en.gaps] == [g.model_dump() for g in th.gaps]


def make_report(language: str, cat: Catalogue) -> ExecutiveReport:
    return ExecutiveReport(
        category="smartphones",
        language=language,
        generated_at=datetime.now(timezone.utc),
        products_analysed=2,
        reviews_analysed=1,
        headline="หัวข้อ" if language == "th" else "Headline",
        summary="สรุป" if language == "th" else "Summary",
        opportunities=[Finding(claim="claim", evidence_review_ids=["r1"])],
        recommendations=[Recommendation(action="do it", rationale="because", priority="high")],
        pricing=analyse_pricing(cat, language=language),
        sentiment=SentimentReport(
            language=language,
            reviews_analysed=1,
            mentions_kept=1,
            mentions_discarded=0,
            aspects=[
                AspectSummary(
                    aspect="แบตเตอรี่" if language == "th" else "battery life",
                    mentions=1,
                    avg_score=-0.8,
                    positive=0,
                    negative=1,
                    evidence=[{"review_id": "r1", "brand": "Apple", "quote": "dies fast", "score": -0.8}],
                )
            ],
        ),
    )


def test_markdown_headings_follow_the_report_language(cat: Catalogue):
    thai = report_to_markdown(make_report("th", cat))

    assert "# รายงานข่าวกรองตลาด" in thai
    assert "## ภาพรวมราคาในตลาด" in thai
    assert "## ตำแหน่งของคู่แข่ง" in thai
    assert "หลักฐาน:" in thai
    # No English scaffolding left behind.
    assert "Price landscape" not in thai
    assert "How this was produced" not in thai


def test_english_report_is_unchanged(cat: Catalogue):
    english = report_to_markdown(make_report("en", cat))

    assert "# Market Intelligence" in english
    assert "## Price landscape" in english
    assert not has_thai(english)


def test_quote_matching_survives_thai_text():
    # An ASCII-only normaliser would blank this out and reject every real quote.
    body = _squash("แบตเตอรี่หมดเร็วมาก ใช้ได้แค่สองชั่วโมง!")
    quote = _squash("แบตเตอรี่หมดเร็วมาก")

    assert quote and quote in body
