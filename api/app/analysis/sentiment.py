"""Aspect-based sentiment over competitor reviews.

Plain positive/negative tells you a brand is disliked. Aspect-based tells you
*what* is disliked — "battery life", "shipping speed", "fit" — which is the
part a product team can act on.

Two guards keep the output honest:
  1. every mention must carry a review_id that was actually in the batch;
  2. its evidence quote must really appear in that review's text.
Anything else is dropped and counted, so the discard rate is visible instead of
silently polluting the report.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.llm import TokenUsage, instructor_client
from app.storage import Catalogue

SYSTEM_PROMPT = """You are a market research analyst extracting aspect-level sentiment from customer reviews.

For every review, identify each distinct ASPECT the customer talks about (e.g. "battery life",
"build quality", "shipping speed", "price", "customer support", "taste", "fit").

Rules:
- Use the exact review_id given for the review the mention came from.
- aspect: 2-3 words, lowercase, generic enough to group across reviews.{aspect_language}
- score: -1.0 (furious) to 1.0 (delighted); 0 for neutral mentions.
- evidence: a VERBATIM span copied from that review, in the review's own language.
  Never translate it, never paraphrase, never invent — it is checked against the source text.
- A review with no substantive opinion produces no mentions. Returning fewer mentions is
  correct and expected; padding the list is a failure.
"""

# Aspect names are report-facing labels, so they follow the report language.
# Evidence quotes never do: they are verified against the original review text.
ASPECT_LANGUAGE = {
    "en": "",
    "th": " Write the aspect name in Thai (ภาษาไทย), e.g. \"แบตเตอรี่\", \"ความเร็วจัดส่ง\".",
}


class AspectMention(BaseModel):
    review_id: str
    aspect: str
    polarity: Literal["positive", "negative", "mixed", "neutral"]
    score: float = Field(ge=-1.0, le=1.0)
    evidence: str

    @field_validator("aspect")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return re.sub(r"\s+", " ", v.strip().lower())


class _BatchResult(BaseModel):
    """What the LLM returns for one batch of reviews."""

    mentions: list[AspectMention] = Field(default_factory=list)


class AspectSummary(BaseModel):
    aspect: str
    mentions: int
    avg_score: float
    positive: int
    negative: int
    brands: dict[str, int] = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)


class BrandSentiment(BaseModel):
    brand: str
    mentions: int
    avg_score: float
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class SentimentReport(BaseModel):
    category: str | None = None
    brand: str | None = None
    language: str = "en"
    reviews_analysed: int
    mentions_kept: int
    mentions_discarded: int = Field(
        default=0, description="mentions rejected for a bad id or unverifiable quote"
    )
    aspects: list[AspectSummary] = Field(default_factory=list)
    brands: list[BrandSentiment] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


def analyse_sentiment(
    cat: Catalogue,
    category: str | None = None,
    brand: str | None = None,
    limit: int = 100,
    model: str | None = None,
    language: str = "en",
) -> SentimentReport:
    settings = get_settings()
    reviews = cat.reviews(category=category, brand=brand, limit=limit)
    if not reviews:
        return SentimentReport(
            category=category, brand=brand, language=language, reviews_analysed=0,
            mentions_kept=0, mentions_discarded=0,
        )

    client = instructor_client()
    usage = TokenUsage()
    by_id = {r["id"]: r for r in reviews}
    kept: list[AspectMention] = []
    discarded = 0

    for batch in _chunks(reviews, settings.reviews_per_llm_call):
        result, completion = client.chat.completions.create_with_completion(
            model=model or settings.llm_model,
            response_model=_BatchResult,
            max_retries=2,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(
                        aspect_language=ASPECT_LANGUAGE.get(language, "")
                    ),
                },
                {"role": "user", "content": _render_batch(batch, settings.max_review_chars)},
            ],
        )
        usage.add(completion)

        for mention in result.mentions:
            if _verify(mention, by_id):
                kept.append(mention)
            else:
                discarded += 1

    return SentimentReport(
        category=category,
        brand=brand,
        language=language,
        reviews_analysed=len(reviews),
        mentions_kept=len(kept),
        mentions_discarded=discarded,
        aspects=_summarise_aspects(kept, by_id),
        brands=_summarise_brands(kept, by_id),
        usage=usage.as_dict(),
    )


def _verify(mention: AspectMention, by_id: dict[str, dict]) -> bool:
    """Reject mentions that cite a review we never sent, or quote text it never contained."""
    review = by_id.get(mention.review_id)
    if review is None:
        return False
    haystack = _squash(f"{review.get('title', '')} {review['body']}")
    needle = _squash(mention.evidence)
    # A short quote is allowed to be a loose match; anything longer must be a
    # real substring of the review.
    return bool(needle) and (needle in haystack or len(needle) < 12)


def _squash(text: str) -> str:
    """Normalise for quote matching: drop punctuation, keep letters of any script.

    `\\w` is unicode-aware, so a Thai or Japanese review survives this; an
    ASCII-only filter would blank it out and reject every real quote.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", "", text.lower())).strip()


