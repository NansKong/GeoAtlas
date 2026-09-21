# GeoAtlas Backend Service 🌍⚡

FastAPI Geopolitical Intelligence + Market Prediction Backend service for GeoAtlas.

---

## 🏛️ Architecture & Services

The backend consists of three co-located services:
1. **FastAPI Web Server (`main.py`)**:
   - High-throughput asynchronous REST API and real-time WebSocket market feeds.
   - Non-blocking database buffering (`DBBuffer`) to handle bursts of market price quotes safely.
   - Interactive Swagger API documentation at `/docs` and ReDoc at `/redoc`.
   - Health check and circuit breaker status at `/health`.

2. **Celery Worker (`workers/celery_app.py`)**:
   - Asynchronous execution of heavy tasks: RSS news ingestion, text sanitization, spaCy NLP entity recognition, and event extraction.
   - Prediction verification and live feature engineering.

3. **Celery Beat**:
   - Periodic cron scheduler triggering RSS feeds every 10 min, article extraction every 5 min, and rolling features every 3 min.

---

## 🚀 Running with Docker (Production)

```bash
# 1. Build Docker image
docker build -t geoatlas-backend .

# 2. Run API container
docker run -d --name geoatlas --restart always \
  -p 7860:7860 \
  --env-file .env \
  geoatlas-backend

# 3. Run Celery Worker
docker run -d --name geoatlas-worker --restart always \
  --env-file .env \
  geoatlas-backend \
  celery -A workers.celery_app worker --loglevel=info --concurrency=2

# 4. Run Celery Beat
docker run -d --name geoatlas-beat --restart always \
  --env-file .env \
  geoatlas-backend \
  celery -A workers.celery_app beat --loglevel=info
```

---

## 🔧 Environment Variables

All settings are configured via `.env` (see `.env.example` for details):
* `DATABASE_URL`: PostgreSQL connection string (with `postgresql+asyncpg://`).
* `DATABASE_URL_SYNC`: Synchronous connection string for Celery (`postgresql+psycopg2://`).
* `CELERY_BROKER_URL`: Upstash Redis broker URL (`rediss://.../?ssl_cert_reqs=CERT_NONE`).
* `CELERY_RESULT_BACKEND`: Upstash Redis result backend URL.
* `SECRET_KEY`: JWT cryptographic signing secret.
* Provider API keys (`POLYGON_API_KEY`, `FINNHUB_API_KEY`, `TWELVEDATA_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, etc.).
