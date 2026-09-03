"""
Unit tests for the Yahoo Finance symbol-mapping layer.

This mapping is the load-bearing piece of the Yahoo provider integration:
Yahoo resolves a bare "BTC" to the Grayscale Bitcoin Trust ETF, not Bitcoin
itself, so every ticker must be routed through asset-type-aware suffixing
before it reaches Yahoo's endpoints.
"""
import pytest

from modules.market.models import AssetType
from modules.market.service import _yahoo_symbol, _strip_yahoo_suffix


def test_crypto_ticker_gets_dash_usd_suffix():
    assert _yahoo_symbol("BTC", AssetType.CRYPTO) == "BTC-USD"


def test_crypto_ticker_already_suffixed_is_left_alone():
    assert _yahoo_symbol("ETH-USD", AssetType.CRYPTO) == "ETH-USD"


def test_forex_ticker_gets_equals_x_suffix():
    assert _yahoo_symbol("EURUSD", AssetType.FOREX) == "EURUSD=X"


def test_commodity_futures_root_gets_equals_f_suffix():
    assert _yahoo_symbol("GC", AssetType.COMMODITY) == "GC=F"


def test_commodity_etf_tracker_is_left_alone():
    assert _yahoo_symbol("GLD", AssetType.COMMODITY) == "GLD"


def test_commodity_already_suffixed_is_left_alone():
    assert _yahoo_symbol("CL=F", AssetType.COMMODITY) == "CL=F"


def test_stock_ticker_is_unchanged():
    assert _yahoo_symbol("AAPL", AssetType.STOCK) == "AAPL"


def test_etf_ticker_is_unchanged():
    assert _yahoo_symbol("SPY", AssetType.ETF) == "SPY"


def test_index_ticker_is_unchanged():
    assert _yahoo_symbol("SPX", AssetType.INDEX) == "SPX"


# ─── _strip_yahoo_suffix (inverse: a Yahoo search hit -> our internal ticker) ──


def test_strip_crypto_suffix_from_search_hit():
    assert _strip_yahoo_suffix("SOL-USD", AssetType.CRYPTO) == "SOL"


def test_strip_forex_suffix_from_search_hit():
    assert _strip_yahoo_suffix("EURUSD=X", AssetType.FOREX) == "EURUSD"


def test_strip_commodity_suffix_from_search_hit():
    assert _strip_yahoo_suffix("HG=F", AssetType.COMMODITY) == "HG"


def test_strip_leaves_stock_ticker_unchanged():
    assert _strip_yahoo_suffix("AMZN", AssetType.STOCK) == "AMZN"


def test_yahoo_symbol_and_strip_are_inverses_for_crypto():
    ticker = "BTC"
    assert _strip_yahoo_suffix(_yahoo_symbol(ticker, AssetType.CRYPTO), AssetType.CRYPTO) == ticker
