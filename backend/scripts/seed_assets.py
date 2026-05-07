"""
Seed a baseline tradable asset universe for MVP development.

Usage:
    python scripts/seed_assets.py
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.market.models import Asset, AssetType


SEED_ASSETS = [
    # Semiconductor / AI
    {"ticker": "NVDA", "name": "NVIDIA Corp", "asset_type": AssetType.STOCK, "sector": "Technology", "industry": "Semiconductors", "country": "United States", "exchange": "NASDAQ", "currency": "USD"},
    {"ticker": "AMD", "name": "Advanced Micro Devices", "asset_type": AssetType.STOCK, "sector": "Technology", "industry": "Semiconductors", "country": "United States", "exchange": "NASDAQ", "currency": "USD"},
    {"ticker": "TSM", "name": "Taiwan Semiconductor Manufacturing", "asset_type": AssetType.STOCK, "sector": "Technology", "industry": "Semiconductors", "country": "Taiwan", "exchange": "NYSE", "currency": "USD"},
    # Market ETFs
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF", "asset_type": AssetType.ETF, "sector": "Broad Market", "industry": "Index ETF", "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "QQQ", "name": "Invesco QQQ Trust", "asset_type": AssetType.ETF, "sector": "Technology", "industry": "Index ETF", "country": "United States", "exchange": "NASDAQ", "currency": "USD"},
    {"ticker": "XLE", "name": "Energy Select Sector SPDR Fund", "asset_type": AssetType.ETF, "sector": "Energy", "industry": "Sector ETF", "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    # Energy / commodities
    {"ticker": "XOM", "name": "Exxon Mobil Corp", "asset_type": AssetType.STOCK, "sector": "Energy", "industry": "Oil & Gas", "country": "United States", "exchange": "NYSE", "currency": "USD"},
    {"ticker": "CVX", "name": "Chevron Corp", "asset_type": AssetType.STOCK, "sector": "Energy", "industry": "Oil & Gas", "country": "United States", "exchange": "NYSE", "currency": "USD"},
    {"ticker": "USO", "name": "United States Oil Fund", "asset_type": AssetType.ETF, "sector": "Energy", "industry": "Commodity ETF", "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    {"ticker": "GLD", "name": "SPDR Gold Shares", "asset_type": AssetType.ETF, "sector": "Metals", "industry": "Commodity ETF", "country": "United States", "exchange": "NYSEARCA", "currency": "USD"},
    # FX / crypto proxies
    {"ticker": "EURUSD", "name": "Euro / US Dollar", "asset_type": AssetType.FOREX, "sector": "FX", "industry": "Currency Pair", "country": "Global", "exchange": "OTC", "currency": "USD"},
    {"ticker": "BTC", "name": "Bitcoin", "asset_type": AssetType.CRYPTO, "sector": "Crypto", "industry": "Layer 1", "country": "Global", "exchange": "CRYPTO", "currency": "USD"},
    {"ticker": "ETH", "name": "Ethereum", "asset_type": AssetType.CRYPTO, "sector": "Crypto", "industry": "Layer 1", "country": "Global", "exchange": "CRYPTO", "currency": "USD"},
]


def main() -> None:
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    created = 0
    updated = 0

    with Session(engine) as session:
        for data in SEED_ASSETS:
            existing = session.execute(
                select(Asset).where(Asset.ticker == data["ticker"])
            ).scalar_one_or_none()

            if existing:
                existing.name = data["name"]
                existing.asset_type = data["asset_type"]
                existing.sector = data["sector"]
                existing.industry = data["industry"]
                existing.country = data["country"]
                existing.exchange = data["exchange"]
                existing.currency = data["currency"]
                updated += 1
            else:
                session.add(Asset(**data))
                created += 1

        session.commit()

    print(f"Asset seed complete: created={created}, updated={updated}, total_input={len(SEED_ASSETS)}")


if __name__ == "__main__":
    main()
