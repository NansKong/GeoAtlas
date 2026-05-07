from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    try:
        from spacy.cli.train import train
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Missing spaCy training dependencies: {exc}")

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parents[1] / config_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).resolve().parents[1] / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    train(str(config_path), str(output_dir), overrides={})


if __name__ == "__main__":
    main()
