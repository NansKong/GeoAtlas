# GeoAtlas — Technical Requirements

## 1. Product Vision
A real-time intelligence platform that maps global geopolitical events to financial market movements and AI-driven predictions.

**Core flow:**
```
Global Event → Sector Impact → Market Movement → Predicted Outcome
```

**Example:**
- Event: China sanctions Taiwan semiconductor exports
- Impact: Semiconductor supply chain risk
- Affected Assets: TSMC, NVIDIA, AMD
- Prediction: Short-term volatility ↑, Chip ETFs ↓

---

## 2. Target Users
| Tier | Users |
|------|-------|
| Primary | Retail traders, macro investors, geopolitics enthusiasts |
| Secondary | Hedge fund analysts, policy researchers, journalists, students |

---

## 3. Core Modules

### Module 1 — Global Event Intelligence Feed
- Real-time feed of geopolitical and macroeconomic events
- Each event card: title, category, impact description, affected markets, prediction, sources
- Data sources: GDELT, NewsAPI, Mediastack, EventRegistry, Reuters RSS, AP RSS, Al Jazeera RSS
- Update cycle: every 5–10 minutes

### Module 2 — Event Intelligence Engine (NLP Pipeline)
Converts raw news into structured geopolitical events.

Pipeline stages:
1. Language Detection (langdetect / fastText) — >99% accuracy
2. Relevance Filter (DistilBERT) — geopolitical Y/N — >92% precision
3. NER Extraction (spaCy + fine-tuned transformer) — >88% F1
4. Event Classification (RoBERTa) — 7 categories — >85% F1
5. Sentiment Scoring (FinBERT) — Pearson >0.75

Event types: `conflict`, `sanction`, `trade_policy`, `economic_data`, `energy_disruption`, `election`, `regulation`

Structured output:
```json
{
  "title": "China restricts gallium exports",
  "event_type": "Trade Policy",
  "country": "China",
  "sector": "Semiconductors",
  "affected_assets": ["NVDA", "AMD", "TSM"],
  "impact": "negative",
  "confidence": 0.74
}
```

Confidence gating:
- `>= 0.72` → AUTO_APPROVED
- `0.55–0.72` → PENDING_REVIEW (human queue)
- `< 0.55` → REJECTED

### Module 3 — Live Market Data Engine
- Assets: Stocks, ETFs, Commodities, Crypto, Forex
- APIs: Polygon.io (real-time WebSocket), Twelve Data (Forex/commodities), CoinGecko Pro (crypto)
- Features: real-time price, OHLCV, charts, volatility indicators
- WebSocket multiplexing: 1 upstream connection → fan-out to all subscribed users

### Module 4 — AI Market Impact Prediction
4 specialized models:
| Model | Type | Horizon | Output |
|-------|------|---------|--------|
| ShortPulse | FinBERT + linear head | 1h–6h | Direction + probability |
| TrendForce | XGBoost | 24h–7d | % change range |
| VolatilityNet | LSTM | 1h–24h | Volatility spike probability |
| RegimeFilter | Random Forest | Always-on | Market regime |

Production rule: only ship predictions for event types with back-test accuracy >60%.

### Module 5 — Intelligence Boards (Pinterest-style)
- Users create boards (e.g., "China–US Tech War", "Middle East Conflict")
- Pin items: events, assets, predictions, news articles
- Visibility: public / private
- Shared alerts per board

### Module 6 — Macro Intelligence Dashboard
- World map with geopolitical event heatmap (red = conflict, green = growth)
- Global market trend overlays
- Regional risk heatmaps

### Module 7 — Personalized Alerts
- Users set alert rules: asset + event type + threshold
- Triggers: email (SendGrid), web push (Firebase FCM), mobile push
- Example: "Notify me when energy-related events affect oil"

---

## 4. Tech Stack

### Frontend (Web)
- Next.js (React framework)
- TypeScript
- TailwindCSS
- ShadCN UI (component library)
- React Query (data fetching + caching)
- Recharts + TradingView widgets (charts)

