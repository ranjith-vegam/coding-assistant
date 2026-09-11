# =============================================================================
# samixa-code-backend
# =============================================================================
# Build context: backend/
#   This service talks to an external model-orchestrator over HTTP (see
#   MODEL_ORCH_BASE_URL) -- it does not bundle or run any model itself. There
#   is no frontend build stage: the VS Code extension is packaged and
#   installed separately (see ../extension/), not served from this image.
#
# Usage:
#   docker compose build
#   docker compose up -d
# =============================================================================

# ── Stage 1: builder (Python deps via uv) ──────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Lockfile first so this layer is cached independently of source changes.
COPY pyproject.toml uv.lock ./

# --frozen            : honour uv.lock exactly, no re-resolution
# --no-dev            : skip pytest/dev extras
# --no-install-project: source is copied in the runtime stage below
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser

WORKDIR /app

# Pre-built venv from the builder stage.
COPY --from=builder /app/.venv /app/.venv

# Application source.
COPY samixa_code/ ./samixa_code/
COPY pyproject.toml ./

RUN mkdir -p /home/appuser/.cache/samixa \
    && chown -R appuser:appgroup /app /home/appuser

USER appuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${SERVICE_PORT:-8765}/health || exit 1

CMD ["python", "-m", "samixa_code"]
