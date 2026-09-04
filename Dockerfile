# nexdeck as one slim container.
#
# Two stages: the frontend is built first, then only the finished files land
# in the image. Node and its node_modules stay outside; FastAPI serves the
# built files itself.

# --- Stage 1: frontend ---------------------------------------------------------
#
# --platform=$BUILDPLATFORM builds this stage on the build machine's
# architecture even for the arm64 image: the output is HTML, CSS and
# JavaScript, identical on every architecture, and npm under emulation takes
# hours.
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# --- Stage 2: runtime ------------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXDECK_DATA_DIR=/data \
    NEXDECK_STATIC_DIR=/app/static

WORKDIR /app

# curl for the healthcheck, gosu to drop root at start, iputils-ping for the
# ping reachability check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gosu iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./static

RUN useradd --system --create-home --uid 1000 nexdeck \
    && mkdir -p /data \
    && chown -R nexdeck:nexdeck /data /app

COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${NEXDECK_PORT:-8000}/api/health" || exit 1

# One worker: SQLite, and the collector must not run twice.
ENTRYPOINT ["/entrypoint.sh"]
# The graceful timeout matters: open live streams would otherwise keep a
# stopping container waiting for clients that never disconnect.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "5"]
