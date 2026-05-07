from typing import List, Optional
import uuid
from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.events.models import (
    Event,
    EventArticle,
    EventImpact,
    EventReviewAction,
    EventTrainingExample,
    EventStatus,
    EventTag,
    EventType,
    NewsArticle,
)
from modules.events.schemas import (
    AffectedAssetOut,
    EventHeatmapPointOut,
    EventListOut,
    EventImpactOut,
    EventOut,
    EventReviewOut,
    NewsArticleOut,
    QualitySummaryOut,
    ReviewActionOut,
    ReviewArticleOut,
    ReviewDecisionIn,
    ReviewHistoryOut,
    TrainingExampleOut,
    WeeklyReviewProgressOut,
)
from modules.market.models import Asset
from modules.users.models import User
from modules.users.router import get_current_user

router = APIRouter(prefix="/events", tags=["Events"])
news_router = APIRouter(prefix="/news", tags=["News"])

PUBLISHED_EVENT_STATUSES = (EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED)

NEWS_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    EventType.CONFLICT.value: (
        "attack",
        "conflict",
        "war",
        "missile",
        "military",
        "offensive",
        "invasion",
        "clash",
    ),
    EventType.SANCTION.value: (
        "sanction",
        "embargo",
        "blacklist",
        "restricted entity",
    ),
    EventType.TRADE_POLICY.value: (
        "tariff",
        "trade policy",
        "export control",
        "trade restriction",
        "import ban",
    ),
    EventType.ECONOMIC_DATA.value: (
        "inflation",
        "cpi",
        "gdp",
        "jobs report",
        "interest rate",
        "unemployment",
        "retail sales",
        "central bank",
    ),
    EventType.ENERGY_DISRUPTION.value: (
        "oil supply",
        "gas supply",
        "pipeline",
        "refinery",
        "opec",
        "power outage",
        "lng",
        "crude",
    ),
    EventType.ELECTION.value: (
        "election",
        "vote",
        "ballot",
        "polls",
        "presidential race",
        "parliament",
    ),
    EventType.REGULATION.value: (
        "regulation",
        "regulatory",
        "antitrust",
        "compliance",
        "policy change",
        "ban approved",
        "lawmakers",
    ),
    "markets": (
        "stock",
        "shares",
        "earnings",
        "market",
        "investor",
        "bond",
        "yield",
        "forecast",
        "chip",
        "semiconductor",
        "technology",
    ),
}

COUNTRY_HEATMAP_COORDS: dict[str, tuple[float, float]] = {
    "United States": (37.0902, -95.7129),
    "China": (35.8617, 104.1954),
    "India": (20.5937, 78.9629),
    "Russia": (61.5240, 105.3188),
    "Ukraine": (48.3794, 31.1656),
    "United Kingdom": (55.3781, -3.4360),
    "Japan": (36.2048, 138.2529),
    "South Korea": (35.9078, 127.7669),
    "North Korea": (40.3399, 127.5101),
    "Germany": (51.1657, 10.4515),
    "France": (46.2276, 2.2137),
    "Saudi Arabia": (23.8859, 45.0792),
    "Israel": (31.0461, 34.8516),
    "Iran": (32.4279, 53.6880),
    "Taiwan": (23.6978, 120.9605),
    "Brazil": (-14.2350, -51.9253),
    "Canada": (56.1304, -106.3468),
    "Mexico": (23.6345, -102.5528),
    "Australia": (-25.2744, 133.7751),
    "South Africa": (-30.5595, 22.9375),
    "United Arab Emirates": (23.4241, 53.8478),
    "Qatar": (25.3548, 51.1839),
    "Lebanon": (33.8547, 35.8623),
    "Chad": (15.4542, 18.7322),
    "Sudan": (12.8628, 30.2176),
    "Morocco": (31.7917, -7.0926),
    "Senegal": (14.4974, -14.4524),
    "Hungary": (47.1625, 19.5033),
    "European Union": (50.8503, 4.3517),
}

