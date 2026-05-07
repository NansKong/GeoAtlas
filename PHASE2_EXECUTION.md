# Phase 2 Execution Guide

Date: 2026-03-13

This file is the practical execution guide for completing Phase 2.
It separates:

- what is already implemented in code
- what you need to run locally
- what still requires external datasets or trained model artifacts
- what counts as "done" for each unchecked task item

Use this together with [task.md](D:/GeoAtlas/task.md) and [SOURCE_OF_TRUTH.md](D:/GeoAtlas/SOURCE_OF_TRUTH.md).

## 1. Current State

The codebase already has these Phase 2 foundations:

- language detection metadata on `news_articles`
- relevance prefilter with heuristic fallback
- event extraction pipeline with confidence gating
- direct asset mapping from ticker mentions and company alias matches
- L2 knowledge graph expansion through `kg_relationships`
- human review UI at `/review`
- review feedback persistence into `event_training_examples`
- dataset export and training scaffolding in `backend/scripts`
- optional runtime support for local model artifacts:
  - relevance model
  - event classifier
  - sentiment model
  - NER model

What is not finished:

- real DistilBERT relevance model training/inference
- real spaCy transformer NER model
- real RoBERTa 7-class event classifier
- real FinBERT sentiment scoring
- ingestion of historical GDELT and ACLED files
- proper labeled historical pairing with Reuters/AP articles
- evaluation reports proving target metrics

## 2. Phase 2 Target

Phase 2 is complete only when all of the following are true:

- a reproducible training dataset pipeline exists
- chronological train/val/test splits exist
- trained model artifacts exist locally
- production worker loads those artifacts
- fallback behavior is defined if artifacts are missing
- metric reports exist for:
  - relevance precision
  - NER F1
  - event classifier F1
  - sentiment metric
- the review queue continues generating new supervised examples

## 3. Files Already Added For Phase 2

Core runtime and pipeline files:

- [config.py](D:/GeoAtlas/backend/core/config.py)
- [nlp_utils.py](D:/GeoAtlas/backend/workers/nlp_utils.py)
- [model_runtime.py](D:/GeoAtlas/backend/workers/model_runtime.py)
- [entity_utils.py](D:/GeoAtlas/backend/workers/entity_utils.py)
- [kg_utils.py](D:/GeoAtlas/backend/workers/kg_utils.py)
- [event_pipeline.py](D:/GeoAtlas/backend/workers/event_pipeline.py)
- [review_feedback.py](D:/GeoAtlas/backend/workers/review_feedback.py)

Training and preprocessing scripts:

- [build_training_corpora.py](D:/GeoAtlas/backend/scripts/build_training_corpora.py)
- [build_chrono_split.py](D:/GeoAtlas/backend/scripts/build_chrono_split.py)
- [train_text_classifier.py](D:/GeoAtlas/backend/scripts/train_text_classifier.py)
- [train_spacy_ner.py](D:/GeoAtlas/backend/scripts/train_spacy_ner.py)
- [normalize_historical_events.py](D:/GeoAtlas/backend/scripts/normalize_historical_events.py)

Review and dataset storage:

- [models.py](D:/GeoAtlas/backend/modules/events/models.py)
- [router.py](D:/GeoAtlas/backend/modules/events/router.py)
- [20260313_0004_event_training_examples.py](D:/GeoAtlas/backend/alembic/versions/20260313_0004_event_training_examples.py)

## 4. Environment Setup

Run this first:

```powershell
cd D:\GeoAtlas\backend
pip install -r requirements.txt
pip install torch
python -m spacy download en_core_web_trf
alembic upgrade head
```

Notes:

- `torch` is intentionally not pinned to a specific CUDA/CPU wheel in the repo.
- Install the version that matches your machine.
- If you only want CPU training/inference, normal `pip install torch` is enough.

## 5. Required `.env` Settings

Add these to `D:\GeoAtlas\backend\.env`:

```env
NLP_RELEVANCE_MODEL_MODE=heuristic
NLP_RELEVANCE_MODEL_PATH=

NLP_EVENT_MODEL_MODE=heuristic
NLP_EVENT_MODEL_PATH=

NLP_SENTIMENT_MODEL_MODE=heuristic
NLP_SENTIMENT_MODEL_PATH=

NLP_NER_MODEL_MODE=heuristic
NLP_NER_MODEL_PATH=

NLP_MODEL_DEVICE=-1
NLP_ENABLE_L2_KG_MAPPING=true
NLP_L2_HOP1_WEIGHT=0.60
NLP_L2_HOP2_WEIGHT=0.35
```

