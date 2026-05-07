from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import NewsArticle


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _day_key(value: str | None) -> str | None:
    if not value:
        return None
    try:
        if 'T' in value:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
        return datetime.fromisoformat(value).date().isoformat()
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--gdelt', default='tmp/phase2/historical.combined.jsonl')
    parser.add_argument('--output', default='tmp/phase2/reuters_ap_gdelt_pairs.jsonl')
    parser.add_argument('--max-pairs', type=int, default=20000)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    gdelt_path = Path(args.gdelt)
    if not gdelt_path.is_absolute():
        gdelt_path = root / gdelt_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hist = _load_jsonl(gdelt_path)
    gdelt_by_day: dict[str, list[dict]] = defaultdict(list)
    for row in hist:
        day = _day_key(row.get('published_at') or row.get('event_date'))
        if day:
            gdelt_by_day[day].append(row)

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    with Session(engine) as session:
        articles = session.execute(
            select(NewsArticle)
            .where((NewsArticle.source.ilike('%reuters%')) | (NewsArticle.source.ilike('%ap%')))
            .order_by(NewsArticle.published_at.desc())
            .limit(args.max_pairs)
        ).scalars().all()

    written = 0
    with out_path.open('w', encoding='utf-8') as handle:
        # Direct Reuters slice from historical GDELT provenance.
        for row in hist:
            if written >= args.max_pairs:
                break
            if str(row.get('provider', '')).lower() != 'reuters':
                continue
            payload = {
                'pair_id': f"reuters-{row.get('canonical_id')}",
                'provider': 'reuters',
                'article_title': row.get('title'),
                'article_text': row.get('description'),
                'article_published_at': row.get('published_at'),
                'gdelt_event_id': row.get('provider_record_id') or row.get('canonical_id'),
                'gdelt_event_type': row.get('event_type'),
                'gdelt_event_date': row.get('event_date'),
                'gdelt_country': row.get('country'),
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + '\n')
            written += 1

        # AP/Reuters live-article pairing against normalized historical GDELT events by day.
        for article in articles:
            if written >= args.max_pairs:
                break
            day = article.published_at.date().isoformat() if article.published_at else None
            if not day:
                continue
            candidates = gdelt_by_day.get(day, [])
            if not candidates:
                continue
            candidate = candidates[0]
            payload = {
                'pair_id': f"news-{article.id}",
                'provider': article.source,
                'article_title': article.title,
                'article_text': article.content,
                'article_published_at': article.published_at.isoformat() if article.published_at else None,
                'gdelt_event_id': candidate.get('provider_record_id') or candidate.get('canonical_id'),
                'gdelt_event_type': candidate.get('event_type'),
                'gdelt_event_date': candidate.get('event_date'),
                'gdelt_country': candidate.get('country'),
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + '\n')
            written += 1

    print(json.dumps({'output': str(out_path), 'pairs_written': written}, ensure_ascii=True))


if __name__ == '__main__':
    main()
