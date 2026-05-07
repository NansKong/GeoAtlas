# GeoAtlas — Master Task Checklist

## Phase 1 — Foundation (Month 1)

Status source:
- Use `SOURCE_OF_TRUTH.md` as canonical execution reference.
- Checklist status synced on 2026-04-01.

### Backend Setup
- [x] Initialize FastAPI modular monolith (`geoatlas/main.py`)
- [x] Setup project structure: `modules/users`, `modules/events`, `modules/market`, `modules/predictions`, `modules/boards`
- [x] Configure PostgreSQL connection (`core/database.py`)
- [x] Configure Redis connection (`core/config.py`)
- [x] Setup Celery + Celery Beat for background tasks
- [x] Create Alembic migration environment
- [x] Write `.env` config with all secrets (API keys, DB URL, Redis URL)

### Database — Core Tables (PostgreSQL)
- [x] `users` table (id, email, password_hash, username, role, subscription_plan, alert_preferences, created_at)
- [x] `assets` table (id, ticker, name, asset_type, sector, industry, country, exchange, currency)
- [x] `events` table (id, title, description, event_type, country, region, severity, source, source_url, published_at)
- [x] `event_tags` table (id, event_id, tag)
- [x] `event_impacts` table (id, event_id, asset_id, impact_direction, impact_strength, confidence_score)
- [x] `predictions` table (id, event_id, asset_id, predicted_direction, predicted_change_pct, predicted_at, resolve_at, actual_change_pct, outcome, model_version, confidence_score)
- [x] `news_articles` table (id, title, content, source, url, published_at, sentiment_score, content_hash)
- [x] `event_articles` table (id, event_id, article_id, relevance_score)
- [x] `boards` table (id, user_id, title, description, visibility, created_at)
- [x] `pins` table (id, board_id, content_type, content_id, created_at)
- [x] `watchlists` table (id, user_id, asset_id, created_at)
- [x] `alerts` table (id, user_id, asset_id, event_type, threshold, created_at)

### Database — Knowledge Graph Tables
- [x] `kg_entities` table (id, entity_type, name, metadata JSONB)
- [x] `kg_relationships` table (id, source_id, target_id, relationship, strength, data_source, last_verified)

### Database — TimescaleDB
- [x] `market_prices` hypertable (id, asset_id, timestamp, open, high, low, close, volume)

### Database Indexes
- [x] Index: `events(published_at)`, `events(country)`, `events(event_type)`
- [x] Index: `event_impacts(asset_id)`
- [x] Index: `market_prices(asset_id, timestamp)`
- [x] Index: `news_articles(published_at)`, `news_articles(content_hash)` (unique)

### News Ingestion Service
- [x] Build ingestion workers for: NewsAPI, GDELT, EventRegistry, Mediastack
- [x] Build RSS parsers for: Reuters, AP News, Al Jazeera
- [x] Normalize articles to unified schema
- [x] Implement SHA256 deduplication (`content_hash = SHA256(title + description)`)
- [x] Store raw articles to `news_articles` table
- [x] Send new articles to Kafka topic / Celery queue for NLP processing
- [x] Schedule ingestion every 5–10 minutes via Celery Beat

### Knowledge Graph Seeding
- [x] Parse Wikidata SPARQL for industry classifications and company-country relationships
- [x] Parse SEC EDGAR 10-K filings for key supplier/customer relationships
- [x] Seed `kg_entities` and `kg_relationships` tables

### Frontend — Basic Setup
- [x] Initialize Next.js + TypeScript + TailwindCSS + ShadCN UI project
- [x] Setup React Query for data fetching
- [x] Build basic layout: Navbar, Sidebar, Main content area
- [x] Build News Feed page (raw articles, no event extraction yet)
- [x] Setup API client pointing to FastAPI backend

---

## Phase 2 — NLP Core (Month 2)

### NLP Pipeline
- [x] Language detection stage (langdetect / fastText) — target >99% accuracy
  - Current implementation: `langdetect` + persisted article metadata + language gate
