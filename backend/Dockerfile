# syntax=docker/dockerfile:1.9

# ---- Base -------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv resolves and installs an order of magnitude faster than pip.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# ---- Builder ----------------------------------------------------------------
FROM base AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN uv venv "$VIRTUAL_ENV"

# Dependencies are installed from the manifest alone so this layer is cached
# across source-only changes.
COPY pyproject.toml README.md ./
RUN uv pip install --python "$VIRTUAL_ENV/bin/python" -r pyproject.toml

# ---- Development ------------------------------------------------------------
FROM builder AS development

RUN uv pip install --python "$VIRTUAL_ENV/bin/python" \
    "pytest>=8.3.0" "pytest-asyncio>=0.24.0" "pytest-cov>=6.0.0" "pytest-env>=1.1.5" \
    "ruff>=0.8.0" "mypy>=1.13.0" "faker>=33.0.0" "anyio>=4.6.0"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- Production -------------------------------------------------------------
FROM base AS production

# Run unprivileged: a container compromise should not be a root shell.
RUN groupadd --system --gid 1001 memescope \
    && useradd --system --uid 1001 --gid memescope --create-home memescope

COPY --from=builder --chown=memescope:memescope /opt/venv /opt/venv
COPY --chown=memescope:memescope alembic.ini ./
COPY --chown=memescope:memescope alembic ./alembic
COPY --chown=memescope:memescope app ./app
COPY --chown=memescope:memescope scripts ./scripts

RUN chmod +x ./scripts/*.sh || true

USER memescope

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/live || exit 1

# Gunicorn supervises uvicorn workers: it handles restarts and graceful reloads
# that a bare uvicorn process does not.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--max-requests", "2000", \
     "--max-requests-jitter", "200", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
