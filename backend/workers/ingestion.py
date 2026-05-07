"""
News ingestion Celery tasks.
Fetches articles from NewsAPI, GDELT, and RSS feeds.
Deduplicates via SHA256 hash.
Stores to news_articles table.
"""
import hashlib
import html
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

import feedparser
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from workers.celery_app import celery_app
from core.config import settings
from modules.market.models import Asset

logger = logging.getLogger(__name__)

SEC_CIK_BY_TICKER = {
    "NVDA": 1045810,
    "AMD": 2488,
    "TSM": 1046179,
    "XOM": 34088,
    "CVX": 93410,
}
SEC_FORMS = {"10-K", "20-F"}
SUPPLIER_TERMS = ("supplier", "suppliers", "supply chain", "sourced from", "procured from")
CUSTOMER_TERMS = ("customer", "customers", "revenue from", "sales to", "major customer")

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_hash(title: str, description: str) -> str:
    raw = f"{title}::{description}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _store_articles(articles: list[dict]) -> int:
    """Synchronously store articles using a sync DB session (Celery is sync)."""
    from modules.events.models import NewsArticle

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    stored = 0
    with Session(engine) as session:
        for article in articles:
            content_hash = article.get("content_hash")
            if not content_hash:
                continue
            existing = session.execute(
                select(NewsArticle).where(NewsArticle.content_hash == content_hash)
            ).scalar_one_or_none()
            if existing:
                continue
            news = NewsArticle(
                title=article["title"],
                content=article.get("content"),
                source=article["source"],
                url=article["url"],
                published_at=article.get("published_at"),
                content_hash=content_hash,
            )
            session.add(news)
            stored += 1
        session.commit()
    if stored > 0:
        # Push newly ingested items into the processing queue immediately.
        celery_app.send_task(
            "workers.event_pipeline.process_unprocessed_articles",
            kwargs={"batch_size": 200},
        )
    return stored


def _kg_safe_metadata(existing: Optional[dict], patch: Optional[dict]) -> Optional[dict]:
    if not patch:
        return existing
    out = dict(existing or {})
    for key, value in patch.items():
        if value is not None:
            out[key] = value
    return out


def _kg_get_or_create_entity(session, entity_type: str, name: str, metadata: Optional[dict] = None):
    from modules.knowledge_graph.models import KGEntity

    entity = session.execute(
        select(KGEntity).where(KGEntity.entity_type == entity_type, KGEntity.name == name)
    ).scalar_one_or_none()
    if entity:
        entity.metadata_ = _kg_safe_metadata(entity.metadata_, metadata)
        return entity, False

    entity = KGEntity(entity_type=entity_type, name=name, metadata_=metadata or {})
    session.add(entity)
    session.flush()
    return entity, True


def _kg_upsert_relationship(
    session,
    source_id,
    target_id,
    relationship: str,
    data_source: str,
    strength: Optional[float] = None,
    last_verified: Optional[date] = None,
) -> bool:
    from modules.knowledge_graph.models import KGRelationship

    edge = session.execute(
        select(KGRelationship).where(
            KGRelationship.source_id == source_id,
            KGRelationship.target_id == target_id,
            KGRelationship.relationship == relationship,
            KGRelationship.data_source == data_source,
        )
    ).scalar_one_or_none()
    if edge:
        edge.strength = strength
        edge.last_verified = last_verified
        return False

    session.add(
        KGRelationship(
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            strength=strength,
            data_source=data_source,
            last_verified=last_verified,
        )
    )
    return True


def _kg_seed_baseline_assets(session) -> tuple[dict[str, object], int, int]:
    assets = session.execute(select(Asset)).scalars().all()
    entity_by_ticker: dict[str, object] = {}
    created_entities = 0
    created_relationships = 0

    for asset in assets:
        ticker = asset.ticker.upper()
        asset_entity, created = _kg_get_or_create_entity(
            session,
            "ASSET",
            ticker,
            metadata={
                "display_name": asset.name,
                "asset_type": asset.asset_type.value,
                "exchange": asset.exchange,
                "currency": asset.currency,
            },
        )
        created_entities += 1 if created else 0
        entity_by_ticker[ticker] = asset_entity

        if asset.sector:
            sector_entity, created = _kg_get_or_create_entity(
                session, "SECTOR", asset.sector, metadata={"source": "assets_table"}
            )
            created_entities += 1 if created else 0
            if _kg_upsert_relationship(
                session,
                source_id=asset_entity.id,
                target_id=sector_entity.id,
                relationship="PART_OF",
                data_source="MANUAL",
                strength=0.9,
            ):
                created_relationships += 1

        if asset.country:
            country_entity, created = _kg_get_or_create_entity(
                session, "COUNTRY", asset.country, metadata={"source": "assets_table"}
            )
            created_entities += 1 if created else 0
            if _kg_upsert_relationship(
                session,
                source_id=asset_entity.id,
                target_id=country_entity.id,
                relationship="PART_OF",
                data_source="MANUAL",
                strength=0.9,
            ):
                created_relationships += 1

    return entity_by_ticker, created_entities, created_relationships