COUNTRY_ALIASES: dict[str, str] = {
    "united states": "United States",
    "u.s.": "United States",
    "us": "United States",
    "america": "United States",
    "china": "China",
    "india": "India",
    "russia": "Russia",
    "ukraine": "Ukraine",
    "united kingdom": "United Kingdom",
    "britain": "United Kingdom",
    "uk": "United Kingdom",
    "japan": "Japan",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "germany": "Germany",
    "france": "France",
    "saudi arabia": "Saudi Arabia",
    "israel": "Israel",
    "iran": "Iran",
    "taiwan": "Taiwan",
    "brazil": "Brazil",
    "canada": "Canada",
    "mexico": "Mexico",
    "australia": "Australia",
    "south africa": "South Africa",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "qatar": "Qatar",
    "lebanon": "Lebanon",
    "chad": "Chad",
    "sudan": "Sudan",
    "morocco": "Morocco",
    "senegal": "Senegal",
    "hungary": "Hungary",
    "european union": "European Union",
    "eu": "European Union",
}

SHORT_COUNTRY_ALIASES = {"us", "uk", "uae", "eu"}

NEWS_CATEGORY_SEVERITY: dict[str, float] = {
    EventType.CONFLICT.value: 4.6,
    EventType.SANCTION.value: 3.8,
    EventType.TRADE_POLICY.value: 3.2,
    EventType.ENERGY_DISRUPTION.value: 4.1,
    EventType.ECONOMIC_DATA.value: 2.4,
    EventType.ELECTION.value: 2.7,
    EventType.REGULATION.value: 2.8,
    "markets": 2.0,
    "general": 2.3,
}


def _parse_event_status(token: str) -> EventStatus:
    normalized = token.strip().replace("-", "_").replace(" ", "_").upper()
    try:
        return EventStatus[normalized]
    except KeyError as exc:
        valid = ", ".join(s.value for s in EventStatus)
        raise HTTPException(status_code=422, detail=f"Invalid status '{token}'. Use one of: {valid}") from exc


def _parse_event_type(token: str) -> EventType:
    normalized = token.strip().replace("-", "_").replace(" ", "_").upper()
    try:
        return EventType[normalized]
    except KeyError as exc:
        valid = ", ".join(t.value for t in EventType)
        raise HTTPException(status_code=422, detail=f"Invalid event_type '{token}'. Use one of: {valid}") from exc


def _apply_review_updates(event: Event, payload: ReviewDecisionIn) -> None:
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        event.title = title
    if payload.description is not None:
        event.description = payload.description
    if payload.event_type is not None:
        event.event_type = _parse_event_type(payload.event_type)
    if payload.country is not None:
        event.country = payload.country
    if payload.region is not None:
        event.region = payload.region
    if payload.severity is not None:
        if payload.severity < 1 or payload.severity > 5:
            raise HTTPException(status_code=422, detail="severity must be between 1 and 5")
        event.severity = payload.severity
    if payload.confidence_score is not None:
        if payload.confidence_score < 0 or payload.confidence_score > 1:
            raise HTTPException(status_code=422, detail="confidence_score must be between 0 and 1")
        event.confidence_score = payload.confidence_score


def _infer_news_category(article: NewsArticle) -> tuple[str, Optional[str]]:
    text = f"{article.title or ''}\n{article.content or ''}".lower()
    best_category = "general"
    best_hits = 0

    for category, keywords in NEWS_CATEGORY_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits > best_hits:
            best_category = category
            best_hits = hits

    matched_event_type = best_category if best_category in {t.value for t in EventType} else None
    return best_category, matched_event_type


