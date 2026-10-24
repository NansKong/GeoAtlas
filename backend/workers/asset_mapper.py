"""
Geopolitical & Macroeconomic Event-Driven Asset Mapper.

Principles:
1. Event-specific, deterministic mappings (no generic templated 5-asset dumping).
2. Explicit directional expectations:
   - ImpactDirection.POSITIVE (▲)
   - ImpactDirection.NEGATIVE (▼)
   - ImpactDirection.NEUTRAL
3. Qualitative magnitude: 'low' | 'medium' | 'high' (no invented % numbers).
4. One-line rationale clearly labeled 'Rule-based expectation: ...'.
5. Direct asset mentions take precedence and receive direct attribution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from modules.events.models import EventType, ImpactDirection


@dataclass(frozen=True)
class ExpectedImpact:
    ticker: str
    direction: ImpactDirection
    magnitude: str  # 'low' | 'medium' | 'high'
    strength: float
    rationale: str


# ── Curated Event-Driven Expectations ─────────────────────────────────────────

CONFLICT_CORE_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("USO", ImpactDirection.POSITIVE, "high", 0.85, "Rule-based expectation: Crude supply risk & geopolitical risk premium"),
    ExpectedImpact("XOM", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Integrated oil major upstream earnings hedge"),
    ExpectedImpact("CVX", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Energy supply disruption beneficiary"),
    ExpectedImpact("GLD", ImpactDirection.POSITIVE, "medium", 0.80, "Rule-based expectation: Traditional safe-haven gold demand"),
    ExpectedImpact("TLT", ImpactDirection.POSITIVE, "medium", 0.70, "Rule-based expectation: Flight to safety in long-term US sovereign debt"),
    ExpectedImpact("DX-Y.NYB", ImpactDirection.POSITIVE, "low", 0.65, "Rule-based expectation: USD reserve currency safe-haven flow"),
    ExpectedImpact("LMT", ImpactDirection.POSITIVE, "medium", 0.80, "Rule-based expectation: Defense contractor weapon systems demand"),
    ExpectedImpact("RTX", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Aerospace & missile defense replenishment"),
    ExpectedImpact("SPY", ImpactDirection.NEGATIVE, "medium", 0.60, "Rule-based expectation: Broad risk-off sentiment in equities"),
]

ENERGY_DISRUPTION_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("USO", ImpactDirection.POSITIVE, "high", 0.90, "Rule-based expectation: Acute oil supply deficit risk"),
    ExpectedImpact("UNG", ImpactDirection.POSITIVE, "high", 0.85, "Rule-based expectation: Natural gas pipeline / LNG flow disruption"),
    ExpectedImpact("XLE", ImpactDirection.POSITIVE, "high", 0.80, "Rule-based expectation: Energy sector margin expansion"),
    ExpectedImpact("XOM", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Upstream production earnings lift"),
    ExpectedImpact("CVX", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Refining and crude export benefit"),
    ExpectedImpact("SPY", ImpactDirection.NEGATIVE, "low", 0.55, "Rule-based expectation: Energy-driven cost push inflation headwind"),
]

TRADE_POLICY_TECH_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("NVDA", ImpactDirection.NEGATIVE, "high", 0.80, "Rule-based expectation: Tech export controls restrict addressable market"),
    ExpectedImpact("TSM", ImpactDirection.NEGATIVE, "medium", 0.75, "Rule-based expectation: Cross-border semiconductor trade restrictions"),
    ExpectedImpact("ASML", ImpactDirection.NEGATIVE, "medium", 0.70, "Rule-based expectation: Lithography tool export bans to restricted regions"),
    ExpectedImpact("DX-Y.NYB", ImpactDirection.POSITIVE, "low", 0.60, "Rule-based expectation: Tariff policy USD appreciation dynamic"),
]

TRADE_POLICY_BROAD_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("CAT", ImpactDirection.NEGATIVE, "medium", 0.65, "Rule-based expectation: Heavy equipment retaliatory tariff friction"),
    ExpectedImpact("BA", ImpactDirection.NEGATIVE, "medium", 0.65, "Rule-based expectation: Aerospace export trade tension headwind"),
    ExpectedImpact("DX-Y.NYB", ImpactDirection.POSITIVE, "low", 0.60, "Rule-based expectation: Trade protectionism bilateral currency shift"),
]

EUROPEAN_FINANCIAL_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("EURUSD", ImpactDirection.NEGATIVE, "medium", 0.75, "Rule-based expectation: Eurozone sovereign yield spread & banking volatility"),
    ExpectedImpact("XLF", ImpactDirection.NEGATIVE, "low", 0.50, "Rule-based expectation: Global bank sentiment contagion"),
    ExpectedImpact("BAC", ImpactDirection.NEGATIVE, "low", 0.50, "Rule-based expectation: Financials correlation with sovereign debt moves"),
]

TAIWAN_TENSIONS_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("TSM", ImpactDirection.NEGATIVE, "high", 0.90, "Rule-based expectation: Taiwan Strait geopolitical disruption risk"),
    ExpectedImpact("NVDA", ImpactDirection.NEGATIVE, "high", 0.85, "Rule-based expectation: Foundry supply chain bottleneck vulnerability"),
    ExpectedImpact("AMD", ImpactDirection.NEGATIVE, "high", 0.80, "Rule-based expectation: Advanced packaging & wafer manufacturing risk"),
    ExpectedImpact("QQQ", ImpactDirection.NEGATIVE, "medium", 0.70, "Rule-based expectation: Tech hardware disruption risk-off repricing"),
]

INFLATION_HAWKISH_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("TLT", ImpactDirection.NEGATIVE, "medium", 0.80, "Rule-based expectation: Rising bond yields depress long duration debt"),
    ExpectedImpact("DX-Y.NYB", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Higher rate differentials strengthen USD"),
    ExpectedImpact("QQQ", ImpactDirection.NEGATIVE, "medium", 0.70, "Rule-based expectation: Elevated discount rates pressure growth multiples"),
]

STIMULUS_DOVISH_IMPACTS: list[ExpectedImpact] = [
    ExpectedImpact("TLT", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Falling benchmark yields lift Treasury prices"),
    ExpectedImpact("QQQ", ImpactDirection.POSITIVE, "medium", 0.75, "Rule-based expectation: Lower discount rate expands tech valuations"),
    ExpectedImpact("SPY", ImpactDirection.POSITIVE, "medium", 0.70, "Rule-based expectation: Monetary easing supports equity multiples"),
    ExpectedImpact("DX-Y.NYB", ImpactDirection.NEGATIVE, "medium", 0.65, "Rule-based expectation: Policy easing softens USD yield advantage"),
]


def map_event_to_expected_assets(
    event_type: EventType,
    title: str,
    country: Optional[str] = None,
    polarity: float = 0.0,
    valid_tickers: Optional[set[str]] = None,
) -> list[ExpectedImpact]:
    """
    Produce event-specific expected asset impacts based on verified geopolitical catalysts.
    Filters out any tickers that are not seeded in the database.
    """
    text_l = title.lower()
    results: list[ExpectedImpact] = []

    # 1. Taiwan Strait / Chip War specific catalyst
    if ("taiwan" in text_l or country == "Taiwan") and any(w in text_l for w in ("strait", "military", "drill", "blockade", "invasion", "war")):
        results.extend(TAIWAN_TENSIONS_IMPACTS)

    # 2. European Sovereign Debt / Banking catalyst (e.g. Barclays, French bond yields)
    elif any(w in text_l for w in ("barclays", "french bond", "french yields", "bundesbank", "cac 40", "sovereign yield", "eurozone banks")):
        results.extend(EUROPEAN_FINANCIAL_IMPACTS)

    # 3. Oil Tanker / Maritime Energy Corridor / Refinery Attack catalyst (Oil instruments first!)
    elif any(w in text_l for w in ("tanker", "tankers", "crude", "oil tanker", "petroleum", "pipeline", "refinery", "lng", "fuel depot")) or (
        any(w in text_l for w in ("hormuz", "persian gulf", "red sea", "bab el-mandeb", "aramco")) and any(w in text_l for w in ("strike", "attack", "hit", "fire", "drone", "missile", "seiz", "damage"))
    ):
        results.extend(ENERGY_DISRUPTION_IMPACTS)

    # 4. Conflict / War catalyst
    elif event_type == EventType.CONFLICT:
        results.extend(CONFLICT_CORE_IMPACTS)

    # 5. Energy Disruption catalyst
    elif event_type == EventType.ENERGY_DISRUPTION:
        results.extend(ENERGY_DISRUPTION_IMPACTS)

    # 5. Trade Policy / Tariffs catalyst
    elif event_type == EventType.TRADE_POLICY:
        if any(w in text_l for w in ("chip", "semiconductor", "ai", "tech", "gpu", "deepseek")):
            results.extend(TRADE_POLICY_TECH_IMPACTS)
        else:
            results.extend(TRADE_POLICY_BROAD_IMPACTS)

    # 6. Economic Data / Central Bank Policy catalyst
    elif event_type == EventType.ECONOMIC_DATA:
        if polarity < -0.15 or any(w in text_l for w in ("inflation jump", "cpi surge", "rate hike", "hawkish")):
            results.extend(INFLATION_HAWKISH_IMPACTS)
        else:
            results.extend(STIMULUS_DOVISH_IMPACTS)

    # Filter against available database tickers if provided
    if valid_tickers is not None:
        return [r for r in results if r.ticker in valid_tickers]

    return results