def _kg_fetch_wikidata_profiles(tickers: list[str], user_agent: str) -> list[dict]:
    if not tickers:
        return []
    ticker_values = " ".join(f'"{ticker}"' for ticker in sorted(set(tickers)))
    query = f"""
SELECT ?ticker ?companyLabel ?industryLabel ?countryLabel WHERE {{
  VALUES ?ticker {{ {ticker_values} }}
  ?company wdt:P249 ?ticker .
  OPTIONAL {{ ?company wdt:P452 ?industry . }}
  OPTIONAL {{ ?company wdt:P17 ?country . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 500
"""
    headers = {"Accept": "application/sparql-results+json", "User-Agent": user_agent}
    with httpx.Client(timeout=30, headers=headers) as client:
        response = client.get(settings.WIKIDATA_SPARQL_URL, params={"query": query, "format": "json"})
        response.raise_for_status()
        payload = response.json()

    rows = payload.get("results", {}).get("bindings", [])
    return [
        {
            "ticker": row.get("ticker", {}).get("value", "").upper(),
            "company_label": row.get("companyLabel", {}).get("value"),
            "industry_label": row.get("industryLabel", {}).get("value"),
            "country_label": row.get("countryLabel", {}).get("value"),
        }
        for row in rows
    ]


def _kg_apply_wikidata(session, entity_by_ticker: dict[str, object], rows: list[dict]) -> tuple[int, int]:
    created_entities = 0
    created_relationships = 0
    for row in rows:
        ticker = row.get("ticker")
        if not ticker:
            continue
        company = entity_by_ticker.get(ticker)
        if company is None:
            company, created = _kg_get_or_create_entity(
                session,
                "ASSET",
                ticker,
                metadata={"display_name": row.get("company_label"), "source": "wikidata"},
            )
            created_entities += 1 if created else 0
            entity_by_ticker[ticker] = company
        else:
            company.metadata_ = _kg_safe_metadata(
                company.metadata_, {"display_name": row.get("company_label"), "source": "wikidata"}
            )

        industry = row.get("industry_label")
        if industry:
            industry_entity, created = _kg_get_or_create_entity(
                session, "SECTOR", industry, metadata={"source": "wikidata"}
            )
            created_entities += 1 if created else 0
            if _kg_upsert_relationship(
                session,
                source_id=company.id,
                target_id=industry_entity.id,
                relationship="PART_OF",
                data_source="WIKIDATA",
                strength=0.78,
            ):
                created_relationships += 1

        country = row.get("country_label")
        if country:
            country_entity, created = _kg_get_or_create_entity(
                session, "COUNTRY", country, metadata={"source": "wikidata"}
            )
            created_entities += 1 if created else 0
            if _kg_upsert_relationship(
                session,
                source_id=company.id,
                target_id=country_entity.id,
                relationship="PART_OF",
                data_source="WIKIDATA",
                strength=0.86,
            ):
                created_relationships += 1

    return created_entities, created_relationships


def _kg_normalize_filing_text(raw_text: str) -> str:
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_text)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _kg_extract_sec_edges(source_ticker: str, text: str, aliases: dict[str, list[str]]) -> dict[tuple[str, str], int]:
    edges: dict[tuple[str, str], int] = {}
    for target_ticker, target_aliases in aliases.items():
        if target_ticker == source_ticker:
            continue
        for alias in target_aliases:
            token = alias.strip().lower()
            if not token:
                continue
            start = 0
            while True:
                idx = text.find(token, start)
                if idx == -1:
                    break
                window = text[max(0, idx - 180): min(len(text), idx + len(token) + 180)]
                if any(term in window for term in SUPPLIER_TERMS):
                    edges[(target_ticker, source_ticker)] = edges.get((target_ticker, source_ticker), 0) + 1
                if any(term in window for term in CUSTOMER_TERMS):
                    edges[(source_ticker, target_ticker)] = edges.get((source_ticker, target_ticker), 0) + 1
                start = idx + len(token)
    return edges