def _to_news_article_out(article: NewsArticle) -> NewsArticleOut:
    category, matched_event_type = _infer_news_category(article)
    snippet = None
    if article.content:
        normalized = " ".join(article.content.split())
        snippet = normalized[:220].rstrip()
        if len(normalized) > 220:
            snippet = f"{snippet}..."

    return NewsArticleOut(
        id=article.id,
        title=article.title,
        source=article.source,
        url=article.url,
        published_at=article.published_at,
        sentiment_score=article.sentiment_score,
        language_code=article.language_code,
        language_confidence=article.language_confidence,
        relevance_score=article.relevance_score,
        relevance_label=article.relevance_label,
        nlp_processed_at=article.nlp_processed_at,
        snippet=snippet,
        category=category,
        matched_event_type=matched_event_type,
        created_at=article.created_at,
    )


def _country_coords(country: str) -> tuple[Optional[float], Optional[float]]:
    coords = COUNTRY_HEATMAP_COORDS.get(country)
    if not coords:
        return None, None
    return coords[0], coords[1]


def _extract_countries_from_text(text: str) -> list[str]:
    normalized = text.lower()
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    for alias, canonical in COUNTRY_ALIASES.items():
        if alias in SHORT_COUNTRY_ALIASES:
            found = re.search(rf"\b{re.escape(alias)}\b", normalized)
            if not found:
                continue
            position = found.start()
        else:
            position = normalized.find(alias)
            if position < 0:
                continue
        if canonical in seen:
            continue
        seen.add(canonical)
        matches.append((position, canonical))
    matches.sort(key=lambda item: item[0])
    return [canonical for _, canonical in matches]


def _estimate_news_severity(article: NewsArticle, category: str) -> float:
    base = NEWS_CATEGORY_SEVERITY.get(category, NEWS_CATEGORY_SEVERITY["general"])
    text = f"{article.title or ''}\n{article.content or ''}".lower()
    intensity = 0.0
    if any(token in text for token in ("war", "missile", "airstrike", "attack", "bombardment", "killed", "kills")):
        intensity += 0.7
    if any(token in text for token in ("sanction", "embargo", "tariff", "export control")):
        intensity += 0.35
    if any(token in text for token in ("refinery", "gas facility", "lng", "pipeline", "oil")):
        intensity += 0.3
    return round(min(5.0, base + intensity), 3)


def _news_heatmap_points(
    articles: list[NewsArticle],
    *,
    requested_event_type: Optional[EventType],
    limit: int,
) -> list[EventHeatmapPointOut]:
    by_country: dict[str, dict[str, float]] = {}
    for article in articles:
        category, matched_event_type = _infer_news_category(article)
        if requested_event_type and matched_event_type != requested_event_type.value:
            continue

        countries = _extract_countries_from_text(f"{article.title or ''}\n{article.content or ''}")
        if not countries:
            continue

        severity = _estimate_news_severity(article, category)
        confidence = article.relevance_score or article.language_confidence or 0.62
        conflict_flag = 1.0 if matched_event_type == EventType.CONFLICT.value else 0.0

        for country in countries:
            bucket = by_country.setdefault(
                country,
                {
                    "event_count": 0.0,
                    "severity_sum": 0.0,
                    "confidence_sum": 0.0,
                    "conflict_count": 0.0,
                },
            )
            bucket["event_count"] += 1.0
            bucket["severity_sum"] += severity
            bucket["confidence_sum"] += float(confidence)
            bucket["conflict_count"] += conflict_flag

    points: list[EventHeatmapPointOut] = []
    for country, bucket in by_country.items():
        count = int(bucket["event_count"])
        if count <= 0:
            continue
        lat, lon = _country_coords(country)
        points.append(
            EventHeatmapPointOut(
                country=country,
                event_count=count,
                avg_severity=round(bucket["severity_sum"] / count, 3),
                avg_confidence=round(bucket["confidence_sum"] / count, 3),
                conflict_share=round(bucket["conflict_count"] / count, 3),
                latitude=lat,
                longitude=lon,
            )
        )

    points.sort(key=lambda row: (row.event_count, row.conflict_share, row.avg_severity), reverse=True)
    return points[:limit]


