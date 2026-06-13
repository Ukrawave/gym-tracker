FROM python:3.11-slim

WORKDIR /app

# Install minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/

# Database lives in /app/data (mounted as a volume by docker-compose)
RUN mkdir -p /app/data

# Default media path inside the container; override with GYM_MEDIA_PATH env var
ENV GYM_MEDIA_PATH=/media
ENV GYM_DB_PATH=/app/data/gym.db

EXPOSE 8080

CMD ["sh", "-c", "python -m app.seed && python -m uvicorn app.main:app --host 0.0.0.0 --port 8080"]
