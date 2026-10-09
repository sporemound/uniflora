FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng ffmpeg fonts-dejavu-core fonts-liberation gosu postgresql-client && \
    rm -rf /var/lib/apt/lists/*

RUN addgroup --system interior && adduser --system --ingroup interior interior

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN python -m pip install --upgrade pip && python -m pip install . && \
    mkdir -p /app/data /app/backups && chown -R interior:interior /app/data /app/backups

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD gosu interior python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uniflora"]