- [x] Relevance classifier (DistilBERT) — geopolitical/macro filter — target >92% precision
  - Current implementation: trained runtime artifact is now wired (`sklearn` local baseline), with transformers fallback supported
- [x] NER extraction (spaCy `en_core_web_trf` + fine-tuning on GDELT-paired text) — target F1 >88%
  - Current implementation: deterministic entity/tag extraction + bootstrapped spaCy NER artifact are wired
- [x] Event type classifier (RoBERTa fine-tuned on 7 categories) — target F1 >85%
  - Categories: Conflict, Sanctions, Trade Policy, Energy Disruption, Regulation, Elections, Economic Data
- [x] Sentiment scoring (FinBERT) — target Pearson >0.75
- [x] Confidence gating logic:
  - `>= 0.72` → AUTO_APPROVED → write to `events` table
  - `0.55–0.72` → PENDING_REVIEW → send to human review queue
  - `< 0.55` → REJECTED

### Training Data Pipeline
- [x] Ingest GDELT Event Database (start parallel in Month 1)
- [x] Ingest ACLED conflict event data
- [x] Pair Reuters/AP historical articles with GDELT event dates for labelled training pairs
- [x] Build train/test split (chronological, not random)
  - Current implementation: historical GDELT/ACLED/Reuters datasets normalized, paired, and chronologically split artifacts generated under `backend/tmp/phase2`

### Human Review Queue
- [x] Build internal annotation UI (simple web page)
  - Show: article headline, extracted event, entity list, suggested impact
  - Actions: Approve / Reject / Edit
- [x] Feed approved corrections back to training dataset automatically
- [x] Target: 50–100 human-reviewed events per week

### Sector & Asset Mapping (Layer 1–2)
- [x] L1: Direct mention — NER entity match to asset ticker
  - Current implementation: ticker mentions + company-name alias matching + persisted event tags
- [x] L2: Knowledge graph traversal (2-hop supply chain relationships)
  - Current implementation: weighted 1-hop/2-hop related asset expansion via `kg_relationships`

### Frontend — Event Feed
- [x] Build Event Card component (event title, type badge, affected assets, sentiment, confidence)
- [x] Build Global Event Feed page
- [x] Add search and filter by event type / country / sector

---

## Phase 3 — Intelligence Layer (Month 3)

### Asset Mapping (Layer 3–4)
- [x] L3: Sector expansion with relevance weighting
- [x] L4: ML embedding similarity on past events (edge cases)

### Event Impact Population
- [x] Write extracted events to `events` table
- [x] Write event-asset mappings to `event_impacts` table

### Market Data Service
- [x] Integrate Polygon.io (real-time stock/ETF via WebSocket)
- [x] Integrate Twelve Data (Forex + commodities)
- [x] Implement Redis caching strategy:
  - `realtime_price`: TTL 15s
  - `daily_ohlcv`: TTL 1h
  - `historical_1y`: TTL 24h (store in PostgreSQL)
  - `fundamentals`: TTL 7 days
- [x] Implement WebSocket multiplexing: 1 connection to Polygon → fan-out to all subscribed users
- [x] Build `/market` API endpoints (price, historical, asset metadata)

### Frontend — Market Panel
- [x] Build Asset Price component with Recharts / TradingView widget
- [x] Build Event → Affected Assets panel
- [x] Build Macro Dashboard: world map event heatmap

### Data Quality
- [x] Implement automated quality gates (pre-write validations):
  - Confidence threshold check (>0.55)
  - Schema validation (no null required fields)
  - Duplicate detection via content_hash
  - Temporal consistency (event timestamp within 48h of article)
  - Asset ticker validation against assets table
- [x] Setup Grafana quality metrics dashboard:
  - Event classification accuracy
  - NLP pipeline p95 latency
  - Auto-approved rate
  - Human review queue backlog
  - News ingestion freshness

---

## Phase 4 — Prediction Engine (Month 4)

### Training Dataset Construction
- [x] Join GDELT historical events with local Binance CM and Polygon historical price data
- [x] Fetch T+1h, T+6h, T+24h, T+7d prices for each event's affected assets
- [x] Label generation: >2% = positive, <-2% = negative, else = neutral
- [x] Feature engineering baseline: event_type, sentiment_score, country/provider, mention/article counts, publish-time features
- [x] Historical weak-label corpus prepared from `backend/tmp/phase2/historical.combined.jsonl` for baseline training

