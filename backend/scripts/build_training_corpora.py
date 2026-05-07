from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.events.models import EventTrainingExample


def _text(title: str, content: str | None) -> str:
    return "\n".join(part for part in [title.strip(), (content or "").strip()] if part).strip()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    with Session(engine) as session:
        rows = session.execute(
            select(EventTrainingExample).order_by(EventTrainingExample.created_at.asc())
        ).scalars().all()

    relevance_path = output_dir / "relevance.jsonl"
    event_type_path = output_dir / "event_type.jsonl"
    sentiment_path = output_dir / "sentiment.jsonl"
    weak_ner_path = output_dir / "weak_ner.jsonl"

    with (
        relevance_path.open("w", encoding="utf-8") as relevance_file,
        event_type_path.open("w", encoding="utf-8") as event_type_file,
        sentiment_path.open("w", encoding="utf-8") as sentiment_file,
        weak_ner_path.open("w", encoding="utf-8") as weak_ner_file,
    ):
        for row in rows:
            text = _text(row.article_title, row.article_content)
            if not text:
                continue

            relevance_file.write(
                json.dumps(
                    {
                        "id": str(row.id),
                        "text": text,
                        "label": 1 if row.label_status == "human_approved" else 0,
                        "created_at": row.created_at.isoformat(),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

            if row.label_status == "human_approved" and row.label_event_type:
                event_type_file.write(
                    json.dumps(
                        {
                            "id": str(row.id),
                            "text": text,
                            "label": row.label_event_type,
                            "created_at": row.created_at.isoformat(),
                        },
                        ensure_ascii=True,
                    )
                    + "\n"
                )

            if row.affected_assets:
                directions = [item.get("impact_direction", "neutral") for item in row.affected_assets if isinstance(item, dict)]
                if directions:
                    sentiment_label = "neutral"
                    if any(direction == "negative" for direction in directions):
                        sentiment_label = "negative"
                    elif any(direction == "positive" for direction in directions):
                        sentiment_label = "positive"
                    sentiment_file.write(
                        json.dumps(
                            {
                                "id": str(row.id),
                                "text": text,
                                "label": sentiment_label,
                                "created_at": row.created_at.isoformat(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )

            weak_ner_file.write(
                json.dumps(
                    {
                        "id": str(row.id),
                        "text": text,
                        "tags": row.tags or [],
                        "created_at": row.created_at.isoformat(),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

    print(
        json.dumps(
            {
                "rows": len(rows),
                "relevance_path": str(relevance_path),
                "event_type_path": str(event_type_path),
                "sentiment_path": str(sentiment_path),
                "weak_ner_path": str(weak_ner_path),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
