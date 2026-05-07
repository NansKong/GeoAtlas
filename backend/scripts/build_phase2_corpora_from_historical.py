from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


EVENT_LABEL_MAP = {
    "Conflict": "conflict",
    "Sanctions": "sanction",
    "Trade Policy": "trade_policy",
    "Economic Data": "economic_data",
    "Energy Disruption": "energy_disruption",
    "Elections": "election",
    "Regulation": "regulation",
    "Diplomatic": "regulation",
}

NEGATIVE_RELEVANCE_TEMPLATES = [
    "Local sports team wins championship match after overtime thriller.",
    "Celebrity fashion event highlights seasonal runway trends and style tips.",
    "Weekend travel guide explores beaches, cafes, and leisure hotspots.",
    "Movie box office roundup covers premieres and entertainment gossip.",
]


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _to_text(row: dict) -> str:
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "").strip()
    return "\n".join(part for part in [title, description] if part).strip()


def _extract_weak_tags(row: dict) -> list[str]:
    tags: list[str] = []
    for key in ("country", "location_name", "actor1", "actor2", "event_type", "sub_event_type"):
        value = str(row.get(key) or "").strip()
        if value:
            tags.append(value)
    clean_tags: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = re.sub(r"\s+", " ", tag)
        if normalized and normalized not in seen:
            seen.add(normalized)
            clean_tags.append(normalized[:80])
    return clean_tags[:14]


def build_corpora(input_path: Path, output_dir: Path, max_rows: int | None) -> dict[str, int]:
    rows = _load_jsonl(input_path)
    rows.sort(key=lambda item: item.get("published_at") or item.get("event_date") or "")
    if max_rows:
        rows = rows[:max_rows]

    relevance_rows: list[dict] = []
    event_type_rows: list[dict] = []
    sentiment_rows: list[dict] = []
    weak_ner_rows: list[dict] = []

    for idx, row in enumerate(rows):
        text = _to_text(row)
        if not text:
            continue
        created_at = row.get("published_at") or f"{row.get('event_date', '2026-01-01')}T00:00:00Z"
        base_id = str(row.get("canonical_id") or f"hist-{idx}")

        relevance_rows.append(
            {"id": base_id, "text": text, "label": 1, "created_at": created_at}
        )
        negative_template = NEGATIVE_RELEVANCE_TEMPLATES[idx % len(NEGATIVE_RELEVANCE_TEMPLATES)]
        relevance_rows.append(
            {
                "id": f"{base_id}-neg",
                "text": negative_template,
                "label": 0,
                "created_at": created_at,
            }
        )

        event_type = EVENT_LABEL_MAP.get(str(row.get("event_type") or "").strip())
        if event_type:
            event_type_rows.append(
                {"id": base_id, "text": text, "label": event_type, "created_at": created_at}
            )

        sentiment_score = row.get("sentiment_score")
        label = "neutral"
        if isinstance(sentiment_score, (int, float)):
            if sentiment_score <= -0.5:
                label = "negative"
            elif sentiment_score >= 0.5:
                label = "positive"
        sentiment_rows.append(
            {"id": base_id, "text": text, "label": label, "created_at": created_at}
        )

        weak_ner_rows.append(
            {
                "id": base_id,
                "text": text,
                "tags": _extract_weak_tags(row),
                "created_at": created_at,
            }
        )

    _write_jsonl(output_dir / "relevance.jsonl", relevance_rows)
    _write_jsonl(output_dir / "event_type.jsonl", event_type_rows)
    _write_jsonl(output_dir / "sentiment.jsonl", sentiment_rows)
    _write_jsonl(output_dir / "weak_ner.jsonl", weak_ner_rows)
    return {
        "relevance_rows": len(relevance_rows),
        "event_type_rows": len(event_type_rows),
        "sentiment_rows": len(sentiment_rows),
        "weak_ner_rows": len(weak_ner_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="data/processed/historical.combined.jsonl",
        help="Combined normalized historical JSONL path.",
    )
    parser.add_argument("--output-dir", default="data/processed")
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = root / input_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    stats = build_corpora(input_path, output_dir, args.max_rows)
    print(json.dumps({"input": str(input_path), "output_dir": str(output_dir), **stats}, ensure_ascii=True))


if __name__ == "__main__":
    main()
