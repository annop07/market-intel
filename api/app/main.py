"""Market Intelligence API.

Pipeline: the Go collector POSTs to /ingest → products land in SQLite and their
reviews are embedded into Qdrant → /analyze/* computes the facts → /report has
the agent write an evidence-cited executive report.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from openai import APIError
from pydantic import BaseModel, Field

from app.analysis.changes import MarketChanges, analyse_changes
from app.analysis.pricing import PriceIntelligence, analyse_pricing
from app.analysis.report import ExecutiveReport, build_report
from app.analysis.sentiment import SentimentReport, analyse_sentiment
from app.config import get_settings
from app.contract import IngestRequest, IngestResponse
from app.llm import TokenUsage, instructor_client
from app.render import report_to_markdown
from app.storage import get_catalogue
from app.vectorstore import get_vector_store

app = FastAPI(
    title="Market Intelligence Agent",
    version="0.1.0",
    description=(
        "Competitor catalogues in, an evidence-cited executive report out. "
        "Numbers are computed in SQL; the LLM only writes the narrative."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    cat = get_catalogue()
    return {
        "status": "ok",
        "llm_configured": settings.llm_configured,
        "llm_model": settings.llm_model,
        "products": cat.count_products(),
        "reviews": cat.count_reviews(),
        "vectors": get_vector_store().count(),
        "sources": cat.sources(),
    }


@app.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest) -> IngestResponse:
    """Accept a batch from the collector: store it, then embed it."""
    cat = get_catalogue()
    products, reviews = cat.upsert_products(request.products)
    vectors = get_vector_store().index_products(request.products)
    return IngestResponse(
        products_upserted=products,
        reviews_upserted=reviews,
        vectors_indexed=vectors,
        catalogue_size=cat.count_products(),
    )


@app.get("/catalogue")
def catalogue(
    category: str | None = None,
    brand: str | None = None,
    source: str | None = None,
    limit: int = Query(default=50, le=500),
    min_products: int = Query(
        default=5,
        ge=1,
        description="hide long-tail categories — a segment of two items has no market to analyse",
    ),
) -> dict:
    cat = get_catalogue()
    return {
        "categories": cat.categories(min_products=min_products),
        "sources": cat.sources(),
        "products": cat.products(category=category, brand=brand, source=source, limit=limit),
    }


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    kind: str | None = Field(default=None, description='"product" or "review"')
    category: str | None = None
    brand: str | None = None


@app.post("/search")
def search(request: SearchRequest) -> dict:
    """Similarity search across products and reviews, filtered by payload."""
    hits = get_vector_store().search(
        request.query,
        top_k=request.top_k,
        kind=request.kind,
        category=request.category,
        brand=request.brand,
    )
    return {"query": request.query, "hits": hits}


# The reviews stay in whatever language they were written in; only the answer
# and the report prose follow the reader's choice.
LANGUAGES = {"en", "th"}
ANSWER_LANGUAGE = {
    "en": "Answer in English.",
    "th": "ตอบเป็นภาษาไทย แต่คงชื่อแบรนด์ ชื่อสินค้า และ review id ไว้ตามเดิม",
}


def _find_api_error(exc: BaseException | None) -> APIError | None:
    """Dig the provider's own error out of whatever wrapped it.

    Instructor retries failed calls and raises its own exception, so the useful
    message ("daily limit", "model not found") is two or three levels down the
    __cause__ chain.
    """
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, APIError):
            return exc
        exc = exc.__cause__ or exc.__context__
    return None


@contextmanager
def llm_errors():
    """Turn provider failures into a 502 that says what actually went wrong.

    A quota or auth problem at the LLM endpoint is not a bug in this service and
    should not read like one — an opaque 500 sends you debugging the wrong box.
    """
    try:
        yield
    except HTTPException:
        raise
    except Exception as exc:
        api_error = _find_api_error(exc)
        if api_error is None:
            raise
        message = getattr(api_error, "message", None) or str(api_error)
        raise HTTPException(status_code=502, detail=f"LLM provider: {message}") from exc


def _language(value: str | None) -> str:
    if value and value not in LANGUAGES:
        raise HTTPException(
            status_code=400, detail=f"language must be one of {sorted(LANGUAGES)}"
        )
    return value or "en"


class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=8, ge=1, le=30)
    category: str | None = None
    brand: str | None = None
    model: str | None = None
    language: str = "en"


class AskResponse(BaseModel):
    answer: str
    citations: list[str] = Field(default_factory=list)
    hits: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


class _GroundedAnswer(BaseModel):
    answer: str = Field(description="2-4 sentences answering the question")
    citations: list[str] = Field(
        default_factory=list, description="review ids from the context that support the answer"
    )


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """RAG over the review corpus — semantic questions across brands."""
    settings = get_settings()
    if not settings.llm_configured:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    language = _language(request.language)

    hits = get_vector_store().search(
        request.question,
        top_k=request.top_k,
        kind="review",
        category=request.category,
        brand=request.brand,
    )
    if not hits:
        raise HTTPException(status_code=404, detail="no reviews indexed for that filter")

    context = "\n".join(
        f'[{h.get("review_id")}] {h.get("brand")} — {h.get("product_title")}: {h["text"]}'
        for h in hits
    )
    usage = TokenUsage()
    with llm_errors():
        result, completion = instructor_client().chat.completions.create_with_completion(
            model=request.model or settings.llm_model,
            response_model=_GroundedAnswer,
            max_retries=2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer strictly from the customer reviews provided. Cite the "
                        "review ids you used. If the reviews do not answer the question, "
                        "say so. " + ANSWER_LANGUAGE[language]
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {request.question}\n\nReviews:\n{context}",
                },
            ],
        )
    usage.add(completion)

    known = {h.get("review_id") for h in hits}
    return AskResponse(
        answer=result.answer,
        citations=[c for c in result.citations if c in known],
        hits=hits,
        usage=usage.as_dict(),
    )


@app.get("/analyze/pricing", response_model=PriceIntelligence)
def pricing(
    category: str | None = None,
    language: str | None = Query(default=None, description='"en" or "th"'),
) -> PriceIntelligence:
    """Deterministic price intelligence — no LLM involved."""
    return analyse_pricing(get_catalogue(), category, language=_language(language))


@app.get("/analyze/changes", response_model=MarketChanges)
def changes(
    category: str | None = None,
    days: int = Query(default=7, ge=1, le=365),
    min_move_pct: float = Query(default=2.0, ge=0),
    language: str | None = Query(default=None, description='"en" or "th"'),
) -> MarketChanges:
    """What moved since the crawl closest to `days` ago — deterministic, no LLM."""
    return analyse_changes(
        get_catalogue(),
        category=category,
        days=days,
        min_move_pct=min_move_pct,
        language=_language(language),
    )


@app.get("/analyze/history")
def history(
    category: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Daily market shape: product count, median price, in-stock rate."""
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    cat = get_catalogue()
    return {
        "category": category,
        "since": since,
        "days_observed": len(cat.snapshot_days(category)),
        "series": cat.daily_series(category=category, since=since),
    }


