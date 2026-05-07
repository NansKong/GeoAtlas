# GeoAtlas Source of Truth

Date: 2026-03-13

## 1) Canonical Product Direction

This file is the implementation authority for the current codebase.
When requirements, task list, and PRD extracts conflict, follow this order:

1. `SOURCE_OF_TRUTH.md` (this file)
2. `requirements.md`
3. `task.md`
4. `PRD/extracted_text.txt` (historical reference, contains mixed/older guidance)

Key decisions locked:
- Architecture: FastAPI modular monolith + Celery workers first, not day-1 microservices.
- Data flow: News ingestion -> NLP/event extraction -> event impacts -> predictions.
- Market stack: Polygon (stocks/ETF), Twelve Data (forex/commodities), CoinGecko (crypto).
- Messaging/orchestration: Celery required for MVP, Kafka optional skeleton in MVP phase.
- Quality gates: confidence threshold, dedupe, schema validation, timestamp consistency, asset validation.

## 2) MVP Scope Locked

Must ship in MVP:
- Live news/event feed with 7 event types
- Event to asset mapping (L1/L2 minimum)
- Market panel (price + basic history)
- ShortPulse-only prediction surface
- Boards (create + pin)
- JWT auth

Explicitly not in MVP:
- Mobile app
- Full model ensemble (TrendForce, VolatilityNet)
- Institutional API tier
- Full advanced world-map analytics

## 3) Current Implementation Snapshot

Completed in code:
- Backend modular monolith skeleton (`backend/main.py`, module routers)
- Core settings, DB, Redis, JWT auth
- SQLAlchemy models for users/assets/events/event_impacts/predictions/news/boards/pins/watchlists/alerts/kg
- Celery app and scheduled ingestion tasks for NewsAPI, GDELT, RSS (Reuters/AP/Al Jazeera)
- Event processing worker (`news_articles` -> `events`) with confidence gating and review statuses
- Phase 2 kickoff baseline added to article processing:
  - persisted NLP metadata on `news_articles` (`language_code`, `language_confidence`, `relevance_score`, `relevance_label`, `nlp_processed_at`)
  - deterministic language detection gate before event extraction
  - relevance prefilter before event extraction
  - backfill task for historical article NLP metadata (`workers.event_pipeline.backfill_article_nlp_metadata`)
- Direct entity extraction baseline added to event enrichment:
  - company-name aliases now map to assets even when the ticker is absent
  - event tags are populated from matched assets, countries, and macro/geopolitical topics
  - topic search now includes persisted event tags
  - backfill task for historical events (`workers.event_pipeline.backfill_event_entities`)
- Human review queue surface added:
  - frontend moderation page at `/review`
  - review payload now includes source articles, entity tags, and suggested affected assets
  - approve / reject / edit flows wired to existing moderation APIs
- Review feedback loop added:
  - approve / reject now persist labeled training examples from linked source articles
  - internal dataset inspection endpoint at `/events/review/training-examples`
  - Celery tasks support backfill and JSONL export of review-derived training data
- Phase 2 model-training scaffolding added:
  - local training corpus build script from `event_training_examples`
  - chronological split script for JSONL datasets
  - generic text-classifier training script for local DistilBERT/RoBERTa/FinBERT-style runs
  - generic spaCy training wrapper for local NER runs
  - local-file normalizer for historical GDELT/ACLED datasets plus Reuters extraction and combined JSONL export
- Production inference runtime now supports optional local model artifacts with heuristic fallback:
  - relevance model path + mode
  - event-type model path + mode
  - sentiment model path + mode
  - NER model path + mode
- L2 KG asset expansion added behind config:
  - 1-hop and 2-hop related asset mapping via `kg_relationships`
  - weighted indirect impacts written into `event_impacts`
- L1 direct asset mapping in worker (ticker mention -> `event_impacts`)
- Event pipeline upgraded to composite scoring:
  - Confidence blends keyword fit, source credibility, recency, and market context
  - Relevance score written per article link (`event_articles.relevance_score`)
  - Impact direction/strength calibrated from polarity + event priors
  - Event severity (1-5) derived from impact cues and confidence
- Ingestion workers now include NewsAPI, GDELT, EventRegistry, Mediastack + Reuters/AP/Al Jazeera RSS
- Celery beat schedules ingestion on 5-10 minute cadence and triggers event processing
- Knowledge graph seeding worker implemented:
  - Baseline entity/edge seed from assets table
  - Wikidata SPARQL parse for industry + company-country relationships
  - SEC EDGAR 10-K/20-F parse for supplier/customer relationship heuristics
  - Writes to `kg_entities` and `kg_relationships` (`workers.ingestion.seed_knowledge_graph`)
- Review queue APIs with moderation audit trail (list/edit/approve/reject/history)
- Market data endpoints with Redis cache policy:
  - `/market/quote/{ticker}` (TTL 15s)
  - `/market/ohlcv/{ticker}` (TTL 1h)
- Market WebSocket stream endpoint with single-upstream fan-out:
  - `/market/ws` (subscribe/unsubscribe/set via socket messages)
  - Upstream providers: Polygon WS (primary) with Finnhub WS fallback
  - Stream ticks update Redis quote cache (`market:quote:{ticker}`) and minute-bucket DB prices
- Expanded market cache layers:
  - `/market/historical/{ticker}` with `historical_1y` cache (TTL 24h)
  - `/market/fundamentals/{ticker}` with fundamentals cache (TTL 7 days)
- Market data policy now enforces live-provider-only mode (no synthetic fallback):
  - `MARKET_REQUIRE_LIVE_API=true` rejects unavailable provider responses with 503
- Frontend market panel connected to quote/OHLCV APIs (ticker search + mini chart)
- Frontend market panel now consumes live WebSocket quote updates with REST fallback
- Frontend market panel now shows fundamentals snapshot (market cap, P/E, EPS, dividend yield)
- Frontend raw news feed page implemented at `/news` (reads `news_articles` directly)
- Frontend initialized with Next.js + TypeScript + TailwindCSS + ShadCN-compatible scaffold
- Event cards now show affected asset chips (Event -> Affected Assets panel)
- Alembic initial migration version (`20260312_0001`) covering core schema + critical indexes
- Frontend Next.js + React Query scaffold with feed and public boards pages
- Docker compose for Postgres/Timescale, Redis, Elasticsearch

Not completed yet:
- ML/NLP extraction pipeline (DistilBERT/RoBERTa/FinBERT) replacing current rule-based baseline
- OpenCorporates KG ingestion path (optional enrichment) not yet implemented
- Prediction training/verification pipelines
- Alert delivery channels

## 4) Execution Priority (Next)

Priority 0 (blockers):
1. Run baseline asset seed in each environment before ingestion workers.
2. Add source health/rate-limit monitoring for all ingestion providers.

Priority 1 (MVP backbone):
1. Build event->asset impact confidence calibration and validation metrics.
2. Add prediction record lifecycle (create -> resolve -> outcome verify task).
3. Add ingestion source health/rate-limit dashboards and alerts.

Priority 2 (product surface):
1. Connect frontend event feed to processed events (not raw placeholder only).
2. Implement board pin flows from event cards.
3. Add basic alerts rule CRUD.

## 5) Working Rule

Before adding new modules, close open Priority 0 blockers first.