### Backend
- FastAPI (Python) — modular monolith
- Celery + Celery Beat (background tasks + scheduling)
- Redis (cache + task broker)
- PostgreSQL (primary relational DB)
- TimescaleDB (time-series market prices)
- Elasticsearch (news + event search)

### NLP / AI
- spaCy (NER base)
- HuggingFace Transformers (DistilBERT, RoBERTa, FinBERT)
- PyTorch (model training)
- scikit-learn (XGBoost, Random Forest, feature engineering)
- MLflow (experiment tracking)
- langdetect (language detection)

### Data Pipeline
- Apache Kafka (event streaming)
- Celery (task queue)
- Apache Airflow (orchestration, optional)
- Scrapy (web scraping fallback)

### Infrastructure
- Cloud: AWS (EC2, EKS, RDS, ElastiCache, CloudFront, S3, MSK)
- Containers: Docker
- Orchestration: Kubernetes (AWS EKS)
- IaC: Terraform + Helm
- CI/CD: GitHub Actions

### Authentication
- JWT (access + refresh tokens)
- OAuth2 / Auth0

### Observability
- Prometheus + Grafana (metrics)
- ELK Stack (logs)
- Alerts: Grafana alerting rules

---

## 5. Database Schema

### PostgreSQL (Core)
```
users           — id, email, password_hash, username, role, subscription_plan, alert_preferences
assets          — id, ticker, name, asset_type, sector, industry, country, exchange, currency
events          — id, title, description, event_type, country, region, severity, source, source_url, published_at
event_tags      — id, event_id, tag
event_impacts   — id, event_id, asset_id, impact_direction, impact_strength, confidence_score
predictions     — id, event_id, asset_id, predicted_direction, predicted_change_pct, predicted_at,
                  resolve_at, actual_change_pct, outcome, model_version, confidence_score
news_articles   — id, title, content, source, url, published_at, sentiment_score, content_hash (SHA256)
event_articles  — id, event_id, article_id, relevance_score
boards          — id, user_id, title, description, visibility, created_at
pins            — id, board_id, content_type, content_id, created_at
watchlists      — id, user_id, asset_id, created_at
alerts          — id, user_id, asset_id, event_type, threshold, created_at
```

### Knowledge Graph (PostgreSQL)
```
kg_entities       — id, entity_type (ASSET|SECTOR|COUNTRY|COMMODITY), name, metadata JSONB
kg_relationships  — id, source_id, target_id, relationship, strength (0–1), data_source, last_verified
```

### TimescaleDB
```
market_prices  — id, asset_id, timestamp, open, high, low, close, volume
```

### Critical Indexes
```sql
CREATE INDEX ON events(published_at);
CREATE INDEX ON events(country);
CREATE INDEX ON events(event_type);
CREATE INDEX ON event_impacts(asset_id);
CREATE INDEX ON market_prices(asset_id, timestamp);
CREATE UNIQUE INDEX ON news_articles(content_hash);
CREATE INDEX ON news_articles(published_at);
```

---

## 6. Asset Mapping System (4 Layers)
| Layer | Method | Coverage | Latency |
|-------|--------|----------|---------|
| L1 — Direct Mention | NER entity → ticker match | ~40% of events | <10ms |
| L2 — Supply Chain | Knowledge graph traversal (2-hop) | ~35% of events | <50ms |
| L3 — Sector Expansion | Sector→asset with relevance weighting | ~20% of events | <20ms |
| L4 — ML Similarity | Embedding similarity on past events | ~5% (edge cases) | <200ms |

Knowledge graph seeding sources:
- Wikidata SPARQL (free) — industry classifications, subsidiaries
- SEC EDGAR 10-K filings (free) — key suppliers and customers
- OpenCorporates (free tier) — company-country-sector
- ML-derived edges — co-movement model (future)

---

