# syntax=docker/dockerfile:1.7
# ---- Builder stage: install deps into a clean wheelhouse ---------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ---- Runtime stage: minimal, non-root ---------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OUTPUT_DIR=/data \
    LOG_LEVEL=INFO

# Non-root user for security (Harness Delegate friendly)
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /app /data \
    && chown -R app:app /app /data

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# App source
COPY --chown=app:app src/ ./src/

USER app

VOLUME ["/data"]

# Healthcheck: imports succeed → image is usable
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import src.main" || exit 1

ENTRYPOINT ["python", "-m", "src.main"]
