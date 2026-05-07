"""
Rule-based event extraction worker.

This is a baseline MVP pipeline that converts raw news_articles into structured
events with confidence gating and review status assignment.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import (
    Event,
    EventArticle,
    EventImpact,
    EventStatus,
    EventTag,
    EventType,
    ImpactDirection,
    NewsArticle,
)
from modules.market.models import Asset
from workers.celery_app import celery_app
from workers.entity_utils import build_asset_alias_map, extract_asset_mentions, extract_entity_tags
from workers.kg_utils import build_asset_graph, expand_related_assets
from workers.model_runtime import predict_event_type
from workers.nlp_utils import (
    article_passes_language_gate,
    compute_article_sentiment,
    detect_article_language,
    relevance_label_for_score,
    score_article_relevance,
)
from workers.alerts import evaluate_event_alerts

logger = logging.getLogger(__name__)

AUTO_APPROVE_THRESHOLD = 0.72
HUMAN_REVIEW_THRESHOLD = 0.55

SOURCE_CREDIBILITY: dict[str, float] = {
    "reuters": 0.95,
    "associated press": 0.93,
    "ap news": 0.90,
    "al jazeera": 0.84,
    "newsapi": 0.70,
    "gdelt": 0.75,
}

EVENT_KEYWORDS: dict[EventType, tuple[str, ...]] = {
    EventType.CONFLICT: (
        "attack",
        "conflict",
        "war",
        "missile",
        "military",
        "offensive",
        "invasion",
        "clash",
    ),
    EventType.SANCTION: (
        "sanction",
        "blacklist",
        "embargo",
        "restricted entity",
    ),
    EventType.TRADE_POLICY: (
        "tariff",
        "export control",
        "trade restriction",
        "trade policy",
        "import ban",
    ),
    EventType.ECONOMIC_DATA: (
        "inflation",
        "cpi",
        "gdp",
        "jobs report",
        "interest rate",
        "unemployment",
        "retail sales",
    ),
    EventType.ENERGY_DISRUPTION: (
        "oil supply",
        "gas supply",
        "pipeline",
        "refinery",
        "opec",
        "energy disruption",
        "power outage",
    ),
    EventType.ELECTION: (
        "election",
        "vote",
        "ballot",
        "polls",
        "presidential race",
    ),
    EventType.REGULATION: (
        "regulation",
        "regulatory",
        "antitrust",
        "compliance",
        "ban approved",
        "policy change",
    ),
}

COUNTRY_ALIASES: dict[str, str] = {
    "united states": "United States",
    "u.s.": "United States",
    "us": "United States",
    "china": "China",
    "india": "India",
    "russia": "Russia",
    "ukraine": "Ukraine",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "israel": "Israel",
    "iran": "Iran",
    "taiwan": "Taiwan",
    "japan": "Japan",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "saudi arabia": "Saudi Arabia",
    "uae": "United Arab Emirates",
    "germany": "Germany",
    "france": "France",
}

SHORT_TOKEN_ALIASES = {"us", "uk", "uae"}

HIGH_IMPACT_TERMS = {
    "escalation",
    "emergency",
    "nationwide",
    "record",
    "surge",
    "collapsed",
    "default",
    "shutdown",
    "strike",
    "retaliation",
    "explosion",
    "attack",
    "sanctioned",
    "ban",
}

POSITIVE_IMPACT_TERMS = {
    "approval",
    "approved",
    "deal",
    "agreement",
    "growth",
    "expands",
    "eases",
    "cuts rates",
    "stimulus",
}

NEGATIVE_IMPACT_TERMS = {
    "ban",
    "sanction",
    "tariff",
    "export control",
    "shortage",
    "strike",
    "attack",
    "invasion",
    "restriction",
    "outage",
}

SIMILARITY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "will",
    "are",
    "has",
    "was",
    "were",
    "its",
    "their",
    "into",
    "over",
    "under",
    "after",
    "before",
    "about",
    "amid",
    "near",
    "into",
    "onto",
    "than",
    "also",
    "more",
    "most",
    "just",
    "news",
}


def _infer_event_type(text: str) -> tuple[Optional[EventType], float]:
    model_label, model_score = predict_event_type(text)
    if model_label:
        try:
            return EventType(model_label), float(model_score or 0.0)
        except ValueError:
            pass

    text_l = text.lower()
    best_type: Optional[EventType] = None
    best_hits = 0

    for event_type, keywords in EVENT_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in text_l)
        if hits > best_hits:
            best_type = event_type
            best_hits = hits

    if not best_type:
        return None, 0.0

    # Lightweight confidence heuristic for MVP baseline.
    confidence = min(0.92, 0.45 + (best_hits * 0.11))
    return best_type, confidence


def _source_score(source: Optional[str]) -> float:
    if not source:
        return 0.68
    source_l = source.lower()
    for key, score in SOURCE_CREDIBILITY.items():
        if key in source_l:
            return score
    return 0.70


def _recency_score(published_at: Optional[datetime]) -> float:
    if not published_at:
        return 0.65
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age = now - published_at.astimezone(timezone.utc)
    if age <= timedelta(hours=2):
        return 0.95
    if age <= timedelta(hours=12):
        return 0.88
    if age <= timedelta(days=1):
        return 0.80
    if age <= timedelta(days=3):
        return 0.70
    if age <= timedelta(days=7):
        return 0.62
    return 0.52


def _market_context_score(text: str, tickers: list[str]) -> float:
    text_l = text.lower()
    market_terms = (
        "stock",
        "shares",
        "equity",
        "bond",
        "yield",
        "futures",
        "market",
        "investor",
        "earnings",
        "guidance",
        "volatility",
        "index",
    )
    term_hits = sum(1 for token in market_terms if token in text_l)
    ticker_signal = min(1.0, len(tickers) * 0.2)
    return min(1.0, 0.42 + term_hits * 0.07 + ticker_signal)


def _composite_confidence(
    base_confidence: float,
    source: Optional[str],
    published_at: Optional[datetime],
    text: str,
    tickers: list[str],
) -> float:
    source_component = _source_score(source)
    recency_component = _recency_score(published_at)
    market_component = _market_context_score(text, tickers)
    # Weighted blend tuned for deterministic MVP behavior.
    blended = (
        0.46 * base_confidence
        + 0.20 * source_component
        + 0.16 * recency_component
        + 0.18 * market_component
    )
    # Slight lift if multiple affected assets were found.
    multi_asset_boost = 0.02 * min(3, len(tickers))
    return max(0.0, min(0.95, blended + multi_asset_boost))


def _derive_severity(event_type: EventType, text: str, confidence: float, ticker_count: int) -> int:
    text_l = text.lower()
    impact_hits = sum(1 for token in HIGH_IMPACT_TERMS if token in text_l)
    event_bias = {
        EventType.CONFLICT: 4,
        EventType.SANCTION: 4,
        EventType.ENERGY_DISRUPTION: 4,
        EventType.TRADE_POLICY: 3,
        EventType.ECONOMIC_DATA: 3,
        EventType.ELECTION: 3,
        EventType.REGULATION: 2,
    }.get(event_type, 3)
    confidence_lift = 1 if confidence >= 0.80 else 0
    ticker_lift = 1 if ticker_count >= 3 else 0
    score = event_bias + min(2, impact_hits // 2) + confidence_lift + ticker_lift
    return int(max(1, min(5, score)))


def _impact_signal(text: str) -> tuple[float, float]:
    text_l = text.lower()
    neg_hits = sum(1 for token in NEGATIVE_IMPACT_TERMS if token in text_l)
    pos_hits = sum(1 for token in POSITIVE_IMPACT_TERMS if token in text_l)
    total = max(1, neg_hits + pos_hits)
    polarity = (pos_hits - neg_hits) / total  # -1 .. +1
    intensity = min(1.0, 0.35 + 0.15 * total)
    return polarity, intensity


def _extract_country(text: str) -> Optional[str]:
    text_l = text.lower()
    for alias, canonical in COUNTRY_ALIASES.items():
        if alias in SHORT_TOKEN_ALIASES:
            if re.search(rf"\b{re.escape(alias)}\b", text_l):
                return canonical
        elif alias in text_l:
            return canonical
    return None


def _tokenize_for_similarity(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
    return [token for token in tokens if token not in SIMILARITY_STOPWORDS]


def _vectorize_tokens(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return {}
    return {token: value / norm for token, value in counts.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = sum(weight * vec_b.get(token, 0.0) for token, weight in vec_a.items())
    return max(0.0, min(1.0, dot))


def _build_similarity_corpus(session: Session) -> list[dict]:
    if not settings.NLP_ENABLE_L4_SIMILARITY_MAPPING:
        return []
    event_rows = session.execute(
        select(
            Event.id,
            Event.event_type,
            Event.title,
            Event.description,
            Event.confidence_score,
        )
        .where(Event.status.in_((EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)))
        .order_by(Event.published_at.desc().nullslast(), Event.created_at.desc())
        .limit(settings.NLP_L4_LOOKBACK_EVENTS)
    ).all()
    if not event_rows:
        return []

    event_ids = [row.id for row in event_rows]
    impact_rows = session.execute(
        select(EventImpact.event_id, Asset.ticker, EventImpact.confidence_score)
        .join(Asset, Asset.id == EventImpact.asset_id)
        .where(EventImpact.event_id.in_(event_ids))
    ).all()
    impacts_by_event: dict[str, dict[str, float]] = {}
    for event_id, ticker, confidence_score in impact_rows:
        key = str(event_id)
        bucket = impacts_by_event.setdefault(key, {})
        bucket[ticker.upper()] = max(bucket.get(ticker.upper(), 0.0), float(confidence_score or 0.5))

    corpus: list[dict] = []
    for row in event_rows:
        event_id = str(row.id)
        asset_scores = impacts_by_event.get(event_id, {})
        if not asset_scores:
            continue
        text = f"{row.title or ''}\n{row.description or ''}"
        vector = _vectorize_tokens(_tokenize_for_similarity(text))
        if not vector:
            continue
        corpus.append(
            {
                "event_type": row.event_type,
                "vector": vector,
                "asset_scores": asset_scores,
                "confidence": float(row.confidence_score or 0.6),
            }
        )
    return corpus


def _expand_sector_assets(
    direct_tickers: list[str],
    asset_lookup: dict[str, Asset],
    sector_members: dict[str, list[str]],
    relevance_score: float,
) -> dict[str, float]:
    if not settings.NLP_ENABLE_L3_SECTOR_MAPPING:
        return {}
    direct = {ticker.upper() for ticker in direct_tickers}
    if not direct:
        return {}

    sector_hits: set[str] = set()
    for ticker in direct:
        asset = asset_lookup.get(ticker)
        if asset and asset.sector:
            sector_hits.add(asset.sector)
    if not sector_hits:
        return {}

    derived: dict[str, float] = {}
    relevance_factor = max(0.25, min(1.0, relevance_score))
    for sector in sector_hits:
        candidates = sector_members.get(sector, [])
        for ticker in candidates[: settings.NLP_L3_MAX_ASSETS_PER_SECTOR]:
            normalized = ticker.upper()
            if normalized in direct:
                continue
            weight = min(1.0, settings.NLP_L3_BASE_WEIGHT * relevance_factor)
            derived[normalized] = max(derived.get(normalized, 0.0), weight)
    return derived


def _expand_similarity_assets(
    text: str,
    event_type: EventType,
    direct_tickers: list[str],
    similarity_corpus: list[dict],
) -> dict[str, float]:
    if not settings.NLP_ENABLE_L4_SIMILARITY_MAPPING:
        return {}
    direct = {ticker.upper() for ticker in direct_tickers}
    base_vector = _vectorize_tokens(_tokenize_for_similarity(text))
    if not base_vector:
        return {}

    candidates: dict[str, float] = {}
    for row in similarity_corpus:
        if row["event_type"] != event_type:
            continue
        similarity = _cosine_similarity(base_vector, row["vector"])
        if similarity < settings.NLP_L4_MIN_SIMILARITY:
            continue
        for ticker, prior_score in row["asset_scores"].items():
            normalized = ticker.upper()
            if normalized in direct:
                continue
            score = similarity * float(prior_score or 0.5)
            candidates[normalized] = max(candidates.get(normalized, 0.0), score)

    ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
    capped = ranked[: settings.NLP_L4_MAX_ASSET_CANDIDATES]
    return {ticker: max(0.0, min(1.0, score)) for ticker, score in capped}


def _validate_quality_gates(
    *,
    session: Session,
    article: NewsArticle,
    event_type: EventType,
    confidence: float,
    published_at: datetime,
    country: Optional[str],
    proposed_tickers: list[str],
    asset_lookup: dict[str, Asset],
) -> tuple[bool, list[str]]:
    if not settings.QUALITY_ENFORCE_GATES:
        return True, []

    errors: list[str] = []
    if confidence < settings.QUALITY_MIN_CONFIDENCE:
        errors.append("confidence_threshold")
    if not article.title or not event_type or not article.source or not article.url:
        errors.append("schema_validation")
    if article.published_at:
        delta = abs((published_at - article.published_at).total_seconds())
        if delta > settings.QUALITY_TEMPORAL_MAX_HOURS * 3600:
            errors.append("temporal_consistency")
    invalid_tickers = [ticker for ticker in proposed_tickers if ticker.upper() not in asset_lookup]
    if invalid_tickers:
        errors.append("asset_validation")

    # Duplicate detection gate: same source article hash already linked to an event of same type/country/day.
    duplicate = session.execute(
        select(Event.id)
        .join(EventArticle, EventArticle.event_id == Event.id)
        .where(
            EventArticle.article_id == article.id,
            Event.event_type == event_type,
            Event.country == country,
            func.date(Event.published_at) == published_at.date(),
        )
    ).scalar_one_or_none()
    if duplicate:
        errors.append("duplicate_detection")

    return len(errors) == 0, errors


def _to_status(confidence: float) -> EventStatus:
    if confidence >= AUTO_APPROVE_THRESHOLD:
        return EventStatus.AUTO_APPROVED
    if confidence >= HUMAN_REVIEW_THRESHOLD:
        return EventStatus.PENDING_REVIEW
    return EventStatus.REJECTED


def _to_impact_direction(event_type: EventType) -> ImpactDirection:
    if event_type in {EventType.CONFLICT, EventType.SANCTION, EventType.ENERGY_DISRUPTION}:
        return ImpactDirection.NEGATIVE
    return ImpactDirection.NEUTRAL


def _to_impact_direction_with_signal(event_type: EventType, polarity: float) -> ImpactDirection:
    if event_type in {EventType.CONFLICT, EventType.SANCTION, EventType.ENERGY_DISRUPTION} and polarity < 0.35:
        return ImpactDirection.NEGATIVE
    if event_type in {EventType.REGULATION, EventType.ECONOMIC_DATA, EventType.TRADE_POLICY}:
        if polarity >= 0.20:
            return ImpactDirection.POSITIVE
        if polarity <= -0.20:
            return ImpactDirection.NEGATIVE
    if event_type == EventType.ELECTION:
        if abs(polarity) >= 0.35:
            return ImpactDirection.POSITIVE if polarity > 0 else ImpactDirection.NEGATIVE
    return _to_impact_direction(event_type)


def _annotate_article_nlp(article: NewsArticle, text: str) -> tuple[str, float, float, str]:
    language_code, language_confidence = detect_article_language(text)
    relevance_score = score_article_relevance(text, source=article.source)
    relevance_label = relevance_label_for_score(relevance_score)
    article.language_code = language_code
    article.language_confidence = language_confidence
    article.relevance_score = relevance_score
    article.relevance_label = relevance_label
    article.nlp_processed_at = datetime.now(timezone.utc)
    return language_code, language_confidence, relevance_score, relevance_label


def _ensure_event_tags(session: Session, event_id, tags: list[str]) -> int:
    created = 0
    for tag in tags:
        existing = session.execute(
            select(EventTag).where(
                EventTag.event_id == event_id,
                EventTag.tag == tag,
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(EventTag(event_id=event_id, tag=tag))
        created += 1
    return created


def _ensure_event_impacts(
    session: Session,
    event_id,
    confidence: float,
    relevance_score: float,
    impact_strength: float,
    impact_direction: ImpactDirection,
    tickers: list[str],
    asset_lookup: dict[str, Asset],
) -> int:
    created = 0

    for ticker in tickers:
        asset = asset_lookup.get(ticker)
        if not asset:
            continue

        existing = session.execute(
            select(EventImpact).where(
                EventImpact.event_id == event_id,
                EventImpact.asset_id == asset.id,
            )
        ).scalar_one_or_none()
        if existing:
            continue

        session.add(
            EventImpact(
                event_id=event_id,
                asset_id=asset.id,
                impact_direction=impact_direction,
                impact_strength=max(0.0, min(1.0, impact_strength)),
                confidence_score=max(0.0, min(1.0, (confidence + relevance_score) / 2)),
            )
        )
        created += 1

    return created


def _ensure_l2_event_impacts(
    session: Session,
    event_id,
    confidence: float,
    relevance_score: float,
    impact_direction: ImpactDirection,
    derived_scores: dict[str, float],
    asset_lookup: dict[str, Asset],
) -> int:
    created = 0
    for ticker, score in derived_scores.items():
        asset = asset_lookup.get(ticker)
        if not asset:
            continue
        existing = session.execute(
            select(EventImpact).where(
                EventImpact.event_id == event_id,
                EventImpact.asset_id == asset.id,
            )
        ).scalar_one_or_none()
        if existing:
            continue
        blended_confidence = max(0.0, min(1.0, ((confidence + relevance_score) / 2) * score))
        session.add(
            EventImpact(
                event_id=event_id,
                asset_id=asset.id,
                impact_direction=impact_direction,
                impact_strength=max(0.0, min(1.0, score)),
                confidence_score=blended_confidence,
            )
        )
        created += 1
    return created


@celery_app.task(name="workers.event_pipeline.process_unprocessed_articles", bind=True, max_retries=3)
def process_unprocessed_articles(self, batch_size: int = 200):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    processed = 0
    created_events = 0
    auto_approved = 0
    pending_review = 0
    rejected = 0
    impacts_created = 0
    language_filtered = 0
    relevance_filtered = 0
    tags_created = 0
    quality_rejected = 0
    quality_failures: dict[str, int] = {}
    notify_event_ids: set[str] = set()

    with Session(engine) as session:
        assets = session.execute(select(Asset)).scalars().all()
        asset_lookup = {asset.ticker.upper(): asset for asset in assets}
        asset_tickers = set(asset_lookup.keys())
        asset_alias_map = build_asset_alias_map(assets)
        sector_members: dict[str, list[str]] = {}
        for asset in assets:
            if asset.sector:
                sector_members.setdefault(asset.sector, []).append(asset.ticker.upper())
        entity_id_by_ticker, ticker_by_entity_id, asset_graph = build_asset_graph(session)
        similarity_corpus = _build_similarity_corpus(session)

        articles = session.execute(
            select(NewsArticle)
            .where(NewsArticle.is_processed.is_(False))
            .order_by(NewsArticle.created_at.asc())
            .limit(batch_size)
        ).scalars().all()

        for article in articles:
            processed += 1
            text = f"{article.title or ''}\n{article.content or ''}"
            language_code, language_confidence, relevance_score, _ = _annotate_article_nlp(article, text)
            article.sentiment_score = compute_article_sentiment(text)

            if not article_passes_language_gate(language_code, language_confidence):
                article.is_processed = True
                rejected += 1
                language_filtered += 1
                continue

            if relevance_score < settings.NLP_RELEVANCE_THRESHOLD:
                article.is_processed = True
                rejected += 1
                relevance_filtered += 1
                continue

            event_type, base_confidence = _infer_event_type(text)

            if not event_type:
                article.is_processed = True
                rejected += 1
                continue

            mentioned_tickers = extract_asset_mentions(text, asset_tickers, asset_alias_map)
            confidence = _composite_confidence(
                base_confidence=base_confidence,
                source=article.source,
                published_at=article.published_at,
                text=text,
                tickers=mentioned_tickers,
            )
            status = _to_status(confidence)
            if status == EventStatus.REJECTED:
                article.is_processed = True
                rejected += 1
                continue

            country = _extract_country(text)
            relevance_score = max(0.0, min(1.0, (confidence + _market_context_score(text, mentioned_tickers)) / 2))
            polarity, intensity = _impact_signal(text)
            impact_direction = _to_impact_direction_with_signal(event_type, polarity=polarity)
            impact_strength = max(0.0, min(1.0, 0.55 * confidence + 0.45 * intensity))
            severity = _derive_severity(
                event_type=event_type,
                text=text,
                confidence=confidence,
                ticker_count=len(mentioned_tickers),
            )
            entity_tags = extract_entity_tags(text, mentioned_tickers, asset_lookup)
            l2_tickers = expand_related_assets(
                mentioned_tickers,
                entity_id_by_ticker=entity_id_by_ticker,
                ticker_by_entity_id=ticker_by_entity_id,
                adjacency=asset_graph,
            )
            l3_tickers = _expand_sector_assets(
                direct_tickers=mentioned_tickers,
                asset_lookup=asset_lookup,
                sector_members=sector_members,
                relevance_score=relevance_score,
            )
            l4_tickers = _expand_similarity_assets(
                text=text,
                event_type=event_type,
                direct_tickers=mentioned_tickers + list(l2_tickers.keys()) + list(l3_tickers.keys()),
                similarity_corpus=similarity_corpus,
            )

            # Dedup by title + type + country + day window.
            published_at = article.published_at or datetime.now(timezone.utc)
            published_date = published_at.date()
            proposed_tickers = sorted(
                {
                    ticker.upper()
                    for ticker in (mentioned_tickers + list(l2_tickers.keys()) + list(l3_tickers.keys()) + list(l4_tickers.keys()))
                }
            )
            is_valid, gate_errors = _validate_quality_gates(
                session=session,
                article=article,
                event_type=event_type,
                confidence=confidence,
                published_at=published_at,
                country=country,
                proposed_tickers=proposed_tickers,
                asset_lookup=asset_lookup,
            )
            if not is_valid:
                article.is_processed = True
                rejected += 1
                quality_rejected += 1
                for code in gate_errors:
                    quality_failures[code] = quality_failures.get(code, 0) + 1
                continue

            existing = session.execute(
                select(Event).where(
                    Event.title == article.title,
                    Event.event_type == event_type,
                    Event.country == country,
                    func.date(Event.published_at) == published_date,
                )
            ).scalar_one_or_none()

            if existing:
                already_linked = session.execute(
                    select(EventArticle).where(
                        EventArticle.event_id == existing.id,
                        EventArticle.article_id == article.id,
                    )
                ).scalar_one_or_none()
                if not already_linked:
                    session.add(
                        EventArticle(
                            event_id=existing.id,
                            article_id=article.id,
                            relevance_score=relevance_score,
                        )
                    )
                if existing.confidence_score is None or confidence > float(existing.confidence_score):
                    existing.confidence_score = confidence
                    existing.severity = severity
                    existing.status = _to_status(confidence)
                tags_created += _ensure_event_tags(session, existing.id, entity_tags)
                impacts_created += _ensure_event_impacts(
                    session=session,
                    event_id=existing.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_strength=impact_strength,
                    impact_direction=impact_direction,
                    tickers=mentioned_tickers,
                    asset_lookup=asset_lookup,
                )
                impacts_created += _ensure_l2_event_impacts(
                    session=session,
                    event_id=existing.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_direction=impact_direction,
                    derived_scores=l2_tickers,
                    asset_lookup=asset_lookup,
                )
                impacts_created += _ensure_l2_event_impacts(
                    session=session,
                    event_id=existing.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_direction=impact_direction,
                    derived_scores=l3_tickers,
                    asset_lookup=asset_lookup,
                )
                impacts_created += _ensure_l2_event_impacts(
                    session=session,
                    event_id=existing.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_direction=impact_direction,
                    derived_scores=l4_tickers,
                    asset_lookup=asset_lookup,
                )
                if existing.status in (EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED):
                    notify_event_ids.add(str(existing.id))
            else:
                event = Event(
                    title=article.title,
                    description=(article.content[:2000] if article.content else None),
                    event_type=event_type,
                    country=country,
                    severity=severity,
                    source=article.source,
                    source_url=article.url,
                    status=status,
                    confidence_score=confidence,
                    published_at=article.published_at,
                )
                session.add(event)
                session.flush()
                session.add(
                    EventArticle(
                        event_id=event.id,
                        article_id=article.id,
                        relevance_score=relevance_score,
                    )
                )
                tags_created += _ensure_event_tags(session, event.id, entity_tags)
                impacts_created += _ensure_event_impacts(
                    session=session,
                    event_id=event.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_strength=impact_strength,
                    impact_direction=impact_direction,
                    tickers=mentioned_tickers,
                    asset_lookup=asset_lookup,
                )
                impacts_created += _ensure_l2_event_impacts(
                    session=session,
                    event_id=event.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_direction=impact_direction,
                    derived_scores=l2_tickers,
                    asset_lookup=asset_lookup,
                )
                impacts_created += _ensure_l2_event_impacts(
                    session=session,
                    event_id=event.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_direction=impact_direction,
                    derived_scores=l3_tickers,
                    asset_lookup=asset_lookup,
                )
                impacts_created += _ensure_l2_event_impacts(
                    session=session,
                    event_id=event.id,
                    confidence=confidence,
                    relevance_score=relevance_score,
                    impact_direction=impact_direction,
                    derived_scores=l4_tickers,
                    asset_lookup=asset_lookup,
                )
                created_events += 1
                if event.status in (EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED):
                    notify_event_ids.add(str(event.id))

            article.is_processed = True

            if status == EventStatus.AUTO_APPROVED:
                auto_approved += 1
            elif status == EventStatus.PENDING_REVIEW:
                pending_review += 1

        session.commit()

    from workers.predictions import generate_predictions_for_event
    for event_id in sorted(notify_event_ids):
        evaluate_event_alerts.delay(event_id)
        generate_predictions_for_event.delay(event_id)

    result = {
        "processed": processed,
        "created_events": created_events,
        "auto_approved": auto_approved,
        "pending_review": pending_review,
        "rejected": rejected,
        "language_filtered": language_filtered,
        "relevance_filtered": relevance_filtered,
        "quality_rejected": quality_rejected,
        "quality_failures": quality_failures,
        "impacts_created": impacts_created,
        "tags_created": tags_created,
    }
    logger.info("Event pipeline batch complete: %s", result)
    return result


@celery_app.task(name="workers.event_pipeline.backfill_article_nlp_metadata", bind=True, max_retries=3)
def backfill_article_nlp_metadata(self, batch_size: int = 500):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    updated = 0
    with Session(engine) as session:
        articles = session.execute(
            select(NewsArticle)
            .where(NewsArticle.nlp_processed_at.is_(None))
            .order_by(NewsArticle.created_at.asc())
            .limit(batch_size)
        ).scalars().all()

        for article in articles:
            text = f"{article.title or ''}\n{article.content or ''}"
            _annotate_article_nlp(article, text)
            updated += 1

        session.commit()

    result = {"updated": updated}
    logger.info("Backfilled NLP metadata for articles: %s", result)
    return result


@celery_app.task(name="workers.event_pipeline.backfill_event_entities", bind=True, max_retries=3)
def backfill_event_entities(self, batch_size: int = 250):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    updated_events = 0
    created_tags = 0
    created_impacts = 0

    with Session(engine) as session:
        assets = session.execute(select(Asset)).scalars().all()
        asset_lookup = {asset.ticker.upper(): asset for asset in assets}
        asset_tickers = set(asset_lookup.keys())
        asset_alias_map = build_asset_alias_map(assets)
        sector_members: dict[str, list[str]] = {}
        for asset in assets:
            if asset.sector:
                sector_members.setdefault(asset.sector, []).append(asset.ticker.upper())
        entity_id_by_ticker, ticker_by_entity_id, asset_graph = build_asset_graph(session)
        similarity_corpus = _build_similarity_corpus(session)

        events = session.execute(
            select(Event)
            .order_by(Event.created_at.desc())
            .limit(batch_size)
        ).scalars().all()

        for event in events:
            articles = session.execute(
                select(NewsArticle)
                .join(EventArticle, EventArticle.article_id == NewsArticle.id)
                .where(EventArticle.event_id == event.id)
                .order_by(NewsArticle.published_at.desc())
            ).scalars().all()
            if not articles:
                continue

            combined_text = "\n".join(f"{article.title or ''}\n{article.content or ''}" for article in articles)
            tickers = extract_asset_mentions(combined_text, asset_tickers, asset_alias_map)
            tags = extract_entity_tags(combined_text, tickers, asset_lookup)

            created_tags += _ensure_event_tags(session, event.id, tags)
            created_impacts += _ensure_event_impacts(
                session=session,
                event_id=event.id,
                confidence=float(event.confidence_score or 0.6),
                relevance_score=0.7,
                impact_strength=0.6,
                impact_direction=_to_impact_direction(event.event_type),
                tickers=tickers,
                asset_lookup=asset_lookup,
            )
            created_impacts += _ensure_l2_event_impacts(
                session=session,
                event_id=event.id,
                confidence=float(event.confidence_score or 0.6),
                relevance_score=0.7,
                impact_direction=_to_impact_direction(event.event_type),
                derived_scores=expand_related_assets(
                    tickers,
                    entity_id_by_ticker=entity_id_by_ticker,
                    ticker_by_entity_id=ticker_by_entity_id,
                    adjacency=asset_graph,
                ),
                asset_lookup=asset_lookup,
            )
            created_impacts += _ensure_l2_event_impacts(
                session=session,
                event_id=event.id,
                confidence=float(event.confidence_score or 0.6),
                relevance_score=0.7,
                impact_direction=_to_impact_direction(event.event_type),
                derived_scores=_expand_sector_assets(
                    direct_tickers=tickers,
                    asset_lookup=asset_lookup,
                    sector_members=sector_members,
                    relevance_score=0.7,
                ),
                asset_lookup=asset_lookup,
            )
            created_impacts += _ensure_l2_event_impacts(
                session=session,
                event_id=event.id,
                confidence=float(event.confidence_score or 0.6),
                relevance_score=0.7,
                impact_direction=_to_impact_direction(event.event_type),
                derived_scores=_expand_similarity_assets(
                    text=combined_text,
                    event_type=event.event_type,
                    direct_tickers=tickers,
                    similarity_corpus=similarity_corpus,
                ),
                asset_lookup=asset_lookup,
            )
            updated_events += 1

        session.commit()

    result = {
        "updated_events": updated_events,
        "created_tags": created_tags,
        "created_impacts": created_impacts,
    }
    logger.info("Backfilled event entities: %s", result)
    return result
