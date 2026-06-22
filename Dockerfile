FROM python:3.12-slim

WORKDIR /app

# Minimal system deps (curl is for the HEALTHCHECK below)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/

# Bake the exercise demo media into the image so the container is fully
# self-contained — no host bind-mount required. The directory is populated
# at build time from ./media/ in the build context.
#
# Layout (matches what app/main.py expects):
#   /media/<slug>.gif
#   /media/mp4/<slug>.mp4
COPY media/ /media/

# SQLite DB volume mount point
RUN mkdir -p /app/data

# Default env. Override GYM_MEDIA_PATH only if you bind-mount a different
# directory; baked /media is the recommended path.
ENV GYM_MEDIA_PATH=/media
ENV GYM_DB_PATH=/app/data/gym.db
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["sh", "-c", "python -m app.seed && python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