def _render_batch(batch: list[dict], max_chars: int) -> str:
    lines = []
    for r in batch:
        body = r["body"][:max_chars]
        rating = f"{r['rating']}/5" if r.get("rating") else "no rating"
        lines.append(
            f"review_id: {r['id']}\nbrand: {r.get('brand', '')} | product: "
            f"{r.get('product_title', '')} | rating: {rating}\ntext: {body}\n"
        )
    return "Extract aspect-level sentiment from these reviews:\n\n" + "\n".join(lines)


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _summarise_aspects(
    mentions: list[AspectMention], by_id: dict[str, dict], top: int = 12
) -> list[AspectSummary]:
    grouped: dict[str, list[AspectMention]] = defaultdict(list)
    for m in mentions:
        grouped[m.aspect].append(m)

    summaries = []
    for aspect, group in grouped.items():
        brands: dict[str, int] = defaultdict(int)
        for m in group:
            brands[by_id[m.review_id].get("brand", "(unbranded)")] += 1
        # Keep the most extreme quotes: they are what a report would cite.
        evidence = sorted(group, key=lambda m: abs(m.score), reverse=True)[:3]
        summaries.append(
            AspectSummary(
                aspect=aspect,
                mentions=len(group),
                avg_score=round(sum(m.score for m in group) / len(group), 3),
                positive=sum(1 for m in group if m.score > 0.15),
                negative=sum(1 for m in group if m.score < -0.15),
                brands=dict(sorted(brands.items(), key=lambda kv: kv[1], reverse=True)),
                evidence=[
                    {
                        "review_id": m.review_id,
                        "brand": by_id[m.review_id].get("brand"),
                        "product": by_id[m.review_id].get("product_title"),
                        "score": m.score,
                        "quote": m.evidence,
                    }
                    for m in evidence
                ],
            )
        )
    summaries.sort(key=lambda a: a.mentions, reverse=True)
    return summaries[:top]


def _summarise_brands(
    mentions: list[AspectMention], by_id: dict[str, dict]
) -> list[BrandSentiment]:
    grouped: dict[str, list[AspectMention]] = defaultdict(list)
    for m in mentions:
        grouped[by_id[m.review_id].get("brand", "(unbranded)")].append(m)

    out = []
    for brand, group in grouped.items():
        per_aspect: dict[str, list[float]] = defaultdict(list)
        for m in group:
            per_aspect[m.aspect].append(m.score)
        averaged = {a: sum(s) / len(s) for a, s in per_aspect.items()}
        ranked = sorted(averaged.items(), key=lambda kv: kv[1], reverse=True)

        out.append(
            BrandSentiment(
                brand=brand,
                mentions=len(group),
                avg_score=round(sum(m.score for m in group) / len(group), 3),
                strengths=[a for a, s in ranked if s > 0.15][:3],
                weaknesses=[a for a, s in reversed(ranked) if s < -0.15][:3],
            )
        )
    out.sort(key=lambda b: b.mentions, reverse=True)
    return out
