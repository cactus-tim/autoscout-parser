# syntax=docker/dockerfile:1.7

# Single-stage image for the AutoScout24 MINI pipeline.
#
# Build context expectations:
#   - pyproject.toml + uv.lock (locked deps)
#   - src/, brief.md
#
# Runtime expectations (mounted via docker-compose or -v at runtime):
#   - /app/.env             (secrets — see .env.example)
#   - /app/creds.json       (GCP service-account JSON, chmod 600 on host)
#
# The container runs `autoscout-pipeline --schedule`, which loops on the
# APScheduler cron in SCHEDULE_CRON (default "15 3 * * *" UTC = 03:15 UTC daily).

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:/root/.local/bin:$PATH

# System libraries required by camoufox's bundled Firefox (Debian Bookworm names).
# camoufox issue tracker confirms these are sufficient for headless rendering.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fonts-liberation \
        libasound2 \
        libdrm2 \
        libgbm1 \
        libgtk-3-0 \
        libpango-1.0-0 \
        libxcomposite1 \
        libxdamage1 \
        libxkbcommon0 \
        libxrandr2 \
        libxshmfence1 \
        libxt6 \
 && rm -rf /var/lib/apt/lists/*

# Pull in `uv` (https://docs.astral.sh/uv/) — single static binary, ~25 MB.
COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /uvx /usr/local/bin/

WORKDIR /app

# Layer 1: dependency manifest only — keeps the install layer cached unless deps change.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Layer 2: bake the camoufox Firefox binary into the image so cold-starts on a new
# server don't need outbound downloads. Binary lives in /root/.cache/camoufox/.
RUN uv run python -m camoufox fetch

# Layer 3: brief — small, may be tweaked frequently. Keep last so deps stay cached.
COPY brief.md ./

# Default: scheduler mode. Override at `docker run`/`docker compose run` time
# with e.g. `autoscout-pipeline --dry-run` for one-shot runs.
ENTRYPOINT ["autoscout-pipeline"]
CMD ["--schedule"]
