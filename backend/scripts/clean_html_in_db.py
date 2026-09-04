"""Strip leftover feed markup from rows ingested before HTML was cleaned on write.

Articles fetched prior to the ingestion fix hold raw `<a href=...>` / `<p>`
payloads in `news_articles.content`, which propagated into `events.description`.
The read paths now strip defensively, but this rewrites the stored text so the
data itself is clean.

    python -m scripts.clean_html_in_db                # rewrite markup in place
    python -m scripts.clean_html_in_db --dry-run      # report only, change nothing
    python -m scripts.clean_html_in_db --purge-feed   # also DELETE the retired
                                                      # google "breaking news" rows

Run from the `backend/` directory.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from core.config import settings
from core.text import clean_feed_text, strip_html
from modules.events.models import Event, EventArticle, NewsArticle

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("clean_html_in_db")

# feedparser names an RSS source after the feed's <title>; this is what the
# retired `q=breaking+news` Google News search feed reported itself as.
RETIRED_FEED_SOURCES = ('"breaking news" - Google News',)

_HTML_LIKE = "%<%>%"


def _looks_like_markup(value: str | None) -> bool:
    return bool(value) and strip_html(value) != value


def clean_articles(session: Session, *, dry_run: bool) -> int:
    """Rewrite news_articles.title/content that still carry markup."""
    rows = session.execute(
        select(NewsArticle).where(
            NewsArticle.title.like(_HTML_LIKE) | NewsArticle.content.like(_HTML_LIKE)
        )
    ).scalars().all()

    changed = 0
    for article in rows:
        new_title = (clean_feed_text(article.title) or article.title)[:500]
        new_content = clean_feed_text(article.content)
        if new_content and len(new_content) > 5000:
            new_content = new_content[:5000]
        if new_title == article.title and new_content == article.content:
            continue
        changed += 1
        if dry_run:
            logger.info("would clean article %s: %s", article.id, new_title[:90])
            continue
        article.title = new_title
        article.content = new_content
    return changed


def clean_events(session: Session, *, dry_run: bool) -> int:
    """Rewrite events.title/description copied from pre-fix article content."""
    rows = session.execute(
        select(Event).where(
            Event.title.like(_HTML_LIKE) | Event.description.like(_HTML_LIKE)
        )
    ).scalars().all()

    changed = 0
    for event in rows:
        new_title = (clean_feed_text(event.title) or event.title)[:500]
        new_description = clean_feed_text(event.description)
        if new_description and len(new_description) > 2000:
            new_description = new_description[:2000]
        if new_title == event.title and new_description == event.description:
            continue
        changed += 1
        if dry_run:
            logger.info("would clean event %s: %s", event.id, new_title[:90])
            continue
        event.title = new_title
        event.description = new_description
    return changed


def purge_retired_feed(session: Session, *, dry_run: bool) -> tuple[int, int]:
    """Delete articles from the retired feed, plus events left with no articles."""
    articles = session.execute(
        select(NewsArticle).where(NewsArticle.source.in_(RETIRED_FEED_SOURCES))
    ).scalars().all()

    if dry_run:
        for article in articles:
            logger.info("would delete article %s: %s", article.id, article.title[:90])

    orphaned_events = 0
    if not dry_run and articles:
        article_ids = [article.id for article in articles]
        # Events whose *only* sources are the articles about to disappear would
        # otherwise linger with an empty citation list.
        candidate_event_ids = session.execute(
            select(EventArticle.event_id)
            .where(EventArticle.article_id.in_(article_ids))
            .distinct()
        ).scalars().all()

        session.execute(delete(NewsArticle).where(NewsArticle.id.in_(article_ids)))
        session.flush()

        for event_id in candidate_event_ids:
            remaining = session.execute(
                select(func.count())
                .select_from(EventArticle)
                .where(EventArticle.event_id == event_id)
            ).scalar() or 0
            if remaining == 0:
                session.execute(delete(Event).where(Event.id == event_id))
                orphaned_events += 1

    return len(articles), orphaned_events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    parser.add_argument(
        "--purge-feed",
        action="store_true",
        help="also delete articles from the retired google 'breaking news' feed",
    )
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    with Session(engine) as session:
        articles_changed = clean_articles(session, dry_run=args.dry_run)
        events_changed = clean_events(session, dry_run=args.dry_run)

        purged_articles = purged_events = 0
        if args.purge_feed:
            purged_articles, purged_events = purge_retired_feed(session, dry_run=args.dry_run)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    verb = "would clean" if args.dry_run else "cleaned"
    logger.info("%s %d articles, %d events", verb, articles_changed, events_changed)
    if args.purge_feed:
        verb = "would delete" if args.dry_run else "deleted"
        logger.info("%s %d retired-feed articles, %d orphaned events", verb, purged_articles, purged_events)

    engine.dispose()


if __name__ == "__main__":
    main()
