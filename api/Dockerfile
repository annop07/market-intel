FROM python:3.12-slim

# uv resolves and installs from the lockfile — same versions as local dev.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH=/data/market.db \
    QDRANT_LOCATION=/data/qdrant \
    REPORT_DIR=/reports

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
