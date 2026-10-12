# Daily recycling reminder. Runs once a day from host cron on a Raspberry Pi;
# the container exits after each run (0 = ok, 1 = failed) so cron logs it.
# Target architecture is arm64; `python:3.14-slim-bookworm` ships multi-arch.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# zoneinfo for Europe/London; slim images ship a minimal tzdata set. passwd
# provides useradd so we can drop privileges.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata passwd \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 recycler

WORKDIR /app

# stdlib-only runtime (urllib + zoneinfo); no pip install needed.
COPY --chown=recycler:recycler app.py report.py scraper.py ./
COPY --chown=recycler:recycler notifiers ./notifiers

# Build-time smoke check: imports are pure (no env/network at import time), so
# this catches a broken COPY (missing module/__init__.py) when the image is
# built, not when cron fires at 2pm.
RUN python -c "import app, report, scraper, notifiers"

USER recycler

# All config (UPRN, USUAL_COLLECTION_DAY, Pushover secrets, LOG_LEVEL) comes
# from .env at run time via --env-file / compose env_file — nothing is baked
# into the image so there's a single source of truth.
CMD ["python", "app.py"]
