# GeoAtlas 🌍📈

**GeoAtlas** is a real-time geopolitical intelligence and market prediction platform. It ingests global news, extracts macroeconomic and geopolitical events using advanced NLP, maps them to financial assets via a dynamic Knowledge Graph, and predicts market impacts using machine learning models (`GeoAtlas-Ensemble-v1`).

---

## Architecture Overview
GeoAtlas is built as a **modular monolith** with event-driven background workers:
- **FastAPI Backend:** Handles REST API endpoints, user authentication, and high-reliability market snapshot & prediction services.
- **Celery Workers:** Manages asynchronous tasks including multi-source RSS ingestion, HTML sanitization, NLP extraction, knowledge graph seeding, and ML inference.
- **Next.js Frontend:** Interactive intelligence dashboard featuring global event feeds, light-themed map page with dynamic hotspot sidebars, asset panels, and custom user watchlists.
- **PostgreSQL + TimescaleDB:** Stores relational data (users, events, assets, predictions) and time-series market price snapshots.

---

## Tech Stack
### Backend & ML Pipeline
* **Framework:** Python 3.11+, FastAPI, SQLAlchemy, Alembic
* **Orchestration & Storage:** Celery, Redis (Task Broker & Cache), PostgreSQL / TimescaleDB
* **NLP Pipeline:** spaCy (NER), HuggingFace Transformers (DistilBERT for relevance, FinBERT for sentiment), custom HTML sanitization (`clean_feed_text`)
* **Prediction Engine:** `GeoAtlas-Ensemble-v1` (FinBERT NLP sentiment + Chronos T5 time-series forecasting model), VolatilityNet & TrendForce models

### Data Providers & Sources
* **Market Data (Primary):** Yahoo Finance (`yfinance`) for Equities, ETFs, Commodities, Market Indices, and Forex pairs. **Binance API** for Crypto.
* **News & Geopolitical Feeds:** Multi-source RSS feeds (Reuters, AP, BBC, Financial Times, Al Jazeera, Bloomberg), GDELT, NewsAPI, Mediastack, EventRegistry.
* **Filtering & Moderation:** Automated non-macro noise purge (`purge_non_macro.py`), blocklist filtering, and calibrated source credibility thresholds (`AUTO_APPROVE_THRESHOLD = 0.60`).

### Frontend
* **Framework:** Next.js (React), TypeScript
* **Styling:** Tailwind CSS, ShadCN UI, Lucide Icons
* **State & Data:** React Query, Recharts (Market visualization)

---

## Key Features
* **Live Intelligence Feed:** Aggregates and normalizes geopolitical events from top global news feeds with zero HTML markup leakage.
* **Geopolitical Noise Purging:** Filters out sports, lifestyle, and non-macro noise at both ingestion and API service layers.
* **Knowledge Graph Asset Mapping:** Maps geopolitical events directly to affected tickers (L1 Direct Mention) and supply-chain dependencies (L2 Sector Expansion).
* **High-Reliability Market Data:** Multi-tier quote fallback powered by Yahoo Finance and Binance to eliminate API rate limits.
* **Interactive Geopolitical Map:** Light-themed Map interface featuring dynamic event-type hotspot sidebars and count badges.
* **AI Prediction Surface:** Evaluates event impact severity and asset direction with TTL-cached prediction metrics.
* **Automated Maintenance:** Background scripts for stale prediction purging, backlog auto-approval, and DB sanitization.

---

## Getting Started

### Prerequisites
* Python 3.11+
* Node.js 18+
* PostgreSQL (with TimescaleDB extension)
* Redis Server
* Docker & Docker Compose (optional)

### 1. Backend Setup
```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start the FastAPI server
uvicorn main:app --reload --port 8000
```

### 2. Celery Worker & Snapshot Tasks (Separate Terminal)
```bash
cd backend
source venv/bin/activate

# Start the Celery worker
celery -A workers.celery_app worker --loglevel=info

# Start Celery Beat (scheduled RSS ingestion and market snapshots)
celery -A workers.celery_app beat --loglevel=info
```

### 3. Utility & Maintenance Scripts
```bash
cd backend

# Purge non-macro/lifestyle events from DB
python -m scripts.purge_non_macro

# Batch approve pending review events (confidence >= 0.60)
python -m scripts.publish_pending_review

# Generate live predictions for active market assets
python -m scripts.generate_live_predictions
```

### 4. Frontend Setup
```bash
cd frontend
npm install

# Run the development server
npm run dev
```
The frontend application will be available at `http://localhost:3000`.

---

## Project Structure
```text
GeoAtlas/
├── backend/                  # FastAPI Application & Background Pipeline
│   ├── core/                 # Config, DB, Security, Cache, HTML Text Cleaners
│   ├── modules/              # Routers, Models & Services (users, events, market, predictions, boards)
│   ├── workers/              # Celery tasks (RSS ingestion, market snapshots, event pipeline)
│   ├── scripts/              # Data sanitization, purge tools & live prediction generators
│   └── alembic/              # Database migration scripts
├── frontend/                 # Next.js Frontend Application
│   ├── src/app/              # Next.js App Router Pages (Feed, Map, Pricing)
│   └── src/components/       # UI Components (MarketPanel, PredictionCard, Map Layers, Watchlists)
├── ops/                      # Infrastructure & Deployment Configs
├── PRD/                      # Product Requirements & Documentation
├── .gitignore                # Security rules (ignoring API keys, envs, logs, non-essential docs)
└── README.md                 # Project Overview & Setup Guide
```

---

## License
This project is proprietary and confidential.
