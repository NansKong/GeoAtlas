from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.config import settings

logger = logging.getLogger(__name__)


def _path_exists(value: str) -> bool:
    return bool(value and Path(value).exists())


@lru_cache(maxsize=1)
def _load_transformers_pipeline(task: str, model_path: str):
    if not _path_exists(model_path):
        return None
    try:
        from transformers import pipeline

        return pipeline(task, model=model_path, tokenizer=model_path, device=settings.NLP_MODEL_DEVICE)
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        logger.warning("Transformers pipeline load failed for %s at %s: %s", task, model_path, exc)
        return None


@lru_cache(maxsize=1)
def _load_spacy_model(model_path: str):
    if not _path_exists(model_path):
        return None
    try:
        import spacy

        return spacy.load(model_path)
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        logger.warning("spaCy model load failed at %s: %s", model_path, exc)
        return None


@lru_cache(maxsize=1)
def _load_sklearn_model(model_path: str):
    if not _path_exists(model_path):
        return None
    try:
        from joblib import load

        return load(model_path)
    except Exception as exc:  # pragma: no cover
        logger.warning("sklearn model load failed at %s: %s", model_path, exc)
        return None


@lru_cache(maxsize=1)
def _load_volatility_lstm():
    try:
        from modules.predictions.ml_models.volatilitynet import VolatilityNetPredictor
        model = VolatilityNetPredictor() # Automatically loads weights or initializes empty structure
        # Verify the actual weights loaded, fall back if no file exists.
        if not _path_exists(model.model_path):
            raise RuntimeError("VolatilityNet weights missing")
        return model
    except Exception as exc:
        logger.warning("VolatilityNet load failed", exc_info=exc)
        return None


@lru_cache(maxsize=1)
def _load_chronos_net():
    try:
        from modules.predictions.ml_models.chronos_net import ChronosNetPredictor
        model = ChronosNetPredictor(use_gpu=(settings.NLP_MODEL_DEVICE >= 0))
        if not model.ready:
             raise RuntimeError("ChronosPipeline failed to initialize")
        return model
    except Exception as exc:
        logger.warning("ChronosNet load failed", exc_info=exc)
        return None


def predict_relevance(text: str) -> tuple[Optional[float], Optional[str]]:
    if settings.NLP_RELEVANCE_MODEL_MODE == "heuristic":
        return None, None
    if settings.NLP_RELEVANCE_MODEL_MODE == "sklearn":
        model_pack = _load_sklearn_model(settings.NLP_RELEVANCE_MODEL_PATH)
        if not model_pack:
            return None, None
        try:
            pipeline = model_pack["pipeline"]
            labels = list(model_pack.get("labels", []))
            prediction = str(pipeline.predict([text[:4096]])[0])
            if hasattr(pipeline, "predict_proba"):
                proba = pipeline.predict_proba([text[:4096]])[0]
                classes = list(pipeline.classes_)
                idx = classes.index(prediction)
                score = float(proba[idx])
            else:
                score = 0.7
            if prediction in {"0", "irrelevant"}:
                return max(0.0, 1.0 - score), "irrelevant"
            if prediction in {"1", "relevant"} or (labels and prediction == labels[-1]):
                return max(0.0, min(1.0, score)), "relevant"
            return max(0.0, min(1.0, score)), prediction
        except Exception as exc:  # pragma: no cover
            logger.warning("Relevance sklearn inference failed: %s", exc)
            return None, None

    classifier = _load_transformers_pipeline("text-classification", settings.NLP_RELEVANCE_MODEL_PATH)
    if classifier is None:
        return None, None
    try:
        result = classifier(text[:2048], truncation=True, top_k=None)
        rows = result[0] if result and isinstance(result[0], list) else result
        if not rows:
            return None, None
        best = max(rows, key=lambda item: float(item["score"]))
        label = str(best["label"]).lower()
        score = float(best["score"])
        if "irrelevant" in label or label.endswith("0") or label == "label_0":
            return 1.0 - score, "irrelevant"
        return score, "relevant"
    except Exception as exc:  # pragma: no cover
        logger.warning("Relevance inference failed: %s", exc)
        return None, None