def _percentile(values: list[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return ordered[rank]


async def _fetch_review_articles(
    db: AsyncSession,
    event_id: uuid.UUID,
    limit: int = 3,
) -> List[ReviewArticleOut]:
    result = await db.execute(
        select(NewsArticle)
        .join(EventArticle, EventArticle.article_id == NewsArticle.id)
        .where(EventArticle.event_id == event_id)
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    articles = result.scalars().all()
    return [
        ReviewArticleOut(
            id=a.id,
            title=a.title,
            source=a.source,
            url=a.url,
            published_at=a.published_at,
        )
        for a in articles
    ]


async def _to_review_out(db: AsyncSession, event: Event) -> EventReviewOut:
    tags_result = await db.execute(select(EventTag.tag).where(EventTag.event_id == event.id).order_by(EventTag.tag.asc()))
    impact_assets_result = await db.execute(
        select(EventImpact, Asset)
        .join(Asset, Asset.id == EventImpact.asset_id)
        .where(EventImpact.event_id == event.id)
        .order_by(EventImpact.confidence_score.desc())
        .limit(8)
    )
    return EventReviewOut(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        country=event.country,
        region=event.region,
        severity=event.severity,
        status=event.status.value,
        confidence_score=event.confidence_score,
        published_at=event.published_at,
        created_at=event.created_at,
        articles=await _fetch_review_articles(db, event.id, limit=3),
        tags=list(tags_result.scalars().all()),
        affected_assets=[
            AffectedAssetOut(
                ticker=asset.ticker,
                name=asset.name,
                impact_direction=impact.impact_direction.value,
                impact_strength=impact.impact_strength,
                confidence_score=impact.confidence_score,
            )
            for impact, asset in impact_assets_result.all()
        ],
    )


def _build_change_payload(payload: ReviewDecisionIn | None) -> Optional[dict]:
    if payload is None:
        return None
    changes = payload.model_dump(exclude_none=True)
    return changes or None


def _log_review_action(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    action: str,
    before_status: Optional[str],
    after_status: Optional[str],
    changes: Optional[dict] = None,
    note: Optional[str] = None,
) -> None:
    db.add(
        EventReviewAction(
            event_id=event_id,
            reviewer_id=reviewer_id,
            action=action,
            before_status=before_status,
            after_status=after_status,
            changes=changes,
            note=note,
        )
    )


async def _snapshot_event_tags(db: AsyncSession, event_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(EventTag.tag).where(EventTag.event_id == event_id).order_by(EventTag.tag.asc())
    )
    return list(result.scalars().all())


async def _snapshot_event_impacts(db: AsyncSession, event_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(EventImpact, Asset)
        .join(Asset, Asset.id == EventImpact.asset_id)
        .where(EventImpact.event_id == event_id)
        .order_by(EventImpact.confidence_score.desc())
    )
    return [
        {
            "ticker": asset.ticker,
            "name": asset.name,
            "impact_direction": impact.impact_direction.value,
            "impact_strength": impact.impact_strength,
            "confidence_score": impact.confidence_score,
        }
        for impact, asset in result.all()
    ]


async def _sync_training_examples(
    db: AsyncSession,
    *,
    event: Event,
    reviewer_id: uuid.UUID,
    review_action: str,
) -> int:
    articles_result = await db.execute(
        select(NewsArticle)
        .join(EventArticle, EventArticle.article_id == NewsArticle.id)
        .where(EventArticle.event_id == event.id)
        .order_by(NewsArticle.published_at.desc())
    )
    articles = articles_result.scalars().all()
    if not articles:
        return 0

    tags = await _snapshot_event_tags(db, event.id)
    affected_assets = await _snapshot_event_impacts(db, event.id)
    label_event_type = event.event_type.value if event.status == EventStatus.HUMAN_APPROVED else None
    label_status = event.status.value

    created = 0
    for article in articles:
        existing = await db.execute(
            select(EventTrainingExample).where(
                EventTrainingExample.event_id == event.id,
                EventTrainingExample.article_id == article.id,
                EventTrainingExample.review_action == review_action,
            )
        )
        row = existing.scalar_one_or_none()
        payload = {
            "reviewer_id": reviewer_id,
            "label_event_type": label_event_type,
            "label_status": label_status,
            "language_code": article.language_code,
            "title": event.title,
            "article_title": article.title,
            "article_content": article.content,
            "source": article.source,
            "url": article.url,
            "country": event.country,
            "region": event.region,
            "severity": event.severity,
            "confidence_score": event.confidence_score,
            "tags": tags,
            "affected_assets": affected_assets,
            "metadata_": {
                "event_source": event.source,
                "event_source_url": event.source_url,
                "article_published_at": article.published_at.isoformat() if article.published_at else None,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        if row:
            for key, value in payload.items():
                setattr(row, key, value)
            continue

        db.add(
            EventTrainingExample(
                event_id=event.id,
                article_id=article.id,
                review_action=review_action,
                **payload,
            )
        )
        created += 1

    return created


@router.get("", response_model=List[EventListOut])
async def list_events(
    event_type: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Free-text topic search"),
    status: Optional[str] = Query("published"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Event)
        .order_by(Event.published_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if status:
        normalized_status = status.lower()
        if normalized_status == "published":
            query = query.where(Event.status.in_(PUBLISHED_EVENT_STATUSES))
        elif normalized_status != "all":
            query = query.where(Event.status == _parse_event_status(status))
    if event_type:
        query = query.where(Event.event_type == _parse_event_type(event_type))
    if country:
        query = query.where(Event.country.ilike(f"%{country}%"))
    if q:
        search_term = q.strip()
        if search_term:
            like_term = f"%{search_term}%"
            asset_event_ids = (
                select(EventImpact.event_id)
                .join(Asset, Asset.id == EventImpact.asset_id)
                .where(
                    or_(
                        Asset.ticker.ilike(like_term),
                        Asset.name.ilike(like_term),
                    )
                )
            )
            tag_event_ids = select(EventTag.event_id).where(EventTag.tag.ilike(like_term))
            query = query.where(
                or_(
                    Event.title.ilike(like_term),
                    Event.description.ilike(like_term),
                    Event.country.ilike(like_term),
                    Event.region.ilike(like_term),
                    Event.source.ilike(like_term),
                    cast(Event.event_type, String).ilike(like_term),
                    Event.id.in_(asset_event_ids),
                    Event.id.in_(tag_event_ids),
                )
            )

    result = await db.execute(query)
    events = result.scalars().all()

    out = []
    for e in events:
        impact_result = await db.execute(
            select(func.count()).where(EventImpact.event_id == e.id)
        )
        impact_assets_result = await db.execute(
            select(EventImpact, Asset)
            .join(Asset, Asset.id == EventImpact.asset_id)
            .where(EventImpact.event_id == e.id)
            .order_by(EventImpact.confidence_score.desc())
            .limit(5)
        )
        affected_assets = [
            AffectedAssetOut(
                ticker=asset.ticker,
                name=asset.name,
                impact_direction=impact.impact_direction.value,
                impact_strength=impact.impact_strength,
                confidence_score=impact.confidence_score,
            )
            for impact, asset in impact_assets_result.all()
        ]
        tags_result = await db.execute(
            select(EventTag.tag)
            .where(EventTag.event_id == e.id)
            .order_by(EventTag.tag.asc())
            .limit(8)
        )
        out.append(
            EventListOut(
                id=e.id,
                title=e.title,
                event_type=e.event_type.value,
                country=e.country,
                severity=e.severity,
                confidence_score=e.confidence_score,
                published_at=e.published_at,
                impact_count=impact_result.scalar() or 0,
                affected_assets=affected_assets,
                tags=list(tags_result.scalars().all()),
            )
        )
    return out


@router.get("/heatmap", response_model=List[EventHeatmapPointOut])
async def event_heatmap(
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(80, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    parsed_event_type = _parse_event_type(event_type) if event_type else None
    query = select(Event).where(
        Event.status.in_(PUBLISHED_EVENT_STATUSES),
        Event.published_at.is_not(None),
        Event.published_at >= since,
        Event.country.is_not(None),
    )
    if parsed_event_type:
        query = query.where(Event.event_type == parsed_event_type)

    result = await db.execute(query.order_by(Event.published_at.desc()))
    events = result.scalars().all()

    by_country: dict[str, dict[str, float]] = {}
    for event in events:
        country = (event.country or "").strip()
        if not country:
            continue
        bucket = by_country.setdefault(
            country,
            {
                "event_count": 0.0,
                "severity_sum": 0.0,
                "severity_count": 0.0,
                "confidence_sum": 0.0,
                "confidence_count": 0.0,
                "conflict_count": 0.0,
            },
        )
        bucket["event_count"] += 1.0
        if event.severity is not None:
            bucket["severity_sum"] += float(event.severity)
            bucket["severity_count"] += 1.0
        if event.confidence_score is not None:
            bucket["confidence_sum"] += float(event.confidence_score)
            bucket["confidence_count"] += 1.0
        if event.event_type == EventType.CONFLICT:
            bucket["conflict_count"] += 1.0

    points: list[EventHeatmapPointOut] = []
    for country, bucket in by_country.items():
        count = int(bucket["event_count"])
        if count <= 0:
            continue
        avg_severity = (bucket["severity_sum"] / bucket["severity_count"]) if bucket["severity_count"] else 0.0
        avg_confidence = (bucket["confidence_sum"] / bucket["confidence_count"]) if bucket["confidence_count"] else 0.0
        conflict_share = bucket["conflict_count"] / float(count)
        lat, lon = _country_coords(country)
        points.append(
            EventHeatmapPointOut(
                country=country,
                event_count=count,
                avg_severity=round(avg_severity, 3),
                avg_confidence=round(avg_confidence, 3),
                conflict_share=round(conflict_share, 3),
                latitude=lat,
                longitude=lon,
            )
        )

    points.sort(key=lambda row: row.event_count, reverse=True)
    if points:
        return points[:limit]

    article_rows = await db.execute(
        select(NewsArticle)
        .where(
            NewsArticle.published_at.is_not(None),
            NewsArticle.published_at >= since,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(max(limit * 6, 120))
    )
    articles = article_rows.scalars().all()
    return _news_heatmap_points(articles, requested_event_type=parsed_event_type, limit=limit)


@router.get("/quality/summary", response_model=QualitySummaryOut)
async def quality_summary(db: AsyncSession = Depends(get_db)):
    total_reviewed_result = await db.execute(
        select(func.count()).where(EventTrainingExample.review_action.in_(("approve", "reject")))
    )
    approved_result = await db.execute(
        select(func.count()).where(EventTrainingExample.review_action == "approve")
    )
    total_reviewed = int(total_reviewed_result.scalar() or 0)
    approved = int(approved_result.scalar() or 0)
    classification_accuracy = (approved / total_reviewed) if total_reviewed else None

    latency_rows = await db.execute(
        select(NewsArticle.created_at, NewsArticle.nlp_processed_at)
        .where(NewsArticle.nlp_processed_at.is_not(None))
        .order_by(NewsArticle.nlp_processed_at.desc())
        .limit(2000)
    )
    latency_values = [
        max(0.0, (processed_at - created_at).total_seconds())
        for created_at, processed_at in latency_rows.all()
        if created_at is not None and processed_at is not None
    ]
    nlp_latency_p95 = _percentile(latency_values, 0.95)

    total_events_result = await db.execute(select(func.count()).select_from(Event))
    auto_approved_result = await db.execute(
        select(func.count()).where(Event.status == EventStatus.AUTO_APPROVED)
    )
    total_events = int(total_events_result.scalar() or 0)
    auto_approved = int(auto_approved_result.scalar() or 0)
    auto_approved_rate = (auto_approved / total_events) if total_events else None

    backlog_result = await db.execute(
        select(func.count()).where(Event.status == EventStatus.PENDING_REVIEW)
    )
    review_backlog = int(backlog_result.scalar() or 0)

    latest_news_result = await db.execute(
        select(NewsArticle.created_at).order_by(NewsArticle.created_at.desc()).limit(1)
    )
    latest_news_created_at = latest_news_result.scalar_one_or_none()
    freshness_minutes: Optional[float] = None
    if latest_news_created_at is not None:
        freshness_minutes = max(
            0.0,
            (datetime.now(timezone.utc) - latest_news_created_at).total_seconds() / 60.0,
        )

    published_events_result = await db.execute(
        select(func.count())
        .select_from(Event)
        .where(Event.status.in_(PUBLISHED_EVENT_STATUSES))
    )
    mapped_events_result = await db.execute(
        select(func.count(func.distinct(EventImpact.event_id)))
        .join(Event, Event.id == EventImpact.event_id)
        .where(Event.status.in_(PUBLISHED_EVENT_STATUSES))
    )
    published_events = int(published_events_result.scalar() or 0)
    mapped_events = int(mapped_events_result.scalar() or 0)
    asset_mapping_coverage = (mapped_events / published_events) if published_events else None

    return QualitySummaryOut(
        classification_accuracy=round(classification_accuracy, 4) if classification_accuracy is not None else None,
        nlp_latency_p95_seconds=round(float(nlp_latency_p95), 2) if nlp_latency_p95 is not None else None,
        auto_approved_rate=round(auto_approved_rate, 4) if auto_approved_rate is not None else None,
        review_queue_backlog=review_backlog,
        news_ingestion_freshness_minutes=round(freshness_minutes, 2) if freshness_minutes is not None else None,
        asset_mapping_coverage=round(asset_mapping_coverage, 4) if asset_mapping_coverage is not None else None,
    )


@router.get("/review/weekly-progress", response_model=WeeklyReviewProgressOut)
async def review_weekly_progress(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    reviewed_count_result = await db.execute(
        select(func.count(func.distinct(EventReviewAction.event_id))).where(
            EventReviewAction.action.in_(("approve", "reject")),
            EventReviewAction.created_at >= week_start,
            EventReviewAction.created_at < week_end,
        )
    )
    reviewed_count = int(reviewed_count_result.scalar() or 0)
    return WeeklyReviewProgressOut(
        week_start_utc=week_start,
        week_end_utc=week_end,
        reviewed_events=reviewed_count,
        target_met=50 <= reviewed_count <= 100,
    )


@router.get("/review/pending", response_model=List[EventReviewOut])
async def list_pending_review_events(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    result = await db.execute(
        select(Event)
        .where(Event.status == EventStatus.PENDING_REVIEW)
        .order_by(Event.published_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()
    return [await _to_review_out(db, event) for event in events]


@router.patch("/review/{event_id}", response_model=EventReviewOut)
async def edit_pending_event(
    event_id: uuid.UUID,
    payload: ReviewDecisionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    before_status = event.status.value
    change_payload = _build_change_payload(payload)
    _apply_review_updates(event, payload)
    _log_review_action(
        db,
        event_id=event.id,
        reviewer_id=current_user.id,
        action="edit",
        before_status=before_status,
        after_status=event.status.value,
        changes=change_payload,
    )
    await db.flush()
    await db.refresh(event)
    return await _to_review_out(db, event)


@router.post("/review/{event_id}/approve", response_model=ReviewActionOut)
async def approve_event(
    event_id: uuid.UUID,
    payload: ReviewDecisionIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    before_status = event.status.value
    change_payload = _build_change_payload(payload)
    if payload:
        _apply_review_updates(event, payload)

    event.status = EventStatus.HUMAN_APPROVED
    _log_review_action(
        db,
        event_id=event.id,
        reviewer_id=current_user.id,
        action="approve",
        before_status=before_status,
        after_status=event.status.value,
        changes=change_payload,
    )
    await _sync_training_examples(
        db,
        event=event,
        reviewer_id=current_user.id,
        review_action="approve",
    )
    await db.flush()
    return ReviewActionOut(
        id=event.id,
        status=event.status.value,
        message="Event approved and moved to HUMAN_APPROVED",
    )


@router.post("/review/{event_id}/reject", response_model=ReviewActionOut)
async def reject_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    before_status = event.status.value
    event.status = EventStatus.REJECTED
    _log_review_action(
        db,
        event_id=event.id,
        reviewer_id=current_user.id,
        action="reject",
        before_status=before_status,
        after_status=event.status.value,
    )
    await _sync_training_examples(
        db,
        event=event,
        reviewer_id=current_user.id,
        review_action="reject",
    )
    await db.flush()
    return ReviewActionOut(
        id=event.id,
        status=event.status.value,
        message="Event rejected",
    )


@router.get("/review/{event_id}/history", response_model=List[ReviewHistoryOut])
async def review_history(
    event_id: uuid.UUID,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    result = await db.execute(
        select(EventReviewAction)
        .where(EventReviewAction.event_id == event_id)
        .order_by(EventReviewAction.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/review/training-examples", response_model=List[TrainingExampleOut])
async def list_training_examples(
    label_status: Optional[str] = Query(None),
    label_event_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    query = (
        select(EventTrainingExample)
        .order_by(EventTrainingExample.created_at.desc())
        .limit(limit)
    )
    if label_status:
        query = query.where(EventTrainingExample.label_status == label_status)
    if label_event_type:
        query = query.where(EventTrainingExample.label_event_type == _parse_event_type(label_event_type).value)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    tag_result = await db.execute(select(EventTag).where(EventTag.event_id == event_id))
    tags = [t.tag for t in tag_result.scalars().all()]

    impact_result = await db.execute(
        select(EventImpact, Asset)
        .join(Asset, Asset.id == EventImpact.asset_id)
        .where(EventImpact.event_id == event_id)
        .order_by(EventImpact.confidence_score.desc())
    )
    impacts = [
        EventImpactOut(
            id=impact.id,
            asset_id=impact.asset_id,
            impact_direction=impact.impact_direction.value,
            impact_strength=impact.impact_strength,
            confidence_score=impact.confidence_score,
            ticker=asset.ticker,
            name=asset.name,
        )
        for impact, asset in impact_result.all()
    ]

    return EventOut(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        country=event.country,
        region=event.region,
        severity=event.severity,
        status=event.status.value,
        confidence_score=event.confidence_score,
        published_at=event.published_at,
        created_at=event.created_at,
        tags=tags,
        impacts=impacts,
    )


@news_router.get("", response_model=List[NewsArticleOut])
async def list_news(
    q: Optional[str] = Query(None, description="Free-text topic search"),
    category: Optional[str] = Query(None, description="Derived article category"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    query = select(NewsArticle).order_by(NewsArticle.published_at.desc())
    if q:
        search_term = q.strip()
        if search_term:
            like_term = f"%{search_term}%"
            query = query.where(
                or_(
                    NewsArticle.title.ilike(like_term),
                    NewsArticle.content.ilike(like_term),
                    NewsArticle.source.ilike(like_term),
                    NewsArticle.url.ilike(like_term),
                )
            )
    result = await db.execute(query)
    articles = result.scalars().all()
    items = [_to_news_article_out(article) for article in articles]
    if category:
        normalized_category = category.strip().lower().replace(" ", "_")
        items = [item for item in items if item.category == normalized_category]
    return items[offset : offset + limit]
