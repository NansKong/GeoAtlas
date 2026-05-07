from __future__ import annotations

import argparse
from pathlib import Path

import spacy
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from modules.market.models import Asset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out = Path(args.output_dir)
    if not out.is_absolute():
        out = Path(__file__).resolve().parents[1] / out
    out.mkdir(parents=True, exist_ok=True)

    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    with Session(engine) as session:
        assets = session.execute(select(Asset)).scalars().all()

    patterns = []
    for asset in assets:
        ticker = (asset.ticker or "").strip().upper()
        name = (asset.name or "").strip()
        if ticker:
            patterns.append({"label": "ORG", "pattern": ticker})
        if name:
            patterns.append({"label": "ORG", "pattern": name})
        if asset.country:
            patterns.append({"label": "GPE", "pattern": asset.country})

    # Global macro entities.
    for term in ["Federal Reserve", "European Central Bank", "OPEC", "NATO", "US", "China", "India", "Russia"]:
        patterns.append({"label": "ORG", "pattern": term})

    ruler.add_patterns(patterns)
    nlp.to_disk(out)
    print(f"saved={out} patterns={len(patterns)}")


if __name__ == "__main__":
    main()
