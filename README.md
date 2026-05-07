# GeoAtlas 🌍📈

**GeoAtlas** is a real-time geopolitical intelligence and market prediction platform. It ingests global news, extracts macroeconomic and geopolitical events using advanced NLP, maps them to financial assets via a dynamic Knowledge Graph, and predicts market impacts using machine learning models.

---

## 🏗 Architecture Overview
GeoAtlas is built as a **modular monolith** with event-driven background workers:
- **FastAPI Backend:** Handles REST API endpoints, WebSocket streams for live market data, and authentication.
- **Celery Workers:** Manages asynchronous tasks including multi-source news ingestion, NLP pipelines, knowledge graph seeding, and ML inference.
- **Next.js Frontend:** Provides an interactive intelligence dashboard featuring global event feeds, affected asset panels, market overviews, and personalized boards.
- **PostgreSQL + TimescaleDB:** Stores relational data (users, events, assets, predictions) and handles high-frequency market tick data.

## 🚀 Tech Stack
### Backend & ML
*   **Framework:** Python, FastAPI, SQLAlchemy, Alembic
*   **Orchestration:** Celery, Redis (Broker & Cache)
*   **NLP Pipeline:** spaCy (NER), HuggingFace Transformers (DistilBERT for relevance, FinBERT for sentiment)
*   **Prediction Engine:** PyTorch (VolatilityNet), XGBoost (TrendForce), ChronosNet (Time-Series)

### Frontend
*   **Framework:** Next.js (React), TypeScript
*   **Styling:** Tailwind CSS, ShadCN UI
*   **State & Data:** React Query, Recharts (Market visualization)

### Data Providers
*   **News/Events:** GDELT, ACLED, NewsAPI, EventRegistry, Mediastack, RSS Feeds
*   **Market Data:** Polygon.io (Stocks/ETFs), Twelve Data (Forex/Commodities), CoinGecko (Crypto)

---

## ✨ Core Features
*   **Live Intelligence Feed:** Aggregates and normalizes news from global sources.
*   **NLP Event Extraction:** Automatically detects languages, filters relevance, extracts entities, and scores sentiment.
*   **Knowledge Graph (L1/L2):** Maps events directly to mentioned tickers or traverses supply-chain relationships to find indirectly affected assets.
*   **Market Prediction Models:** Evaluates event impact severity and predicts asset price movements (T+1h, T+6h, T+24h).
*   **Human-in-the-Loop Review:** Moderation queue for low-confidence events to continuously train the models.
*   **Intelligence Boards & Alerts:** Pinterest-style boards to track specific geopolitical themes and real-time push/email alerts.

---

## 🛠 Getting Started

### Prerequisites
*   Python 3.11+
*   Node.js 18+
*   PostgreSQL (with TimescaleDB extension)
*   Redis
*   Docker & Docker Compose (optional, for infrastructure)

### 1. Backend Setup
```bash
cd backend
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with your database credentials and API keys

# Run database migrations
alembic upgrade head

# Start the FastAPI server
uvicorn main:app --reload --port 8000
```

### 2. Worker Setup (In a separate terminal)
```bash
cd backend
source venv/bin/activate
# Start the Celery worker
celery -A workers.celery_app worker --loglevel=info

# Start Celery Beat (for scheduled ingestion)
celery -A workers.celery_app beat --loglevel=info
```

### 3. Frontend Setup
```bash
cd frontend
npm install

# Setup environment variables
cp .env.local.example .env.local

# Run the development server
npm run dev
```
The frontend will be available at `http://localhost:3000`.

---

## 📂 Project Structure
```text
GeoAtlas/
├── backend/                  # FastAPI Application
│   ├── core/                 # Config, DB, Security, Cache
│   ├── modules/              # API Routers & DB Models (users, events, market, predictions, boards)
│   ├── workers/              # Celery tasks (ingestion, nlp, evaluate_models)
│   ├── scripts/              # Data normalization and ML training scripts
│   └── alembic/              # Database migrations
├── frontend/                 # Next.js Application
│   ├── src/app/              # Pages and Routing
│   └── src/components/       # UI Components (Cards, Maps, Charts)
├── ops/                      # Docker, Grafana, Prometheus configs
└── README.md                 # Project Documentation
```

## 📜 License
This project is proprietary and confidential.
