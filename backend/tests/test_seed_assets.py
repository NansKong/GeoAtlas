"""
Unit tests for seed_assets.py's baseline-price lookup.

Root cause under test: the seeder used to fall back to a hardcoded $100.00
for any ticker missing from its curated INITIAL_PRICES dict — which has no
forex entries at all. That fake price got written as the asset's first (and,
once live providers started failing/rate-limiting, only) MarketPrice row,
and the snapshot loop's DB-fallback then re-persisted it every cycle
forever, which is why several forex pairs (and one bogus "DXY Inc" stock)
were observed stuck at exactly $100.00 with zero price variance.
"""
from scripts.seed_assets import _baseline_price, INITIAL_PRICES


def test_known_ticker_returns_its_curated_price():
    assert _baseline_price("AAPL") == INITIAL_PRICES["AAPL"]


def test_unknown_forex_ticker_returns_none_not_a_fake_price():
    assert _baseline_price("EURUSD") is None


def test_unknown_ticker_returns_none_not_a_fake_price():
    assert _baseline_price("SOME_RANDOM_TICKER") is None
