"""The executive report: the one artefact a business person actually reads.

The agent is handed facts, not raw data. Prices, indices and stock rates arrive
pre-computed from SQL; aspect sentiment arrives with verified quotes and their
review ids. The model's remaining job is judgement and narrative — and every
qualitative claim it makes has to cite the review ids it rests on. Citations
pointing at reviews we never sent are stripped before the report is returned.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.analysis.changes import MarketChanges, analyse_changes
from app.analysis.pricing import PriceIntelligence, analyse_pricing
from app.analysis.sentiment import SentimentReport, analyse_sentiment
from app.config import get_settings
from app.llm import TokenUsage, instructor_client
from app.storage import Catalogue

SYSTEM_PROMPT = """You are a competitive intelligence analyst writing for a product executive.

You are given VERIFIED FACTS: price statistics computed from the catalogue, and aspect-level
sentiment extracted from real customer reviews with their review ids.

Rules:
- Never invent a number. Every figure you use must appear in the facts given to you.
- Every finding that rests on customer opinion MUST cite the review ids it came from.
- Be specific and commercial. "Brand X wins on battery life" is useless; "Brand X's battery
  draws 4 of 6 negative mentions in the category, while Brand Y draws none" is useful.
- Recommendations must be actions the reader can take (pricing move, feature investment,
  positioning change), each with the reason it follows from the evidence.
