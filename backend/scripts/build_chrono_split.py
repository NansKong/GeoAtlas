from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=lambda item: item.get("created_at", ""))
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument("--output-dir", default="data/splits")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = root / input_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    rows = load_rows(input_path)
    total = len(rows)
    train_end = int(total * args.train_ratio)
    val_end = train_end + int(total * args.val_ratio)

    train_rows = rows[:train_end]
    val_rows = rows[train_end:val_end]
    test_rows = rows[val_end:]

    stem = input_path.stem
    write_rows(output_dir / f"{stem}.train.jsonl", train_rows)
    write_rows(output_dir / f"{stem}.val.jsonl", val_rows)
    write_rows(output_dir / f"{stem}.test.jsonl", test_rows)

    print(
        json.dumps(
            {
                "input": str(input_path),
                "train": len(train_rows),
                "val": len(val_rows),
                "test": len(test_rows),
                "output_dir": str(output_dir),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