When model artifacts are trained, switch the modes:

```env
NLP_RELEVANCE_MODEL_MODE=transformers
NLP_RELEVANCE_MODEL_PATH=D:\GeoAtlas\backend\models\relevance_distilbert

NLP_EVENT_MODEL_MODE=transformers
NLP_EVENT_MODEL_PATH=D:\GeoAtlas\backend\models\event_roberta

NLP_SENTIMENT_MODEL_MODE=transformers
NLP_SENTIMENT_MODEL_PATH=D:\GeoAtlas\backend\models\sentiment_finbert

NLP_NER_MODEL_MODE=spacy
NLP_NER_MODEL_PATH=D:\GeoAtlas\backend\models\ner_spacy
```

## 6. Build Training Data From Review Feedback

This uses the existing `event_training_examples` table.

First backfill review-derived examples:

```powershell
cd D:\GeoAtlas\backend
celery -A workers.celery_app.celery_app call workers.review_feedback.backfill_training_examples --kwargs="{\"batch_size\":5000}"
```

Then build corpora:

```powershell
cd D:\GeoAtlas\backend
python scripts\build_training_corpora.py
```

This produces:

- `backend/data/processed/relevance.jsonl`
- `backend/data/processed/event_type.jsonl`
- `backend/data/processed/sentiment.jsonl`
- `backend/data/processed/weak_ner.jsonl`

What each file is for:

- `relevance.jsonl`
  - binary classification
  - `1 = human_approved`
  - `0 = rejected`
- `event_type.jsonl`
  - multiclass event-type training
  - only approved examples with event labels
- `sentiment.jsonl`
  - weak labels derived from approved/reviewed impact directions
- `weak_ner.jsonl`
  - weak supervision source for tag/entity extraction

## 7. Create Chronological Splits

Do not use random splitting for news/event modeling.

Run:

```powershell
cd D:\GeoAtlas\backend
python scripts\build_chrono_split.py data\processed\relevance.jsonl
python scripts\build_chrono_split.py data\processed\event_type.jsonl
python scripts\build_chrono_split.py data\processed\sentiment.jsonl
```

This produces:

- `backend/data/splits/relevance.train.jsonl`
- `backend/data/splits/relevance.val.jsonl`
- `backend/data/splits/relevance.test.jsonl`
- same structure for `event_type`
- same structure for `sentiment`

Completion rule:

- no future samples may appear in train relative to val/test
- splitting must preserve time order

## 8. Historical External Data You Must Supply

The repo now supports direct normalization of the local files you added.
You no longer need to pre-convert ACLED to CSV, and you do not need a separate Reuters archive just to get a Reuters slice.

### What The Normalizer Now Supports

`backend/scripts/normalize_historical_events.py` can now:

- read raw GDELT `.export.CSV` files directly from a file or directory
- read ACLED `.xlsx` workbooks directly from a file or directory
- derive a Reuters dataset from Reuters-tagged GDELT rows
- emit one combined normalized JSONL file across Reuters + ACLED + GDELT

### GDELT Event Database

Normalize the full raw GDELT directory you already added:

```powershell
cd D:\GeoAtlas\backend
python scripts\normalize_historical_events.py gdelt data\raw\gdelt data\processed\gdelt.normalized.jsonl
```

### ACLED Conflict Data

Normalize the ACLED workbook directory you already added:

```powershell
cd D:\GeoAtlas\backend
python scripts\normalize_historical_events.py acled data\ACLED data\processed\acled.normalized.jsonl
```

### Reuters Dataset

Reuters is now derived from the Reuters-tagged subset of raw GDELT rows.
This is not a full Reuters article archive; it is a Reuters-focused normalized event dataset extracted from GDELT provenance and URL markers.

```powershell
cd D:\GeoAtlas\backend
python scripts\normalize_historical_events.py reuters data\raw\gdelt data\processed\reuters.normalized.jsonl
```

### Combined Historical Dataset

Build one unified normalized dataset with Reuters written first, ACLED second, and the remaining GDELT rows last.
Reuters-overlapping GDELT rows are skipped in the combined file so the Reuters slice stays first-class instead of being duplicated.

