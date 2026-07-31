"""The anti-hallucination guards, tested without ever calling an LLM.

These are the checks that decide what the report is allowed to claim, so they
are worth testing directly rather than through a live model.
"""
from __future__ import annotations

from app.analysis.report import Finding, _ReportDraft, _strip_unknown_citations
from app.analysis.sentiment import (
    AspectMention,
    _summarise_aspects,
    _summarise_brands,
    _verify,
)

REVIEWS = {
    "r1": {
        "id": "r1",
        "title": "",
        "body": "The battery dies after two hours and the screen is dim.",
        "brand": "Acme",
        "product_title": "Acme Laptop",
    },
    "r2": {
        "id": "r2",
        "title": "",
        "body": "Shipping was fast and the build quality feels premium.",
        "brand": "Beta",
        "product_title": "Beta Laptop",
    },
}


def mention(review_id: str, aspect: str, score: float, evidence: str) -> AspectMention:
    return AspectMention(
        review_id=review_id,
        aspect=aspect,
        polarity="negative" if score < 0 else "positive",
        score=score,
        evidence=evidence,
    )


def test_verify_accepts_a_real_quote():
    assert _verify(mention("r1", "battery life", -0.8, "battery dies after two hours"), REVIEWS)


def test_verify_rejects_an_unknown_review_id():
    # The model invented a review that was never in the batch.
    assert not _verify(mention("r99", "battery life", -0.8, "battery dies"), REVIEWS)


def test_verify_rejects_a_quote_the_review_never_contained():
    assert not _verify(
        mention("r1", "customer support", -0.9, "support hung up on me twice"), REVIEWS
    )


def test_verify_ignores_punctuation_and_case():
    assert _verify(mention("r2", "shipping speed", 0.7, "Shipping was FAST!"), REVIEWS)


def test_aspect_names_are_normalised():
    assert mention("r1", "  Battery   LIFE ", -0.5, "battery dies").aspect == "battery life"


def test_summarise_aspects_groups_and_counts():
    mentions = [
        mention("r1", "battery life", -0.8, "battery dies after two hours"),
        mention("r2", "battery life", 0.6, "build quality feels premium"),
        mention("r2", "shipping speed", 0.9, "Shipping was fast"),
    ]

    summaries = {a.aspect: a for a in _summarise_aspects(mentions, REVIEWS)}

    battery = summaries["battery life"]
    assert battery.mentions == 2
    assert battery.positive == 1 and battery.negative == 1
    assert battery.avg_score == -0.1
    assert battery.brands == {"Acme": 1, "Beta": 1}


def test_summarise_brands_splits_strengths_from_weaknesses():
    mentions = [
        mention("r1", "battery life", -0.8, "battery dies"),
        mention("r2", "shipping speed", 0.9, "Shipping was fast"),
    ]

    brands = {b.brand: b for b in _summarise_brands(mentions, REVIEWS)}

    assert brands["Acme"].weaknesses == ["battery life"]
    assert brands["Acme"].strengths == []
    assert brands["Beta"].strengths == ["shipping speed"]


def test_report_strips_citations_to_unknown_reviews():
    draft = _ReportDraft(
        headline="h",
        summary="s",
        opportunities=[Finding(claim="battery is a weak spot", evidence_review_ids=["r1", "ghost"])],
        threats=[Finding(claim="rivals ship faster", evidence_review_ids=["nope"])],
    )

    dropped = _strip_unknown_citations(draft, known_ids={"r1", "r2"})

    assert dropped == 2
    assert draft.opportunities[0].evidence_review_ids == ["r1"]
    assert draft.threats[0].evidence_review_ids == []
