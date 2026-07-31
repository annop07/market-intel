# Market Intelligence Agent

> **Week 4 Bootcamp deliverable** — a Go collector, a Python analysis agent and a Next.js
> dashboard that turn competitor catalogues and customer reviews into an **evidence-cited
> executive report**.

Point it at a set of e-commerce sources; it crawls them politely, embeds every review,
computes the price landscape in SQL, extracts aspect-level sentiment with an LLM, and writes
a report a product executive can act on — with every claim traceable to a review id.

A sample of the real output: [`reports/2026-07-31-smartphones.md`](reports/2026-07-31-smartphones.md).

## What it demonstrates

| Skill (Week 4) | Where it lives |
| --- | --- |
| Concurrent Go scraper — worker pool, rate limiting, retry/backoff | [`scraper/internal/runner/runner.go`](scraper/internal/runner/runner.go), [`scraper/internal/fetch/client.go`](scraper/internal/fetch/client.go) |
| Pluggable source adapters (add a platform = add one file) | [`scraper/internal/source/`](scraper/internal/source/) |
| robots.txt compliance (own parser: groups, wildcards, longest-match) | [`scraper/internal/fetch/robots.go`](scraper/internal/fetch/robots.go) |
| Cross-language data contract (Go struct ↔ Pydantic model) | [`scraper/internal/model/model.go`](scraper/internal/model/model.go) ↔ [`api/app/contract.py`](api/app/contract.py) |
| Vector pipeline — local embeddings + similarity search over reviews | [`api/app/vectorstore.py`](api/app/vectorstore.py), `POST /search` |
| RAG Q&A across brands with citation filtering | [`api/app/main.py`](api/app/main.py), `POST /ask` |
| Deterministic price & feature intelligence (no LLM) | [`api/app/analysis/pricing.py`](api/app/analysis/pricing.py), `GET /analyze/pricing` |
| Price history & change detection across crawls | [`api/app/analysis/changes.py`](api/app/analysis/changes.py), `GET /analyze/changes` · `/analyze/history` |
| Aspect-based sentiment with hallucination guards | [`api/app/analysis/sentiment.py`](api/app/analysis/sentiment.py), `POST /analyze/sentiment` |
| Structured Output — executive report as a validated schema | [`api/app/analysis/report.py`](api/app/analysis/report.py), `POST /report` |
| Dashboard (Next.js + Recharts) | [`dashboard/src/app/page.tsx`](dashboard/src/app/page.tsx) |
| Bilingual output — UI, RAG answers and the report itself (EN / ไทย) | [`dashboard/src/lib/i18n.ts`](dashboard/src/lib/i18n.ts), [`api/app/render.py`](api/app/render.py) |
| Dockerised stack + nightly GitHub Actions pipeline | [`docker-compose.yml`](docker-compose.yml), [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) |

## Architecture

```
 sources ──▶ Go collector ──JSONL / POST──▶ FastAPI ──▶ SQLite  (catalogue + daily snapshots)
             │  worker pool                     │      └─▶ Qdrant (fastembed, local)
             │  rate limit + retry              │
             │  robots.txt                      ├─▶ pricing.py    deterministic stats
             └─ source adapters                 ├─▶ changes.py    what moved since last crawl
                                                ├─▶ sentiment.py  aspect extraction + guards
                                                ├─▶ /ask          RAG over reviews
                                                └─▶ report.py ──▶ ExecutiveReport (Pydantic)
                                                                   ├─▶ reports/*.md   (CI commits)
                                                                   ├─▶ reports/*.json (dashboard)
                                                                   ├─▶ history/*.csv  (CI commits)
                                                                   └─▶ Next.js dashboard
```

## Sources

| Name | What it gives | Why this one |
| --- | --- | --- |
| `dummyjson` | ~194 products, ~30 brands, 24 categories, 582 reviews | A public sandbox API — the richest legal stand-in for a marketplace catalogue, and the source the competitor analysis actually runs on |
| `books` | up to 1000 products, categories, ratings, spec tables | books.toscrape.com, published for scraping practice — the real HTML path: pagination, detail pages, messy availability strings |
| `scrapeme` | ~755 products, WooCommerce taxonomy, stock state | scrapeme.live, another sandbox storefront — everything is on the listing pages, so a large catalogue costs ~15 requests |

**A note on target selection.** The first adapter written for this project pointed at
webscraper.io's e-commerce test site. Its robots.txt carries `Disallow: /test-sites/e-commerce/`,
the fetch layer refused every request, and the adapter was deleted rather than the check
switched off. Marketplaces like Shopee and Lazada are off the table for the same reason —
their terms forbid it and their bot protection is there to be respected, not defeated.
Adding a platform you *are* allowed to crawl is one file in
[`scraper/internal/source/`](scraper/internal/source/).

## Three decisions worth knowing about

**1. The LLM never computes a number.** Prices, medians, price indices, discount depth and
stock rates all come out of SQL in [`storage.py`](api/app/storage.py) and
[`pricing.py`](api/app/analysis/pricing.py). The model receives those figures as *verified
facts* and writes the narrative around them. Rerun the report and the numbers are identical;
only the prose moves.

**2. Every qualitative claim carries evidence.** Aspect extraction must return a `review_id`
that was actually in the batch and a quote that really appears in that review — anything else
is dropped and counted ([`_verify`](api/app/analysis/sentiment.py)). The report agent's
citations are filtered against the reviews it was shown. Both counts are printed at the bottom
of every report, so the hallucination rate is visible instead of hidden.

**3. Sentiment is aspect-level, not positive/negative.** "Customers dislike Apple" is not
actionable. "`product description` draws 5 of 5 negative mentions across four brands" is.