- If the evidence is thin, say so plainly instead of padding.
{language_rule}"""

# Brand names, product names, metrics and review ids stay as they are in every
# language — translating them would break the link back to the evidence.
LANGUAGE_RULE = {
    "en": "",
    "th": (
        "- Write ALL prose in Thai (ภาษาไทย): headline, summary, positioning, findings,\n"
        "  rationales. Keep brand names, product names, review ids and numbers exactly as\n"
        "  given — do not translate or reformat them. Business terms may stay in English\n"
        "  where that is what Thai product teams actually say (เช่น margin, positioning).\n"
    ),
}


class Finding(BaseModel):
    claim: str
    evidence_review_ids: list[str] = Field(default_factory=list)
    supporting_metric: str | None = Field(
        default=None, description="a figure copied verbatim from the supplied facts"
    )


class CompetitorProfile(BaseModel):
    brand: str
    positioning: str = Field(description="one line: where this brand sits in the market")
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    evidence_review_ids: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    action: str
    rationale: str
    priority: Literal["high", "medium", "low"] = "medium"


class _ReportDraft(BaseModel):
    """The part of the report the LLM writes."""

    headline: str = Field(description="one sentence a CEO could read alone")
    summary: str = Field(description="3-5 sentences of executive summary")
    competitors: list[CompetitorProfile] = Field(default_factory=list)
    opportunities: list[Finding] = Field(default_factory=list)
    threats: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)


class ExecutiveReport(BaseModel):
    category: str | None = None
    language: str = "en"
    generated_at: datetime
    products_analysed: int
    reviews_analysed: int
    headline: str
    summary: str
    competitors: list[CompetitorProfile] = Field(default_factory=list)
    opportunities: list[Finding] = Field(default_factory=list)
    threats: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    pricing: PriceIntelligence
    sentiment: SentimentReport
    changes: MarketChanges | None = None
    citations_dropped: int = Field(
        default=0, description="review ids the model cited that do not exist"
    )
    usage: dict = Field(default_factory=dict)


def build_report(
    cat: Catalogue,
    category: str | None = None,
    review_limit: int = 100,
    model: str | None = None,
    language: str = "en",
    change_window_days: int = 7,
) -> ExecutiveReport:
    settings = get_settings()

    pricing = analyse_pricing(cat, category, language=language)
    changes = analyse_changes(cat, category, days=change_window_days, language=language)
    sentiment = analyse_sentiment(
        cat, category=category, limit=review_limit, model=model, language=language
    )

    usage = TokenUsage()
    client = instructor_client()
    draft, completion = client.chat.completions.create_with_completion(
        model=model or settings.llm_model,
        response_model=_ReportDraft,
        max_retries=2,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    language_rule=LANGUAGE_RULE.get(language, "")
                ),
            },
            {
                "role": "user",
                "content": _render_facts(category, pricing, sentiment, changes),
            },
        ],
    )
    usage.add(completion)
    if sentiment.usage:
        usage.merge(_usage_from_dict(sentiment.usage))

    known_ids = {
        e["review_id"] for aspect in sentiment.aspects for e in aspect.evidence
    }
    dropped = _strip_unknown_citations(draft, known_ids)

    return ExecutiveReport(
        category=category,
        language=language,
        generated_at=datetime.now(timezone.utc),
        products_analysed=pricing.distribution.get("count", 0),
        reviews_analysed=sentiment.reviews_analysed,
        headline=draft.headline,
        summary=draft.summary,
        competitors=draft.competitors,
        opportunities=draft.opportunities,
        threats=draft.threats,
        recommendations=draft.recommendations,
        pricing=pricing,
        sentiment=sentiment,
        changes=changes,
        citations_dropped=dropped,
        usage=usage.as_dict(),
    )


def _render_facts(
    category: str | None,
    pricing: PriceIntelligence,
    sentiment: SentimentReport,
    changes: MarketChanges | None = None,
) -> str:
    facts = {
        "category": category or "all categories",
        "price_distribution": pricing.distribution,
        "brand_positions": [b.model_dump(exclude_none=True) for b in pricing.brands],
        "price_gaps": [g.model_dump() for g in pricing.gaps],
        "computed_observations": pricing.observations,
        "review_aspects": [
            {
                "aspect": a.aspect,
                "mentions": a.mentions,
                "avg_score": a.avg_score,
                "positive": a.positive,
                "negative": a.negative,
                "by_brand": a.brands,
                "quotes": a.evidence,
            }
            for a in sentiment.aspects
        ],
        "brand_sentiment": [b.model_dump() for b in sentiment.brands],
        "reviews_analysed": sentiment.reviews_analysed,
    }

    if changes and changes.has_history:
        facts["what_changed"] = {
            "compared": f"{changes.baseline_day} → {changes.latest_day}",
            "median_before": changes.median_before,
            "median_after": changes.median_after,
            "median_change_pct": changes.median_change_pct,
            # Only the largest moves: a long tail of 2% wobbles would drown the
            # findings that matter.
            "price_moves": [m.model_dump() for m in changes.price_moves[:10]],
            "stock_flips": [f.model_dump() for f in changes.stock_flips[:10]],
            "new_products": [p.model_dump() for p in changes.new_products[:5]],
            "disappeared": [p.model_dump() for p in changes.disappeared[:5]],
            "computed_observations": changes.observations,
        }

    instruction = "Write the executive report. Cite review ids from the quotes above."
    if changes and changes.has_history:
        instruction += (
            " The catalogue has been crawled more than once: treat what_changed as the "
            "freshest signal — a competitor moving price is more actionable than a "
            "standing price difference — and say explicitly what moved."
        )
    return (
        "VERIFIED FACTS (the only numbers you may use):\n"
        + json.dumps(facts, ensure_ascii=False, indent=2, default=str)
        + "\n\n"
        + instruction
    )


def _strip_unknown_citations(draft: _ReportDraft, known_ids: set[str]) -> int:
    """Remove citations to reviews that were never shown to the model."""
    dropped = 0
    groups = [draft.opportunities, draft.threats, draft.competitors]
    for group in groups:
        for item in group:
            valid = [rid for rid in item.evidence_review_ids if rid in known_ids]
            dropped += len(item.evidence_review_ids) - len(valid)
            item.evidence_review_ids = valid
    return dropped


def _usage_from_dict(data: dict) -> TokenUsage:
    usage = TokenUsage()
    usage.prompt_tokens = data.get("prompt_tokens", 0)
    usage.completion_tokens = data.get("completion_tokens", 0)
    usage.total_tokens = data.get("total_tokens", 0)
    usage.llm_calls = data.get("llm_calls", 0)
    usage.models = list(data.get("models", []))
    return usage
