# GeoAtlas Pipeline — INGESTION CONTRACT
**Version**: `v1.0-ingestion-stable`

This pipeline is officially designated as complete and stable. It serves as the immutable data foundation bridging external market data with internal prediction modeling.

## 1. Input Standard
**Symbol Universe (`universe.py`)** -> Core list defining our prediction universe.
The pipeline accepts raw ticker lists and automatically isolates constraints via an `adapter.route()` morphology check (e.g. `USDT` mappings securely partitioned).

## 2. Output Standard 
**PostgreSQL (`db.py`)** -> Yields fully sanitized, timezone-uniform OHLCV (Open, High, Low, Close, Volume) series natively merged into overlapping historical tables.

## 3. Strict Guarantees
🔴 **No Duplicates**
Safeguarded physically at the SQL execution layer utilizing strict `ON CONFLICT (symbol, timestamp) DO UPDATE`.

🔴 **Intelligent Incremental Updates**
Bypasses historical queries entirely utilizing optimized initial metadata pulls mapping directly to exact UTC daily boundaries (`latest_ts > today`).

🔴 **API Resilience & Provider Fallbacks**
Utilizes state-aware `AsyncTokenBucket` Additive Increase/Multiplicative Decrease (AIMD) algorithm dynamically scaling back against `429` constraints cleanly bouncing rejected instances natively to TwelveData.

*We consider this sector finished. Do not fundamentally re-engineer components here outside of maintenance.*
