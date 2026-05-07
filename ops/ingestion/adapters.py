"""
Provider Adapter Layer
Provides unified validation, missing-data checks, and parsed extractions
across diverse API schemas (e.g. Polygon v2 vs v3) to prevent parse-level crashes.
"""

class PolygonAdapter:
    def validate(self, data, endpoint_type="agg"):
        """Validates if the structural schema implies success, decoupled from arbitrary status keys"""
        if endpoint_type == "agg":
            # /v2/aggs doesn't reliably use 'status: OK' like v3 reference endpoints do
            return "ticker" in data or ("results" in data and isinstance(data["results"], list))
        elif endpoint_type == "reference":
            return data.get("status") == "OK" and "results" in data
        return False

    def is_empty(self, data):
        return len(data.get("results", [])) == 0

    def parse(self, data):
        return data.get("results", [])


class TwelveDataAdapter:
    def validate(self, data, endpoint_type="time_series"):
        if endpoint_type == "time_series":
            # TwelveData returns 'status: error' explicitly on failures
            if data.get("status") == "error":
                return False
            return "values" in data and isinstance(data["values"], list)
        return False

    def is_empty(self, data):
        return len(data.get("values", [])) == 0

    def parse(self, data):
        return data.get("values", [])


class ProviderAdapterLayer:
    """Unified Adapter Layer to map parameters like intervals and symbols per provider"""
    
    def get_interval(self, provider: str, interval: str) -> str:
        provider = provider.lower()
        if provider == "twelvedata":
            # Map standard shorthand to TwelveData exact formats
            mapping = {
                "1m": "1min",
                "5m": "5min",
                "15m": "15min",
                "30m": "30min",
                "1h": "1hour",
                "2h": "2hours",
                "4h": "4hours",
                "1d": "1day",
                "1w": "1week",
                "1mo": "1month",
                "1M": "1month" 
            }
            # Fallback to the original if not found (in case they already pass "1day")
            return mapping.get(interval, interval)
        return interval

    def get_symbol(self, provider, symbol):
        """Map standard symbol to provider-specific symbol format"""
        # Binance uses USDT instead of USD for most pairs
        if provider == "binance":
            return symbol.replace("-USD", "USDT")
            
        # Polygon uses dashes for class shares (e.g. BRK.B -> BRK-B)
        if provider == "polygon":
            return symbol.replace(".", "-")
            
        # TwelveData typically expects standard ticker (BRK.B or BRK-B usually handled, but keep standard)
        return symbol

    def is_supported_by_twelvedata(self, symbol: str) -> bool:
        """
        Check if a fallback symbol is structurally supported by TwelveData.
        Prevents wasting limits on pure crypto formats inherently unsupported inside TwelveData API.
        """
        upper_sym = symbol.upper()
        if "-USD" in upper_sym or "USDT" in upper_sym or ".OTC" in upper_sym:
            return False
        return True

    def route(self, symbol: str) -> str:
        """
        Fully automatic provider selection based on symbol morphology.
        Automatically designates the exact optimal endpoint pipeline.
        """
        upper = symbol.upper()
        
        # Crypto pairs (Binance style target format)
        if upper.endswith("USDT") or upper.endswith("BUSD"):
            return "binance"
            
        # Stocks / equities (Default) -> Route to Polygon explicitly
        return "polygon"

adapter = ProviderAdapterLayer()