```powershell
cd D:\GeoAtlas\backend
python scripts\normalize_historical_events.py combine data\processed\historical.combined.jsonl --gdelt-input data\raw\gdelt --acled-input data\ACLED --reuters-input data\raw\gdelt
```

### Output Schema

Each normalized row now includes these core fields:

- `canonical_id`
- `provider`
- `provider_record_id`
- `published_at`
- `event_date`
- `title`
- `description`
- `source_name`
- `source_url`
- `country`
- `region`
- `admin1`
- `location_name`
- `latitude`
- `longitude`
- `event_type`
- `sub_event_type`
- `event_code`
- `event_root_code`
- `actor1`
- `actor2`
- `fatalities`
- `num_mentions`
- `num_sources`
- `num_articles`
- `sentiment_score`
- `sentiment_label`
- `relevance_label`
- `metadata`

### Reuters/AP Pairing Status

Reuters extraction is now implemented from the local GDELT data.
AP pairing is still not implemented because there is no AP archive or AP-specific local schema in the workspace.
If you later add an AP historical dump, the same normalizer can be extended for it.

## 9. Train The Relevance Model

Goal:

- replace heuristic relevance with DistilBERT

Recommended command:

```powershell
cd D:\GeoAtlas\backend
python scripts\train_text_classifier.py --dataset data\processed\relevance.jsonl --model-name distilbert-base-uncased --output-dir models\relevance_distilbert
```

After training:

- set `NLP_RELEVANCE_MODEL_MODE=transformers`
- set `NLP_RELEVANCE_MODEL_PATH=D:\GeoAtlas\backend\models\relevance_distilbert`

Where it is used:

- [nlp_utils.py](D:/GeoAtlas/backend/workers/nlp_utils.py)

Completion rule:

- relevance inference runs from local artifact
- heuristic fallback remains intact if model path is missing
- test precision is recorded

## 10. Train The Event Type Classifier

Goal:

- replace keyword classifier with RoBERTa

Recommended command:

```powershell
cd D:\GeoAtlas\backend
python scripts\train_text_classifier.py --dataset data\processed\event_type.jsonl --model-name roberta-base --output-dir models\event_roberta
```

After training:

- set `NLP_EVENT_MODEL_MODE=transformers`
- set `NLP_EVENT_MODEL_PATH=D:\GeoAtlas\backend\models\event_roberta`

Where it is used:

- [event_pipeline.py](D:/GeoAtlas/backend/workers/event_pipeline.py)

Completion rule:

- `_infer_event_type` is driven primarily by model output
- keyword logic remains fallback only
- per-class metrics are available

## 11. Train The Sentiment Model

Goal:

- replace heuristic sentiment with FinBERT

Recommended command:

```powershell
cd D:\GeoAtlas\backend
python scripts\train_text_classifier.py --dataset data\processed\sentiment.jsonl --model-name ProsusAI/finbert --output-dir models\sentiment_finbert
```

After training:

- set `NLP_SENTIMENT_MODEL_MODE=transformers`
- set `NLP_SENTIMENT_MODEL_PATH=D:\GeoAtlas\backend\models\sentiment_finbert`

Where it is used:

- [nlp_utils.py](D:/GeoAtlas/backend/workers/nlp_utils.py)
- [event_pipeline.py](D:/GeoAtlas/backend/workers/event_pipeline.py)

Completion rule:

- sentiment scores are persisted for new articles
- model artifact is used at runtime
- evaluation metric is recorded

## 12. Train The NER Model

Goal:

- replace deterministic entity extraction with spaCy transformer NER

Current status:

- the repo has weak supervision sources
- it does not yet have a true labeled `.spacy` corpus generator

What you need to do:

1. Build annotated NER training data from approved examples.
2. Create a spaCy config.
3. Train with:

```powershell
cd D:\GeoAtlas\backend
python scripts\train_spacy_ner.py --config configs\spacy_ner.cfg --output-dir models\ner_spacy
```

After training:

- set `NLP_NER_MODEL_MODE=spacy`
- set `NLP_NER_MODEL_PATH=D:\GeoAtlas\backend\models\ner_spacy`

Where it is used:

- [entity_utils.py](D:/GeoAtlas/backend/workers/entity_utils.py)

Completion rule:

- model entities are included in tags and asset matching
- alias rules remain fallback
- F1 is measured on held-out examples

## 13. L1 And L2 Asset Mapping

### L1 Direct Mention

