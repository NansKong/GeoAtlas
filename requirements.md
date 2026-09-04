# GeoAtlas — Technical Requirements & System Architecture

## 1. Product Vision
A real-time geopolitical intelligence platform that ingests global events, extracts geopolitical and macroeconomic signals using NLP, maps affected assets via a Knowledge Graph, and generates market impact predictions.

**Core flow:**
```
Global Event → NLP & Noise Filter → Knowledge Graph Asset Mapping → Market Pulse (Yahoo Finance / Binance) → AI Prediction (GeoAtlas-Ensemble-v1)
```

---

## 2. Target Users
| Tier | Users | Description |
|------|-------|-------------|
| Primary | Macro investors, retail traders, geopolitics analysts | Track event-driven market shifts in real time |
| Secondary | Policy researchers, risk analysts, financial journalists | Analyze supply chain & regional geopolitical risk heatmaps |

---

## 3. Core Modules

### Module 1 — Global Event Intelligence Feed
- **Real-Time Feed:** Aggregates macroeconomic and geopolitical news.
- **Data Sources:** Multi-source RSS feeds (Reuters, AP, BBC, Financial Times, Al Jazeera, Bloomberg), GDELT, NewsAPI, Mediastack, EventRegistry.
- **Sanitization:** `clean_feed_text` strips HTML markup, unescapes HTML entities, and normalizes unicode characters prior to ingestion.
- **Update Frequency:** Scheduled ingestion loop every 5–10 minutes via Celery Beat.

### Module 2 — Event Intelligence Engine (NLP Pipeline & Noise Filter)
Converts raw news into structured, actionable geopolitical events.

1. **Text Sanitization:** HTML tag stripping and entity normalization.
2. **Relevance & Noise Filter:** Dual-layer blocklist filtering (`purge_non_macro.py`, `cleanup_irrelevant_events.py`) to purge sports, entertainment, and lifestyle stories.
3. **NER Extraction:** spaCy entity recognition for countries, organizations, and commodity assets.
4. **Sentiment Scoring:** FinBERT NLP sentiment classification.
5. **Confidence Gating & Moderation:**
   - `>= 0.60` → **AUTO_APPROVED** (published directly to dashboard)
   - `0.40–0.59` → **PENDING_REVIEW** (moderation queue / `publish_pending_review.py`)
   - `< 0.40` → **REJECTED**

Event types: `conflict`, `sanction`, `trade_policy`, `economic_data`, `energy_disruption`, `election`, `regulation`.

### Module 3 — Live Market Data Engine
- **Primary Data Provider:** **Yahoo Finance (`yfinance`)** for Equities, ETFs, Commodities, Market Indices, and Forex pairs.
- **Crypto Data Provider:** **Binance API** for cryptocurrency pairs (`BTC-USD`, `ETH-USD`, `SOL-USD`).
- **Resilience & Fallback Hierarchy:**
  - Multi-tier quote resolution hierarchy to eliminate 429 rate limits from legacy providers (Alpaca, TwelveData, FCS).
  - Seed database quote fallbacks for instant DB warmup.
  - Non-zero price change selection logic (`choose_best()`).
- **Auto-Discovery & Ticker Search:** Real-time ticker search and scheduled asset price snapshot worker (`market_snapshot.py`).

### Module 4 — AI Market Impact Prediction Surface
Powered by **GeoAtlas-Ensemble-v1**:
- **Ensemble Architecture:** Fuses **FinBERT NLP sentiment scores** with **Chronos T5 time-series forecasting**.
- **Prediction Horizons:** Short-term (1h–6h), Mid-term (24h), and Volatility risk scoring.
- **Caching & Performance:** TTL-based accuracy caching to optimize endpoint query speeds.
- **Automated Lifecycle:** `purge_stale_predictions.py` cleans up expired forecasts; `generate_live_predictions.py` generates fresh predictions for active assets.

### Module 5 — Interactive Geopolitical Map Page
- **Light-Themed Aesthetic:** Professional research dashboard layout.
- **Dynamic Hotspot Sidebar:** Automatically adapts sidebar labeling and metric highlights based on selected event type filter (Sanctions, Trade Policy, Armed Conflict, etc.).
- **Event Count Badges:** Displays active event count badges for high visual clarity instead of arbitrary percentages.