@app.post("/analyze/sentiment", response_model=SentimentReport)
def sentiment(
    category: str | None = None,
    brand: str | None = None,
    limit: int = Query(default=100, le=500),
    model: str | None = None,
    language: str | None = Query(default=None, description='"en" or "th"'),
) -> SentimentReport:
    if not get_settings().llm_configured:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    with llm_errors():
        return analyse_sentiment(
            get_catalogue(),
            category=category,
            brand=brand,
            limit=limit,
            model=model,
            language=_language(language),
        )


class ReportRequest(BaseModel):
    category: str | None = None
    review_limit: int = Field(default=100, ge=1, le=500)
    model: str | None = None
    language: str = Field(default="en", description='prose language: "en" or "th"')
    save: bool = Field(default=False, description="also write reports/<date>.md")


@app.post("/report", response_model=ExecutiveReport)
def report(request: ReportRequest = Body(default=ReportRequest())) -> ExecutiveReport:
    if not get_settings().llm_configured:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    with llm_errors():
        result = build_report(
            get_catalogue(),
            category=request.category,
            review_limit=request.review_limit,
            model=request.model,
            language=_language(request.language),
        )
    if request.save:
        save_report(result)
    return result


@app.get("/report/latest.md", response_class=PlainTextResponse)
def latest_markdown(language: str | None = Query(default=None)) -> str:
    """The most recent saved report, as Markdown."""
    return _latest_file("md", _language(language)).read_text(encoding="utf-8")


@app.get("/report/latest.json")
def latest_json(language: str | None = Query(default=None)) -> dict:
    """The most recent saved report as data.

    The dashboard reads this instead of calling /report, so opening a page
    costs no tokens — the charts show the last report that was actually run.
    """
    return json.loads(_latest_file("json", _language(language)).read_text(encoding="utf-8"))


def _latest_file(extension: str, language: str) -> Path:
    """Newest saved report for a language.

    Thai reports are written with a `-th` suffix, so each language has its own
    archive and switching the dashboard never shows a stale translation.
    """
    directory = Path(get_settings().report_dir)
    if not directory.exists():
        raise HTTPException(status_code=404, detail="no report has been saved yet")

    files = sorted(directory.glob(f"*.{extension}"))
    if language == "en":
        files = [f for f in files if not f.stem.endswith("-th")]
    else:
        files = [f for f in files if f.stem.endswith(f"-{language}")]

    if not files:
        raise HTTPException(
            status_code=404, detail=f"no report has been saved in language '{language}'"
        )
    return files[-1]


def save_report(result: ExecutiveReport) -> Path:
    """Write reports/YYYY-MM-DD[-category][-lang].{md,json} — one to read, one to plot."""
    directory = Path(get_settings().report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    category = f"-{result.category}" if result.category else ""
    # English stays unsuffixed so existing report links keep working.
    language = "" if result.language == "en" else f"-{result.language}"
    path = directory / f"{stamp}{category}{language}.md"
    path.write_text(report_to_markdown(result), encoding="utf-8")
    path.with_suffix(".json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    return path