def predict_event_type(text: str) -> tuple[Optional[str], Optional[float]]:
    if settings.NLP_EVENT_MODEL_MODE == "heuristic":
        return None, None
    if settings.NLP_EVENT_MODEL_MODE == "sklearn":
        model_pack = _load_sklearn_model(settings.NLP_EVENT_MODEL_PATH)
        if not model_pack:
            return None, None
        try:
            pipeline = model_pack["pipeline"]
            prediction = str(pipeline.predict([text[:4096]])[0]).lower()
            if hasattr(pipeline, "predict_proba"):
                proba = pipeline.predict_proba([text[:4096]])[0]
                classes = list(pipeline.classes_)
                idx = classes.index(prediction)
                score = float(proba[idx])
            else:
                score = 0.7
            return prediction, max(0.0, min(1.0, score))
        except Exception as exc:  # pragma: no cover
            logger.warning("Event-type sklearn inference failed: %s", exc)
            return None, None

    classifier = _load_transformers_pipeline("text-classification", settings.NLP_EVENT_MODEL_PATH)
    if classifier is None:
        return None, None
    try:
        result = classifier(text[:2048], truncation=True)
        if not result:
            return None, None
        best = result[0]
        label = str(best["label"]).lower().replace("label_", "")
        score = float(best["score"])
        mapping = {
            "0": "conflict",
            "1": "sanction",
            "2": "trade_policy",
            "3": "economic_data",
            "4": "energy_disruption",
            "5": "election",
            "6": "regulation",
        }
        return mapping.get(label, label), score
    except Exception as exc:  # pragma: no cover
        logger.warning("Event-type inference failed: %s", exc)
        return None, None


def predict_sentiment(text: str) -> Optional[float]:
    if settings.NLP_SENTIMENT_MODEL_MODE == "heuristic":
        return None
    if settings.NLP_SENTIMENT_MODEL_MODE == "sklearn":
        model_pack = _load_sklearn_model(settings.NLP_SENTIMENT_MODEL_PATH)
        if not model_pack:
            return None
        try:
            pipeline = model_pack["pipeline"]
            prediction = str(pipeline.predict([text[:4096]])[0]).lower()
            if prediction == "negative":
                return -0.7
            if prediction == "positive":
                return 0.7
            return 0.0
        except Exception as exc:  # pragma: no cover
            logger.warning("Sentiment sklearn inference failed: %s", exc)
            return None

    classifier = _load_transformers_pipeline("text-classification", settings.NLP_SENTIMENT_MODEL_PATH)
    if classifier is None:
        return None
    try:
        result = classifier(text[:2048], truncation=True)
        if not result:
            return None
        best = result[0]
        label = str(best["label"]).lower()
        score = float(best["score"])
        if "negative" in label or label.endswith("0"):
            return -score
        if "neutral" in label or label.endswith("1"):
            return 0.0
        return score
    except Exception as exc:  # pragma: no cover
        logger.warning("Sentiment inference failed: %s", exc)
        return None


def predict_entities(text: str) -> list[dict[str, str]]:
    if settings.NLP_NER_MODEL_MODE == "heuristic":
        return []
    ner = _load_spacy_model(settings.NLP_NER_MODEL_PATH)
    if ner is None:
        return []
    try:
        doc = ner(text[:5000])
        return [{"text": ent.text, "label": ent.label_} for ent in doc.ents if ent.text.strip()]
    except Exception as exc:  # pragma: no cover
        logger.warning("NER inference failed: %s", exc)
        return []

# --- XGBoost / Tabular Model Inference ---

