import psycopg2
from psycopg2.extras import execute_batch
import os

DB_CONFIG = {
    "dbname": "geoatlas",
    "user": "geoatlas",
    "password": "geoatlas_dev",
    "host": "localhost",
    "port": "5432"
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def apply_schema():
    """Apply the basic tables if they don't exist yet"""
    with open(os.path.join(os.path.dirname(__file__), 'schema.sql'), 'r') as f:
        schema_sql = f.read()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(schema_sql)
    conn.commit()
    cursor.close()
    conn.close()
    print("Schema applied successfully.")

def get_latest_timestamps(symbols, timeframe="daily"):
    """
    Returns a dictionary mapping {symbol: latest_timestamp (datetime)}
    for the requested symbols to avoid fetching duplicate history.
    """
    if not symbols:
        return {}
        
    table = "market_prices_daily" if timeframe == "daily" else "market_prices_hourly"
    
    conn = get_connection()
    cursor = conn.cursor()
    # Execute batch read with ANY for optimal performance
    query = f"SELECT symbol, MAX(timestamp) FROM {table} WHERE symbol = ANY(%s) GROUP BY symbol;"
    cursor.execute(query, (symbols,))
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Store mapping
    return {r[0]: r[1] for r in rows}

def upsert_symbols(symbols_list):
    """
    symbols_list is a list of dicts: [{'symbol': 'AAPL', 'asset_type': 'stocks', 'source': 'yfinance'}, ...]
    """
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        INSERT INTO symbols (symbol, asset_type, source, active)
        VALUES (%(symbol)s, %(asset_type)s, %(source)s, true)
        ON CONFLICT (symbol) DO UPDATE 
        SET asset_type = EXCLUDED.asset_type,
            source = EXCLUDED.source,
            active = EXCLUDED.active;
    """
    execute_batch(cursor, query, symbols_list)
    conn.commit()
    cursor.close()
    conn.close()

def upsert_market_prices(data_list, timeframe="daily"):
    """
    data_list is a list of dicts: 
    [{'symbol': 'AAPL', 'timestamp': dt, 'open': 150.0, 'high': 151.0, 'low': 149.0, 'close': 150.5, 'volume': 1000000, 'provider': 'yfinance'}]
    """
    table = "market_prices_daily" if timeframe == "daily" else "market_prices_hourly"

    conn = get_connection()
    cursor = conn.cursor()
    query = f"""
        INSERT INTO {table} (symbol, timestamp, open, high, low, close, volume, provider)
        VALUES (%(symbol)s, %(timestamp)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(provider)s)
        ON CONFLICT (symbol, timestamp) DO UPDATE 
        SET open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            provider = EXCLUDED.provider,
            last_updated = CURRENT_TIMESTAMP;
    """
    
    # We use execute_batch for better performance on bulk inserts
    execute_batch(cursor, query, data_list, page_size=5000)
    conn.commit()
    cursor.close()
    conn.close()

if __name__ == "__main__":
    apply_schema()
