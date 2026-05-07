from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from modules.market.models import Asset
from workers.model_runtime import predict_entities

ASSET_SUFFIX_TOKENS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "ltd",
    "limited",
    "plc",
    "sa",
    "ag",
    "nv",
    "holdings",
    "holding",
    "group",
    "trust",
    "series",
    "adr",
    "class",
}

GENERIC_SINGLE_TOKEN_ALIASES = {
    "global",
    "technology",
    "energy",
    "holdings",
    "capital",
    "resources",
    "materials",
    "financial",
    "industrial",
}

COUNTRY_TERMS: dict[str, tuple[str, ...]] = {
    "United States": ("united states", "u.s.", "us"),
    "China": ("china",),
    "India": ("india",),
    "Russia": ("russia",),
    "Ukraine": ("ukraine",),
    "United Kingdom": ("united kingdom", "uk"),
    "Israel": ("israel",),
    "Iran": ("iran",),
    "Taiwan": ("taiwan",),
    "Japan": ("japan",),
    "South Korea": ("south korea",),
    "Saudi Arabia": ("saudi arabia",),
}

TOPIC_TAGS: dict[str, tuple[str, ...]] = {
    "inflation": ("inflation", "cpi", "prices rose"),
    "rates": ("interest rate", "rate cut", "rate hike", "fed", "ecb", "central bank"),
    "semiconductors": ("semiconductor", "chip", "foundry"),
    "energy": ("oil", "gas", "lng", "refinery", "pipeline", "opec"),
    "trade": ("tariff", "trade policy", "export control", "import ban"),
    "sanctions": ("sanction", "embargo", "blacklist"),
    "elections": ("election", "ballot", "vote", "polls"),
    "defense": ("missile", "military", "defense", "drone", "airstrike"),
}


def normalize_entity_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _generate_asset_aliases(asset: Asset) -> set[str]:
    aliases = {asset.ticker.upper()}
    normalized_name = normalize_entity_text(asset.name or "")
    if not normalized_name:
        return aliases

    tokens = [token for token in normalized_name.split() if token]
    stripped_tokens = [token for token in tokens if token not in ASSET_SUFFIX_TOKENS]

    candidates = {
        normalized_name,
        " ".join(stripped_tokens),
    }
    if len(stripped_tokens) >= 2:
        candidates.add(" ".join(stripped_tokens[:2]))
    if len(stripped_tokens) >= 3:
        candidates.add(" ".join(stripped_tokens[:3]))

    for alias in candidates:
        cleaned = alias.strip()
        if not cleaned:
            continue
        alias_tokens = cleaned.split()
        if len(alias_tokens) == 1:
            if len(cleaned) < 5 or cleaned in GENERIC_SINGLE_TOKEN_ALIASES:
                continue
        aliases.add(cleaned)

    return aliases


def build_asset_alias_map(assets: Iterable[Asset]) -> dict[str, str]:
    alias_to_tickers: dict[str, set[str]] = defaultdict(set)
    for asset in assets:
        for alias in _generate_asset_aliases(asset):
            alias_to_tickers[alias].add(asset.ticker.upper())

    resolved: dict[str, str] = {}
    for alias, tickers in alias_to_tickers.items():
        if alias.isupper():
            resolved[alias] = next(iter(sorted(tickers)))
            continue
        if len(tickers) == 1:
            resolved[alias] = next(iter(tickers))
    return resolved


def extract_asset_mentions(text: str, asset_tickers: set[str], alias_map: dict[str, str]) -> list[str]:
    mentions = set()

    raw_candidates = set(re.findall(r"\b[A-Z][A-Z0-9]{0,9}\b", text.upper()))
    mentions.update(raw_candidates.intersection(asset_tickers))

    normalized = normalize_entity_text(text)
    if normalized:
        padded = f" {normalized} "
        for alias, ticker in alias_map.items():
            if alias.isupper():
                continue
            if f" {alias} " in padded:
                mentions.add(ticker)

    for entity in predict_entities(text):
        alias = normalize_entity_text(entity.get("text", ""))
        if alias and alias in alias_map:
            mentions.add(alias_map[alias])

    return sorted(mentions)


def extract_entity_tags(text: str, tickers: list[str], asset_lookup: dict[str, Asset]) -> list[str]:
    normalized = normalize_entity_text(text)
    padded = f" {normalized} "
    tags: set[str] = set()

    for ticker in tickers:
        asset = asset_lookup.get(ticker)
        if not asset:
            continue
        tags.add(ticker)
        core_name = normalize_entity_text(asset.name or "")
        if core_name:
            tag_label = " ".join(word.capitalize() for word in core_name.split()[:3])
            tags.add(tag_label)
        if asset.sector:
            tags.add(asset.sector)
        if asset.country:
            tags.add(asset.country)

    for country, aliases in COUNTRY_TERMS.items():
        if any(f" {normalize_entity_text(alias)} " in padded for alias in aliases):
            tags.add(country)

    for tag, keywords in TOPIC_TAGS.items():
        if any(keyword in normalized for keyword in keywords):
            tags.add(tag)

    for entity in predict_entities(text):
        entity_text = entity.get("text", "").strip()
        entity_label = entity.get("label", "").upper()
        if not entity_text:
            continue
        if entity_label in {"ORG", "GPE", "LOC", "PRODUCT", "NORP"}:
            tags.add(entity_text[:80])

    return sorted(tag for tag in tags if tag)[:12]