@lru_cache(maxsize=1)
def _load_xgb_model():
    model_path = settings.XGB_MODEL_PATH
    
    if not _path_exists(model_path):
        logger.warning("XGB model path not found: %s", model_path)
        return None

    try:
        # Try sklearn-style first
        from joblib import load
        loaded_model = load(model_path)
        if isinstance(loaded_model, dict):
            # Model is a dictionary wrapper containing metadata
            model = loaded_model.get("pipeline") or loaded_model.get("model") or loaded_model.get("estimator") or loaded_model.get("xgb")
            if model and "features" in loaded_model:
                model.metadata = {"features": loaded_model["features"]}
                if "label_encoder" in loaded_model:
                    model.label_encoder = loaded_model["label_encoder"]
                return model
            elif model:
                return model
            else:
               raise ValueError(f"Could not find model inside dictionary keys: {list(loaded_model.keys())}")
        return loaded_model
    except Exception as exc1:
        logger.warning(f"joblib.load failed: {exc1}")
        try:
            import xgboost as xgb
            model = xgb.Booster()
            model.load_model(model_path)
            # Fetch metadata schema for feature order
            try:
                import json
                meta = model.attr("model_metadata")
                if meta:
                    meta_dict = json.loads(meta)
                    model.metadata = meta_dict
            except Exception:
                pass
            return model
        except Exception as exc:
            logger.warning("XGB model load failed: %s", exc)
            return None

def predict_regime_xgboost(features: dict) -> Optional[dict]:
    model = _load_xgb_model()
    if model is None:
        return None

    try:
        # Check if model has embedded schema
        if hasattr(model, "metadata") and "features" in model.metadata:
            FEATURE_ORDER = model.metadata["features"]
        else:
            FEATURE_ORDER = ["7d_vol", "sentiment_momentum"] # fallback

        # Enforce exact ordering (fails fast if totally missing, but we will patch it to fill 0.0 with warning)
        feature_vector = []
        missing_feats = []
        for f in FEATURE_ORDER:
            if f not in features:
                missing_feats.append(f)
                feature_vector.append(0.0)
            else:
                feature_vector.append(features[f])
                
        if missing_feats:
            logger.debug(f"XGB inference padded {len(missing_feats)} missing features with 0.0: {missing_feats[:3]}...")
            
        # Optional: range validation
        if "7d_vol" in FEATURE_ORDER and "7d_vol" in features:
            vol_idx = FEATURE_ORDER.index("7d_vol")
            if abs(feature_vector[vol_idx]) > 5.0: # 500% daily vol is impossible without glitch
                raise ValueError("7d_vol out of expected range")

        if hasattr(model, "predict"):
            raw_pred = model.predict([feature_vector])[0]
            p_breakout = 0.5
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba([feature_vector])[0]
                confidence = float(max(proba))
                # Assuming index 1 corresponds to breakout (1)
                if len(proba) > 1:
                    p_breakout = float(proba[1])
            else:
                confidence = 0.7
            
            # Inverse transform if label_encoder is present
            if hasattr(model, "label_encoder"):
                try:
                    pred = model.label_encoder.inverse_transform([raw_pred])[0]
                except Exception as e:
                    logger.warning(f"Label decoding failed, using raw prediction: {e}")
                    pred = raw_pred
            else:
                pred = raw_pred

        # native xgboost
        else:
            import xgboost as xgb
            dmatrix = xgb.DMatrix([feature_vector], feature_names=FEATURE_ORDER)
            raw_pred = model.predict(dmatrix)[0]
            p_breakout = float(raw_pred)  # For native binary:logistic, predict returns probability of positive class
            pred = 1 if p_breakout > 0.5 else 0
            confidence = max(p_breakout, 1.0 - p_breakout)

        return {
            "prediction": pred,
            "confidence": confidence,
            "p_breakout": p_breakout,
        }

    except Exception as exc:
        logger.warning("XGB inference failed: %s", exc)
        return None

def predict_volatility_lstm(feature_sequence: list) -> Optional[Dict[str, Any]]:
    """
    Executes deep learning Volatility spike prediction using the trained LSTM.
    """
    model = _load_volatility_lstm()
    if model is None:
        return None
        
    try:
        return model.predict(feature_sequence)
    except Exception as exc:
        logger.error("VolatilityNet LSTM inference failed: %s", exc)
        return None


def predict_chronos_trajectory(price_history: List[float], horizon_steps: int = 24) -> Optional[Dict[str, Any]]:
    """
    Executes long-horizon foundation model forecasting using amazon/chronos-t5-base.
    """
    model = _load_chronos_net()
    if model is None:
        return None
        
    try:
        return model.predict(price_history, horizon_steps=horizon_steps)
    except Exception as exc:
        logger.error("ChronosNet inference failed: %s", exc)
        return None


