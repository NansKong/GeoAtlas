from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="JSONL dataset path")
    parser.add_argument("--model-name", required=True, help="Base model name or local path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--label-field", default="label")
    args = parser.parse_args()

    try:
        from datasets import load_dataset
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Missing ML dependencies: {exc}")

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = Path(__file__).resolve().parents[1] / dataset_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).resolve().parents[1] / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset("json", data_files=str(dataset_path), split="train")
    labels = sorted({row[args.label_field] for row in dataset})
    label2id = {label: idx for idx, label in enumerate(labels)}
    id2label = {idx: label for label, idx in label2id.items()}

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    def preprocess(batch):
        encoded = tokenizer(batch[args.text_field], truncation=True, padding="max_length", max_length=256)
        encoded["label"] = [label2id[label] for label in batch[args.label_field]]
        return encoded

    dataset = dataset.map(preprocess, batched=True)
    dataset = dataset.train_test_split(test_size=0.1, shuffle=False)

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=len(labels),
        label2id=label2id,
        id2label=id2label,
    )

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(output_dir / "runs"),
            num_train_epochs=2,
            per_device_train_batch_size=8,
            per_device_eval_batch_size=8,
            evaluation_strategy="epoch",
            save_strategy="epoch",
            logging_steps=20,
            load_best_model_at_end=False,
            report_to=[],
        ),
        train_dataset=dataset["train"],
        eval_dataset=dataset["test"],
        tokenizer=tokenizer,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))


if __name__ == "__main__":
    main()
