from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from modules.knowledge_graph.models import KGEntity, KGRelationship

SUPPORTED_RELATIONSHIPS = {"SUPPLIES_TO", "PART_OF", "COMPETES_WITH", "CORRELATED", "REGULATES"}


def build_asset_graph(session: Session) -> tuple[dict[str, str], dict[str, str], dict[str, list[tuple[str, float]]]]:
    entities = session.execute(
        select(KGEntity.id, KGEntity.name).where(KGEntity.entity_type == "ASSET")
    ).all()
    entity_id_by_ticker = {name.upper(): str(entity_id) for entity_id, name in entities}
    ticker_by_entity_id = {str(entity_id): name.upper() for entity_id, name in entities}

    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    relationships = session.execute(
        select(KGRelationship.source_id, KGRelationship.target_id, KGRelationship.relationship, KGRelationship.strength)
        .where(KGRelationship.relationship.in_(SUPPORTED_RELATIONSHIPS))
    ).all()

    for source_id, target_id, relationship, strength in relationships:
        src = str(source_id)
        dst = str(target_id)
        weight = float(strength or 0.5)
        adjacency[src].append((dst, weight))
        if relationship in {"SUPPLIES_TO", "COMPETES_WITH", "CORRELATED", "REGULATES"}:
            adjacency[dst].append((src, weight * 0.9))

    return entity_id_by_ticker, ticker_by_entity_id, dict(adjacency)


def expand_related_assets(
    direct_tickers: list[str],
    entity_id_by_ticker: dict[str, str],
    ticker_by_entity_id: dict[str, str],
    adjacency: dict[str, list[tuple[str, float]]],
) -> dict[str, float]:
    if not settings.NLP_ENABLE_L2_KG_MAPPING:
        return {}

    direct = {ticker.upper() for ticker in direct_tickers}
    related: dict[str, float] = {}

    for ticker in direct:
        root = entity_id_by_ticker.get(ticker)
        if not root:
            continue
        for neighbor, strength in adjacency.get(root, []):
            neighbor_ticker = ticker_by_entity_id.get(neighbor)
            if neighbor_ticker and neighbor_ticker not in direct:
                score = strength * settings.NLP_L2_HOP1_WEIGHT
                related[neighbor_ticker] = max(related.get(neighbor_ticker, 0.0), score)
            for second_hop, second_strength in adjacency.get(neighbor, []):
                second_ticker = ticker_by_entity_id.get(second_hop)
                if second_ticker and second_ticker not in direct:
                    score = strength * second_strength * settings.NLP_L2_HOP2_WEIGHT
                    related[second_ticker] = max(related.get(second_ticker, 0.0), score)

    return related
