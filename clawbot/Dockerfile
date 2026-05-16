FROM python:3.13-slim

# Install Chromium dependencies for browser-use, plus git for CTO self-modification
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHROMIUM_PATH=/usr/bin/chromium \
    UV_PROJECT_ENVIRONMENT=/venv \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --no-dev --no-install-project

COPY src/ src/
COPY agents/ agents/
COPY CORPORATE_CHARTER.md .

RUN mkdir -p /metrics && chmod 700 /metrics

# Pre-download the fastembed ONNX model (~130 MB) so first production write()
# doesn't block on the download. Fails fast at build time if the model can't be fetched.
RUN /venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

CMD ["/venv/bin/python", "-m", "clawbot.main"]
