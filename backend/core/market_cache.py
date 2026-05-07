import asyncio
from typing import Any, Dict

_CACHE: Dict[str, Any] = {
    "market_snapshot": {
        "snapshot": [],
        "last_updated": None,
        "source_status": {
            "binance": "connecting",
            "polygon": "connecting"
        }
    }
}
_LOCK = asyncio.Lock()

async def get_market_snapshot() -> Any:
    async with _LOCK:
        return _CACHE.get("market_snapshot", {})

async def set_market_snapshot(data: Any) -> None:
    async with _LOCK:
        _CACHE["market_snapshot"] = data
