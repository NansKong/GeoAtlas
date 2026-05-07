-- schema.sql

-- 1. Symbols Table
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    asset_type TEXT, -- 'crypto', 'stocks', 'fx'
    source TEXT, -- 'yfinance', 'polygon', 'finnhub'
    active BOOLEAN DEFAULT true
);

-- 2. Daily Market Prices
CREATE TABLE IF NOT EXISTS market_prices_daily (
    symbol TEXT REFERENCES symbols(symbol),
    timestamp TIMESTAMP,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    provider TEXT, -- 'yfinance', 'polygon', etc.
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_daily_symbol_ts ON market_prices_daily(symbol, timestamp DESC);

-- 3. Hourly Market Prices (for later/future)
CREATE TABLE IF NOT EXISTS market_prices_hourly (
    symbol TEXT REFERENCES symbols(symbol),
    timestamp TIMESTAMP,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    provider TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_hourly_symbol_ts ON market_prices_hourly(symbol, timestamp DESC);

-- 4. Ingestion State (to track idempotency and last sync)
CREATE TABLE IF NOT EXISTS ingestion_state (
    symbol TEXT PRIMARY KEY REFERENCES symbols(symbol),
    last_daily_sync TIMESTAMP,
    last_hourly_sync TIMESTAMP
);
