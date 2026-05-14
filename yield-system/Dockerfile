FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock README.md* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY scripts ./scripts
COPY site ./site

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ENV=prod \
    DATA_DIR=/data \
    LOG_DIR=/data/logs

RUN mkdir -p /data /data/logs && \
    useradd -r -u 1000 -g root yield && \
    chown -R yield:root /data && \
    chmod -R g+rwX /data

USER yield
EXPOSE 8080

CMD ["uvicorn", "yield_system.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