## The market has a shape over time

Every crawl writes one snapshot per product per day into `price_snapshots`, so re-running the
collector builds history instead of overwriting yesterday. [`changes.py`](api/app/analysis/changes.py)
then diffs the latest crawl against the one closest to N days ago and reports what moved:
price cuts and rises above a noise floor, stock flips, listings that appeared or vanished, and
the shift in the category median. All arithmetic — the model is handed the diff, never asked
to spot it, and the report leads with it because a competitor cutting price *this week* beats
a price difference that has been true for months.

CI runners are ephemeral, so the pipeline reads and writes
[`history/price-history.csv`](history/) and the nightly job commits it. The history is a CSV
in the repo rather than a binary database: you can diff it, and so can a reviewer.

With a single crawl the API says `has_history: false` and the dashboard says so too — one
observation is a snapshot, not a trend, and pretending otherwise would be the easiest lie in
the whole project.

To see the trend UI before you have days of real history, generate a **clearly-labelled
synthetic** history into a separate database:

```bash
uv run python -m scripts.seed_demo_history      # writes ./data/demo.db, never touches market.db
DATABASE_PATH=./data/demo.db uv run uvicorn app.main:app --port 8001
```

## Two languages, one set of numbers

The dashboard has an **EN / ไทย** toggle, and it goes all the way down: interface labels,
the rule-based findings from [`pricing.py`](api/app/analysis/pricing.py), the aspect names,
the RAG answers, and the executive report prose. Reports are written per language
(`2026-07-31-smartphones.md` and `…-th.md`), so switching loads the report that was actually
written in that language instead of showing English under a Thai heading.

Three things never get translated, because translating them would break the audit trail:
**figures** (computed once, identical in both languages), **brand and product names**, and
**evidence quotes** — a quote is verified character-by-character against the original review,
so it stays in the language the customer wrote it in.

```bash
uv run python -m scripts.pipeline --input "../data/raw/*.jsonl" --report --category smartphones --language th
```

## Quick start

### 1. Collect

```bash
cd scraper
go run ./cmd/collect -source all -limit 200 -out "../data/raw/{source}.jsonl"
```

Useful flags: `-source dummyjson,books` · `-concurrency 6` · `-rps 4` · `-list` ·
`-api http://localhost:8001/ingest` (stream straight into the API).

### 2. Analyse

```bash
cd api
cp .env.example .env          # add your OPENAI_API_KEY (any OpenAI-compatible endpoint)
uv sync
uv run python -m scripts.pipeline --input "../data/raw/*.jsonl" --report --category smartphones
```

That ingests, embeds, analyses and writes `reports/<date>-smartphones.md` + `.json`.

To run the API instead:

```bash
uv run uvicorn app.main:app --reload --port 8001
```

Interactive docs at **http://localhost:8001/docs**.

### 3. Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Open **http://localhost:3000** (API base is set in `dashboard/.env.local`).

### Docker

```bash
docker compose up -d qdrant api
docker compose run --rm collector
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | liveness, catalogue size, per-source counts |
| POST | `/ingest` | accept a batch from the collector → SQLite + Qdrant |
| GET | `/catalogue` | categories, sources, products (filterable) |
| POST | `/search` | similarity search over products and reviews |
| POST | `/ask` | RAG Q&A over the review corpus, with citations |
| GET | `/analyze/pricing` | deterministic price intelligence (no LLM, no key needed) |
| GET | `/analyze/changes` | what moved since the crawl closest to `days` ago |
| GET | `/analyze/history` | daily series: product count, median price, in-stock rate |
| POST | `/analyze/sentiment` | aspect-based sentiment for a category or brand |
| POST | `/report` | full executive report (`save=true` writes to `reports/`) |
| GET | `/report/latest.md` · `/report/latest.json` | the last saved report |

Everything that produces prose takes `language` (`en` \| `th`): `/ask`, `/analyze/pricing`,
`/analyze/changes`, `/analyze/sentiment`, `/report`, and both `/report/latest.*`. An unknown code is a **400**,
and a failure at the LLM endpoint (quota, bad model id) comes back as a **502** carrying the
provider's own message rather than an opaque 500.

## Try it

```bash
# What do customers complain about across the category?
curl -s localhost:8001/ask -H 'content-type: application/json' \
  -d '{"question":"What do customers complain about most in smartphones?","category":"smartphones"}' | jq

# Price landscape — pure SQL, works without an API key
curl -s "localhost:8001/analyze/pricing?category=smartphones" | jq '.observations'

# Find products similar to a competitor's, across sources
curl -s localhost:8001/search -H 'content-type: application/json' \
  -d '{"query":"lightweight laptop for students","kind":"product","top_k":5}' | jq
```

## Tests

```bash
cd scraper && go test -race ./...   # retry policy, robots parser, worker pool, adapters
cd api && uv run pytest             # storage, pricing maths, hallucination guards
```

Both suites are offline: no API key, no network, no model download. The scraper tests serve
their own fixtures from `httptest`; the Python tests exercise the deterministic half of the
system and the guards that decide what the report may claim.

## Automation

[`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) runs nightly: crawl →
embed → analyse → report → commit `reports/<date>.md` back to the repository. The repo becomes
the archive — open any dated file to see what the market looked like that morning.
[`ci.yml`](.github/workflows/ci.yml) runs `go vet`, `go test -race` and `pytest` on every push.

## Tech stack

Go 1.26 (goquery · x/time/rate) · FastAPI · Instructor · Pydantic v2 · Qdrant · fastembed ·
SQLite · uv · Next.js 16 · Recharts · Docker · GitHub Actions