### Model Integrations (HuggingFace Zero-Shot & ML)
- [x] **ShortPulse baseline** (TF-IDF + Logistic Regression surrogate): weak-label direction + probability artifact trained
- [x] **ShortPulse** (FinBERT): 1h–6h prediction → Pre-trained HuggingFace NLP pipeline (`ProsusAI/finbert`).
- [x] **TrendForce & VolatilityNet**: XGBoost for price trend (tabular) and PyTorch LSTM for volatility spikes (CUDA-enabled).
- [x] **ChronosNet** (amazon/chronos-t5-base): Direct Time-Series foundational forecasting built on HuggingFace tokenization.
- [x] **RegimeFilter** (Random Forest): always-on market regime classifier (using scikit-learn).

### Prediction Validation
- [x] Track all predictions vs actual outcomes in `predictions` table
- [x] Build Celery task `verify_event_outcome` (runs T+24h and T+7d)
- [x] Accuracy dashboard query in Grafana (by model_version and horizon)
- [x] Production rule: ship predictions only for event types with back-test accuracy >60%
- [x] Auto-disable prediction feature if accuracy drops <50%

### Frontend — Prediction UI
- [x] Build Prediction card (direction, % change range, confidence, horizon)
- [x] Display model accuracy score transparently on UI
- [x] Build Prediction history view

---

## Phase 5 — Platform Features (Month 5)

### Intelligence Boards (Pinterest-style)
- [x] Build Boards CRUD API (`/boards` endpoints)
- [x] Build Pins API (`/pins` endpoints) — pin events, assets, predictions, news
- [x] Board visibility: public / private
- [x] Frontend: Board creation flow, drag-and-drop pin management
- [x] Example boards: China-US Tech War, Middle East Conflict, Global Energy Crisis

### Personalized Alerts
- [x] Build alert rule creation API (`/alerts` endpoints)
- [x] Celery task: check alerts on every new event, trigger notifications
- [x] Email notifications via SendGrid
- [x] Web push notifications via Firebase FCM
- [x] Frontend: Alert settings page

### User Watchlists
- [x] Build watchlist API (`/watchlists` endpoints)
- [x] Frontend: Watchlist panel showing tracked assets with latest event impacts



---

## Phase 6 — Hardening & Web Scaling (Month 6)

### Performance & Testing
- [ ] Load testing with k6 (target: 100k concurrent users)
- [ ] NLP service extraction from monolith (if CPU >60%)
- [ ] Prediction service extraction (if inference >5s)
- [ ] Security audit + penetration testing
- [ ] RBAC enforcement review

### DevOps
- [ ] Setup GitHub Actions CI/CD pipeline
- [ ] Dockerize all services
- [ ] Kubernetes deployment (AWS EKS or GCP GKE)
- [ ] Terraform infrastructure-as-code
- [ ] Prometheus + Grafana observability stack
- [ ] ELK stack for log aggregation

### Launch
- [ ] Public beta launch
- [ ] Seed knowledge graph with 1000+ events from GDELT
- [ ] Initial asset universe: top 500 global stocks + major ETFs + commodities + top 20 crypto

---

## Infrastructure Budget (MVP)
| Item | Provider | Cost/Month |
|------|----------|-----------|
| Real-time stock/ETF | Polygon Starter | $29 |
| Crypto prices | CoinGecko Pro | $129 |
| News API | NewsAPI Business | $449 |
| Forex/Commodities | Twelve Data | $29 |
| Infrastructure | AWS EC2+RDS+Redis | ~$120 |
| **Total** | | **~$756/month** |

---

## Quality Gates (Do Not Ship Without These)
- [ ] NLP classifier accuracy >85% on test set
- [ ] Prediction back-test accuracy >60% per event category
- [ ] News ingestion latency <30s per event
- [ ] Auto-approval rate >70%
- [ ] Asset mapping coverage >90%