### Module 6 — Intelligence Boards & Watchlists
- Custom user watchlists and theme-based pinboards.
- Real-time price delta badges and alert triggers.

---

## 4. Tech Stack

### Frontend
- **Framework:** Next.js (React), TypeScript
- **Styling:** Tailwind CSS, ShadCN UI, Lucide React Icons
- **State & Charts:** React Query, Recharts, Custom SVG Map Components

### Backend & Async Pipeline
- **Framework:** FastAPI (Python 3.11+), SQLAlchemy, Alembic
- **Orchestration:** Celery, Redis (Broker & Cache)
- **Database:** PostgreSQL + TimescaleDB (relational & time-series market snapshots)

### NLP & AI Models
- **NLP:** spaCy, HuggingFace Transformers (DistilBERT, FinBERT)
- **Time-Series / ML:** Chronos T5, PyTorch, VolatilityNet, XGBoost
- **Sanitization:** `beautifulsoup4`, `html`, `re`

---

## 5. System Utilities & Maintenance Tools

| Script | Path | Purpose |
|--------|------|---------|
| Non-Macro Purge | `backend/scripts/purge_non_macro.py` | Deletes sports, lifestyle, and non-geopolitical event noise |
| Pending Publisher | `backend/scripts/publish_pending_review.py` | Auto-approves queued events meeting source credibility threshold (>=0.60) |
| Live Prediction Generator | `backend/scripts/generate_live_predictions.py` | Computes live predictions for active market tickers |
| Stale Prediction Purge | `backend/scripts/purge_stale_predictions.py` | Purges expired prediction records |
| DB HTML Cleaner | `backend/scripts/clean_html_in_db.py` | Batch strips legacy raw HTML tags from stored news event descriptions |

---

## 6. Security & Repository Hygiene

- **Environment & Secret Protection:** Strictly enforced via `.gitignore` (blocking `.env*`, `secrets.*`, API key files, credentials).
- **Certificates & Keys:** Blocks `*.pem`, `*.key`, `*.crt`, SSH keys (`id_rsa*`), and cloud CLI configs (`.aws/`, `.gcp/`).
- **Data & Log Exclusions:** Excludes database dumps (`*.sqlite`, `*.db`), logs (`*.log`), and large datasets (`*.parquet`, `*.pkl`, `*.jsonl`).
- **Document & PDF Restrictions:** Excludes `*.pdf`, `*.docx`, `PRD/`, and unrequired markdown files from git tracking.
- **Authentication:** JWT access tokens with refresh token rotation and role-based access checks.

---

## 7. Asset Mapping Architecture (Knowledge Graph)
1. **L1 — Direct Mention:** Extract entity Ticker directly from news text (e.g. `NVDA`, `TSM`).
2. **L2 — Sector Expansion:** Map country/event to sector dependencies via Knowledge Graph nodes.
3. **L3 — Supply Chain:** Graph traversal for vendor/customer linkages.

---

## 8. Database Schema Highlights
- `users`: User profiles, subscription plans, alert preferences.
- `events`: Geopolitical events, severity, classification, confidence score, source URL.
- `assets`: Financial instruments (ticker, name, asset_type, sector, exchange).
- `event_impacts`: Relationship between events and affected assets.
- `predictions`: Model outputs (`predicted_direction`, `predicted_change_pct`, `confidence_score`, `model_version`).
- `market_prices`: Time-series price snapshots (`open`, `high`, `low`, `close`, `volume`).
- `watchlists` & `boards`: User-saved assets and pinned intelligence boards.

---

## 9. System Status & Verification Plan
- **Backend API:** Verified FastAPI routers (`events`, `market`, `predictions`, `users`).
- **Market Snapshot:** Verified Yahoo Finance (`yfinance`) integration for equities/commodities/forex & Binance for crypto.
- **RSS News Pipeline:** Verified zero-HTML text extraction and non-macro filtering.
- **Frontend Dashboard:** Verified Next.js components (`MarketPanel`, `PredictionCard`, `Map` page, `WatchlistPanel`).