## 7. Data Quality Requirements
Automated gates (pre-write to DB):
- Confidence threshold: reject if <0.55
- Schema validation: no null required fields
- Deduplication: SHA256(title + event_type + country + published_date)
- Temporal consistency: event timestamp within 48h of article publish date
- Asset validation: all tickers must exist in assets table

Quality metrics (Grafana dashboard):
| Metric | Target | Alert Threshold |
|--------|--------|----------------|
| Event classification accuracy | >85% | <75% |
| NLP pipeline latency (p95) | <30s | >60s |
| Events auto-approved rate | >70% | <50% |
| Human review queue backlog | <100 | >500 |
| Prediction accuracy (24h) | >58% | <50% |
| Asset mapping coverage | >90% | <80% |
| News ingestion freshness | <10 min lag | >30min |

---

## 8. Performance Requirements
- News ingestion: 1000+ articles/hour
- Event extraction latency: <30 seconds per article
- Real-time market price update: <1 second (WebSocket)
- Target scale: 100k users, 10k daily events, 100M market records

---

## 9. Security Requirements
- JWT access tokens + refresh token rotation
- OAuth2 / Auth0 for social login
- RBAC (role-based access control): free / pro / institutional / admin
- API rate limiting at gateway level
- DDoS protection
- Input validation on all endpoints
- All secrets via environment variables (never hardcoded)

---

## 10. Recommended Project Structure (Modular Monolith)
```
geoatlas/
├── main.py                  # FastAPI app, mounts all routers
├── core/
│   ├── config.py
│   ├── database.py
│   └── security.py
├── modules/
│   ├── users/               # Auth, profiles, subscriptions
│   │   ├── router.py
│   │   ├── service.py
│   │   └── models.py
│   ├── events/              # Event intelligence, NLP pipeline
│   │   ├── router.py
│   │   ├── nlp_pipeline.py
│   │   └── models.py
│   ├── market/              # Market data, WebSocket hub
│   ├── predictions/         # ML models, prediction tracking
│   └── boards/              # Boards, pins, watchlists, alerts
└── workers/                 # Celery tasks (news ingestion, NLP, verification)
```

**Microservice extraction triggers:**
- NLP consuming >60% CPU → extract to standalone GPU worker
- Prediction inference >5s → extract to dedicated GPU service
- Auth becoming compliance target → isolate to Auth service
- Team grows to 6+ engineers → full decomposition

---

## 11. Monetization (Postponed)
- **100% Free MVP:** For the current phase, the platform will be totally free. All users will have full, unlimited access to predictions, boards, and alerts.
- **Removed:** Subscription tiers, limits on predictions/boards, and Stripe integration are postponed.

---

## 12. MVP Scope (Ship First)
Must include:
- Live geopolitics feed (news ingestion + NLP extraction)
- Event classification (7 event types)
- Market data panel (price, charts)
- Event → asset mapping (L1 + L2 layers)
- Basic predictions (ShortPulse model only)
- User boards (create, pin events)
- User auth (JWT)

Exclude from MVP:
- Mobile app (Postponed indefinitely)
- Monetization & Subscriptions (Platform will remain free for now)
- Advanced ML ensemble (TrendForce, VolatilityNet)
- Complex world map visualization
- Institutional API tier

---

## 13. External API Dependencies
| API | Purpose | Free Limit | Recommended Plan |
|-----|---------|-----------|-----------------|
| Polygon.io | Real-time stock/ETF | 5 calls/min, 15min delay | Starter $29/mo |
| Twelve Data | Forex + commodities | 8 calls/min | $29/mo |
| CoinGecko Pro | Crypto prices | — | $129/mo |
| NewsAPI | News articles | 100 req/day | Business $449/mo |
| GDELT | Geopolitical events dataset | Free | Free |
| ACLED | Conflict event data | Free (researchers) | Free |
| SEC EDGAR | Supply chain data | Free | Free |
| Wikidata SPARQL | Knowledge graph | Free | Free |
| SendGrid | Email notifications | 100/day free | Essentials ~$15/mo |
| Firebase FCM | Push notifications | Free | Free |