def _kg_fetch_sec_latest_10k(client: httpx.Client, cik: int) -> tuple[Optional[str], Optional[date]]:
    cik_padded = f"{cik:010d}"
    try:
        response = client.get(f"{settings.SEC_EDGAR_BASE_URL}/submissions/CIK{cik_padded}.json")
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None, None

    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    for form, accession, doc, filing_date in zip(forms, accessions, docs, dates):
        if form not in SEC_FORMS or not accession or not doc:
            continue
        cik_int = str(int(cik_padded))
        accession_no_dash = accession.replace("-", "")
        url = f"{settings.SEC_ARCHIVES_BASE_URL}/edgar/data/{cik_int}/{accession_no_dash}/{doc}"
        try:
            parsed_date = datetime.strptime(filing_date, "%Y-%m-%d").date() if filing_date else None
        except ValueError:
            parsed_date = None
        return url, parsed_date
    return None, None


def _kg_apply_sec(session, entity_by_ticker: dict[str, object], user_agent: str) -> tuple[int, int, int]:
    assets = session.execute(select(Asset.ticker, Asset.name)).all()
    aliases: dict[str, list[str]] = {}
    for ticker, name in assets:
        tokens = [ticker.lower()]
        if name:
            tokens.extend(
                candidate.strip().lower()
                for candidate in (name, name.replace("Corp", "").replace("Corporation", ""))
                if candidate and candidate.strip()
            )
        aliases[ticker.upper()] = list(dict.fromkeys(tokens))

    filings_scanned = 0
    rels_created = 0
    mention_count = 0
    headers = {"User-Agent": user_agent, "Accept": "application/json,text/html"}
    with httpx.Client(timeout=35, headers=headers) as client:
        for ticker, cik in SEC_CIK_BY_TICKER.items():
            source_entity = entity_by_ticker.get(ticker)
            if source_entity is None:
                continue
            filing_url, verified_date = _kg_fetch_sec_latest_10k(client, cik)
            if not filing_url:
                continue
            try:
                filing_resp = client.get(filing_url)
                filing_resp.raise_for_status()
                filing_text = filing_resp.text
            except Exception:
                continue

            filings_scanned += 1
            edges = _kg_extract_sec_edges(
                source_ticker=ticker,
                text=_kg_normalize_filing_text(filing_text),
                aliases=aliases,
            )
            for (src_ticker, dst_ticker), count in edges.items():
                src_entity = entity_by_ticker.get(src_ticker)
                dst_entity = entity_by_ticker.get(dst_ticker)
                if not src_entity or not dst_entity:
                    continue
                mention_count += count
                if _kg_upsert_relationship(
                    session,
                    source_id=src_entity.id,
                    target_id=dst_entity.id,
                    relationship="SUPPLIES_TO",
                    data_source="SEC_FILING",
                    strength=round(min(0.95, 0.45 + 0.08 * count), 4),
                    last_verified=verified_date,
                ):
                    rels_created += 1

    return filings_scanned, rels_created, mention_count


# ─── NewsAPI ─────────────────────────────────────────────────────────────────

@celery_app.task(name="workers.ingestion.fetch_newsapi", bind=True, max_retries=3)
def fetch_newsapi(self):
    if not settings.NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not set, skipping NewsAPI fetch")
        return {"skipped": True, "reason": "no api key"}

    categories = ["business", "politics", "world"]
    articles = []

    with httpx.Client(timeout=30) as client:
        for category in categories:
            try:
                resp = client.get(
                    "https://newsapi.org/v2/top-headlines",
                    params={"category": category, "language": "en", "pageSize": 50, "apiKey": settings.NEWS_API_KEY},
                )
                resp.raise_for_status()
                for a in resp.json().get("articles", []):
                    title = a.get("title") or ""
                    description = a.get("description") or ""
                    if not title or title == "[Removed]":
                        continue
                    articles.append({
                        "title": title[:500],
                        "content": a.get("content"),
                        "source": a.get("source", {}).get("name", "NewsAPI"),
                        "url": a.get("url", ""),
                        "published_at": _parse_dt(a.get("publishedAt")),
                        "content_hash": _make_hash(title, description),
                    })
            except Exception as exc:
                logger.error(f"NewsAPI error for category {category}: {exc}")

    stored = _store_articles(articles)
    logger.info(f"NewsAPI: fetched {len(articles)}, stored {stored} new articles")
    return {"fetched": len(articles), "stored": stored}