Current status:

- already implemented
- ticker mention matching works
- company alias matching works
- optional NER entities can feed the same path

Relevant files:

- [entity_utils.py](D:/GeoAtlas/backend/workers/entity_utils.py)
- [event_pipeline.py](D:/GeoAtlas/backend/workers/event_pipeline.py)

### L2 Knowledge Graph Traversal

Current status:

- implemented
- 1-hop and 2-hop asset expansion is active behind config

Relevant files:

- [kg_utils.py](D:/GeoAtlas/backend/workers/kg_utils.py)
- [event_pipeline.py](D:/GeoAtlas/backend/workers/event_pipeline.py)
- [models.py](D:/GeoAtlas/backend/modules/knowledge_graph/models.py)

What you should still do:

- tune `NLP_L2_HOP1_WEIGHT`
- tune `NLP_L2_HOP2_WEIGHT`
- inspect whether indirect impacts are too noisy

## 14. Backfill Commands After Training

Once model artifacts are configured in `.env`, restart services and backfill old data.

```powershell
cd D:\GeoAtlas\backend
uvicorn main:app --reload
```

In another terminal:

```powershell
cd D:\GeoAtlas\backend
celery -A workers.celery_app.celery_app worker -l info -P solo
celery -A workers.celery_app.celery_app beat -l info
```

Then backfill:

```powershell
cd D:\GeoAtlas\backend
celery -A workers.celery_app.celery_app call workers.event_pipeline.backfill_article_nlp_metadata --kwargs="{\"batch_size\":5000}"
celery -A workers.celery_app.celery_app call workers.event_pipeline.backfill_event_entities --kwargs="{\"batch_size\":1000}"
```

## 15. What I Could Implement And Already Did

Already done in code:

- runtime config for model artifact loading
- optional transformers/spaCy inference hooks
- training corpus builder
- chronological split builder
- generic classifier training wrapper
- generic spaCy training wrapper
- historical event normalizer for local GDELT/ACLED dumps
- L2 KG expansion in production worker

## 16. What I Could Not Finish For You

These require data or artifacts that are not in the workspace:

- actual GDELT historical dataset files
- actual ACLED historical dataset files
- Reuters/AP historical archive for pairing
- trained DistilBERT model weights
- trained RoBERTa event classifier weights
- trained FinBERT fine-tuned weights
- trained spaCy NER model
- metric reports from held-out evaluation

These are not code omissions. They are external-data and training-runtime dependencies.

## 17. What Counts As Done For Each Remaining Unchecked Task

### Relevance classifier

Done only when:

- artifact exists
- runtime uses it
- fallback exists
- evaluation precision is recorded

### spaCy NER

Done only when:

- labeled NER corpus exists
- trained model exists
- runtime uses it
- held-out F1 is recorded

### RoBERTa event classifier

Done only when:

- trained 7-class artifact exists
- worker uses it
- fallback exists
- class metrics are recorded

### FinBERT sentiment

Done only when:

- sentiment artifact exists
- new articles are scored in production path
- metric is recorded

### GDELT and ACLED ingestion

Done only when:

- local historical files are available
- normalized outputs are generated
- datasets are included in training pipeline

### Reuters/AP pairing

Done only when:

- historical article source exists
- event alignment logic exists
- labeled pairs are produced

## 18. Recommended Execution Order

Run these in this order:

1. Install dependencies and migrate DB
2. Backfill review-derived training examples
3. Build corpora
4. Build chronological splits
5. Normalize local GDELT and ACLED files
6. Train relevance model
7. Train event classifier
8. Train sentiment model
9. Train NER model
10. Switch `.env` modes from `heuristic` to artifact-backed runtime
11. Restart services
12. Backfill old articles/events through the new models
13. Generate evaluation metrics
14. Update `task.md`

## 19. Verification Checklist

Before marking Phase 2 complete, verify:

- `python -m compileall D:\GeoAtlas\backend`
- `cmd /c npx tsc --noEmit`
- `/review` still works
- `/api/v1/events` still returns structured events
- `/api/v1/news` still returns article metadata
- approved reviews continue generating `event_training_examples`
- model artifacts are actually being loaded, not silently falling back

## 20. Final Note

The repo is now set up so you do not need to redesign Phase 2 again.
The remaining work is mostly:

- supplying historical datasets
- running training jobs
- validating metrics
- switching runtime modes to trained artifacts
