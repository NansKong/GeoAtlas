# GeoAtlas Backend Service 🌍⚡

FastAPI Geopolitical Intelligence + Market Prediction Backend service for GeoAtlas.

---

## 🏛️ Architecture & Services

The backend consists of co-located containerized services on `geoatlas-network`:
1. **FastAPI Web Server (`main.py`)**:
   - High-throughput asynchronous REST API and real-time WebSocket market feeds.
   - Non-blocking database buffering (`DBBuffer`) to handle bursts of market price quotes safely.
   - Interactive Swagger API documentation at `/docs` and ReDoc at `/redoc`.
   - Health check and circuit breaker status at `/health`.

2. **Celery Worker (`workers/celery_app.py`)**:
   - Asynchronous execution of heavy tasks: RSS news ingestion, text sanitization, spaCy NLP entity recognition, and event extraction.
   - Prediction verification, live feature engineering, and daily 30-day database retention pruning (`workers.cleanup.purge_old_data`).

3. **Celery Beat**:
   - Periodic cron scheduler triggering RSS feeds every 10 min, article extraction every 5 min, rolling features every 3 min, and daily database purge at 02:30 UTC.

4. **PostgreSQL 17 Database (`geoatlas-postgres`)**:
   - Dedicated local container with persistent storage volume (`~/postgres-data`). Sub-millisecond latency.

5. **Redis 7 Cache & Broker (`geoatlas-redis`)**:
   - Local in-memory task broker and application cache with AOF persistence (`~/redis-data`).

---

## 🚀 Running with Docker (Production)

```bash
# 0. Create Bridge Network & Storage Directories
docker network create geoatlas-network
mkdir -p ~/postgres-data ~/redis-data

# 1. Run Local PostgreSQL Container
docker run -d --name geoatlas-postgres --restart always \
  --network geoatlas-network \
  -p 127.0.0.1:5432:5432 \
  -v /home/ubuntu/postgres-data:/var/lib/postgresql/data \
  -e POSTGRES_DB=geoatlas \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD='YOUR_PASSWORD' \
  postgres:17-alpine

# 2. Run Local Redis Container
docker run -d --name geoatlas-redis --restart always \
  --network geoatlas-network \
  -p 127.0.0.1:6379:6379 \
  -v /home/ubuntu/redis-data:/data \
  redis:alpine redis-server --appendonly yes --requirepass "YOUR_PASSWORD"

# 3. Run API container
docker run -d --name geoatlas --restart always \
  --network geoatlas-network \
  -p 7860:7860 \
  --env-file .env \
  geoatlas-backend

# 4. Run Celery Worker
docker run -d --name geoatlas-worker --restart always \
  --network geoatlas-network \
  --env-file .env \
  geoatlas-backend \
  celery -A workers.celery_app worker --loglevel=info --concurrency=2

# 5. Run Celery Beat
docker run -d --name geoatlas-beat --restart always \
  --network geoatlas-network \
  --env-file .env \
  geoatlas-backend \
  celery -A workers.celery_app beat --loglevel=info
```

---

## 🔧 Environment Variables

All settings are configured via `.env` (see `.env.example` for details):
* `DATABASE_URL`: PostgreSQL connection string (with `postgresql+asyncpg://`).
* `DATABASE_URL_SYNC`: Synchronous connection string for Celery (`postgresql+psycopg2://`).
* `CELERY_BROKER_URL`: Redis broker URL (`redis://...:6379/1`).
* `CELERY_RESULT_BACKEND`: Redis result backend URL (`redis://...:6379/2`).
* `SECRET_KEY`: JWT cryptographic signing secret.
* Provider API keys (`POLYGON_API_KEY`, `FINNHUB_API_KEY`, `TWELVEDATA_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, etc.).