# ─── GDELT ───────────────────────────────────────────────────────────────────

@celery_app.task(name="workers.ingestion.fetch_gdelt", bind=True, max_retries=3)
def fetch_gdelt(self):
    """Fetch geopolitical events from GDELT API v2."""
    articles = []
    keywords = "geopolitics OR sanctions OR conflict OR 'trade war' OR military"

    with httpx.Client(timeout=30) as client:
        try:
            resp = client.get(
                settings.GDELT_BASE_URL,
                params={
                    "query": keywords,
                    "mode": "artlist",
                    "maxrecords": 75,
                    "format": "json",
                    "sort": "datedesc",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            for a in data.get("articles", []):
                title = a.get("title") or ""
                if not title:
                    continue
                articles.append({
                    "title": title[:500],
                    "content": None,
                    "source": a.get("domain", "GDELT"),
                    "url": a.get("url", ""),
                    "published_at": _parse_dt(a.get("seendate")),
                    "content_hash": _make_hash(title, a.get("url", "")),
                })
        except Exception as exc:
            logger.error(f"GDELT fetch error: {exc}")

    stored = _store_articles(articles)
    logger.info(f"GDELT: fetched {len(articles)}, stored {stored} new articles")
    return {"fetched": len(articles), "stored": stored}


# ─── EventRegistry ────────────────────────────────────────────────────────────

@celery_app.task(name="workers.ingestion.fetch_eventregistry", bind=True, max_retries=3)
def fetch_eventregistry(self):
    if not settings.EVENTREGISTRY_API_KEY:
        logger.warning("EVENTREGISTRY_API_KEY not set, skipping EventRegistry fetch")
        return {"skipped": True, "reason": "no api key"}

    articles = []
    payload = {
        "apiKey": settings.EVENTREGISTRY_API_KEY,
        "resultType": "articles",
        "articlesCount": 100,
        "articlesSortBy": "date",
        "articlesSortByAsc": False,
        "query": {
            "$query": {
                "$and": [
                    {"lang": "eng"},
                    {
                        "$or": [
                            {"keyword": "geopolitics"},
                            {"keyword": "sanctions"},
                            {"keyword": "trade policy"},
                            {"keyword": "conflict"},
                            {"keyword": "energy disruption"},
                            {"keyword": "election"},
                            {"keyword": "regulation"},
                        ]
                    },
                ]
            }
        },
    }

    with httpx.Client(timeout=45) as client:
        try:
            resp = client.post(settings.EVENTREGISTRY_BASE_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            rows = (
                data.get("articles", {}).get("results")
                or data.get("articles", {}).get("articles")
                or data.get("results")
                or []
            )
            for a in rows:
                title = (a.get("title") or "").strip()
                body = (a.get("body") or a.get("content") or "")
                url = a.get("url") or ""
                if not title or not url:
                    continue
                source_title = (
                    (a.get("source", {}) or {}).get("title")
                    if isinstance(a.get("source"), dict)
                    else a.get("source")
                ) or "EventRegistry"
                articles.append(
                    {
                        "title": title[:500],
                        "content": body[:5000] if body else None,
                        "source": str(source_title)[:100],
                        "url": url,
                        "published_at": _parse_dt(a.get("dateTimePub") or a.get("dateTime")),
                        "content_hash": _make_hash(title, body or url),
                    }
                )
        except Exception as exc:
            logger.error(f"EventRegistry fetch error: {exc}")

    stored = _store_articles(articles)
    logger.info(f"EventRegistry: fetched {len(articles)}, stored {stored} new articles")
    return {"fetched": len(articles), "stored": stored}


# ─── Mediastack ───────────────────────────────────────────────────────────────

@celery_app.task(name="workers.ingestion.fetch_mediastack", bind=True, max_retries=3)
def fetch_mediastack(self):
    if not settings.MEDIASTACK_API_KEY:
        logger.warning("MEDIASTACK_API_KEY not set, skipping Mediastack fetch")
        return {"skipped": True, "reason": "no api key"}

    articles = []
    query_terms = "geopolitics,sanctions,trade,conflict,election,energy,regulation"

    with httpx.Client(timeout=45) as client:
        try:
            resp = client.get(
                settings.MEDIASTACK_BASE_URL,
                params={
                    "access_key": settings.MEDIASTACK_API_KEY,
                    "languages": "en",
                    "limit": 100,
                    "sort": "published_desc",
                    "keywords": query_terms,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data") or []
            for a in rows:
                title = (a.get("title") or "").strip()
                description = (a.get("description") or "").strip()
                url = a.get("url") or ""
                if not title or not url:
                    continue
                articles.append(
                    {
                        "title": title[:500],
                        "content": (a.get("content") or description or None),
                        "source": str(a.get("source") or "Mediastack")[:100],
                        "url": url,
                        "published_at": _parse_dt(a.get("published_at")),
                        "content_hash": _make_hash(title, description or url),
                    }
                )
        except Exception as exc:
            logger.error(f"Mediastack fetch error: {exc}")

    stored = _store_articles(articles)
    logger.info(f"Mediastack: fetched {len(articles)}, stored {stored} new articles")
    return {"fetched": len(articles), "stored": stored}


# ─── Knowledge Graph Seeding ──────────────────────────────────────────────────

@celery_app.task(name="workers.ingestion.seed_knowledge_graph", bind=True, max_retries=2)
def seed_knowledge_graph(self):
    """
    Seed KG entities/relationships from:
    - assets baseline (ASSET/SECTOR/COUNTRY entities + PART_OF edges)
    - Wikidata SPARQL (industry + country)
    - SEC EDGAR 10-K/20-F text heuristics (SUPPLIES_TO edges)
    """
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

    entities_created = 0
    relationships_created = 0
    wikidata_rows = 0
    sec_filings_scanned = 0
    sec_mentions = 0

    with Session(engine) as session:
        entity_by_ticker, baseline_entities, baseline_rels = _kg_seed_baseline_assets(session)
        entities_created += baseline_entities
        relationships_created += baseline_rels

        try:
            wikidata_rows_data = _kg_fetch_wikidata_profiles(
                list(entity_by_ticker.keys()),
                user_agent=settings.SEC_EDGAR_USER_AGENT,
            )
            wikidata_rows = len(wikidata_rows_data)
            wd_entities, wd_rels = _kg_apply_wikidata(
                session=session,
                entity_by_ticker=entity_by_ticker,
                rows=wikidata_rows_data,
            )
            entities_created += wd_entities
            relationships_created += wd_rels
        except Exception as exc:
            logger.warning("Wikidata KG seeding skipped due to error: %s", exc)

        try:
            sec_filings_scanned, sec_rels, sec_mentions = _kg_apply_sec(
                session=session,
                entity_by_ticker=entity_by_ticker,
                user_agent=settings.SEC_EDGAR_USER_AGENT,
            )
            relationships_created += sec_rels
        except Exception as exc:
            logger.warning("SEC KG seeding skipped due to error: %s", exc)

        session.commit()

    result = {
        "entities_created_or_updated": entities_created,
        "relationships_created_or_updated": relationships_created,
        "wikidata_rows": wikidata_rows,
        "sec_filings_scanned": sec_filings_scanned,
        "sec_mentions": sec_mentions,
    }
    logger.info("Knowledge graph seed complete: %s", result)
    return result


# ─── RSS ─────────────────────────────────────────────────────────────────────

@celery_app.task(name="workers.ingestion.fetch_rss", bind=True, max_retries=3)
def fetch_rss(self, feed_url: str):
    """Generic RSS feed parser."""
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        source_name = feed.feed.get("title", feed_url)
        for entry in feed.entries[:50]:
            title = entry.get("title") or ""
            summary = entry.get("summary") or ""
            if not title:
                continue
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import time
                published = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
            articles.append({
                "title": title[:500],
                "content": summary[:5000] if summary else None,
                "source": source_name[:100],
                "url": entry.get("link", ""),
                "published_at": published,
                "content_hash": _make_hash(title, summary),
            })
    except Exception as exc:
        logger.error(f"RSS fetch error for {feed_url}: {exc}")

    stored = _store_articles(articles)
    logger.info(f"RSS {feed_url}: fetched {len(articles)}, stored {stored} new articles")
    return {"feed": feed_url, "fetched": len(articles), "stored": stored}


# ─── Util ────────────────────────────────────────────────────────────────────

def _parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%dT%H%M%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
