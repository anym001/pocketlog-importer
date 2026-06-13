FROM python:3.12-slim

ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching), then the package itself so
# the `pocketlog-import` console script lands on PATH (used by `docker exec`).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY pocketlog_importer ./pocketlog_importer
RUN sed -i "s|^__version__ = .*|__version__ = \"${APP_VERSION}\"|" pocketlog_importer/__init__.py \
 && pip install --no-cache-dir .

COPY config/config.example.yaml config/rules.example.yaml /app/config/
COPY docker/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Persistent state (PocketLog /config convention) + the work directories.
VOLUME ["/config", "/data"]

# Healthcheck: the run heartbeat must be fresher than ~2 cron intervals;
# `--healthcheck` derives the threshold from schedule.cron in config.yaml.
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=3 \
  CMD pocketlog-import --healthcheck || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["pocketlog-import"]
