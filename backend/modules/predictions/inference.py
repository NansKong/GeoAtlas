from __future__ import annotations
import logging
from typing import Dict, Any

from .ml_models.shortpulse import ShortPulsePredictor
from .ml_models.trendforce import TrendForcePredictor
from .ml_models.volatilitynet import VolatilityNetPredictor
from .ml_models.regimefilter import RegimeFilterPredictor
from .ml_models.chronos_net import ChronosNetPredictor

logger = logging.getLogger(__name__)

class PredictionOrchestrator:
    def __init__(self, use_gpu: bool = True):
        logger.info("Initializing Prediction Orchestrator with Phase 4 models...")
        self.shortpulse = ShortPulsePredictor(use_gpu=use_gpu)
        self.trendforce = TrendForcePredictor()
        self.volatilitynet = VolatilityNetPredictor()
        self.regimefilter = RegimeFilterPredictor()
        self.chronos = ChronosNetPredictor(use_gpu=use_gpu)

    def generate_predictions(self, event_text: str, features: Dict[str, Any], sequence: list, price_history: list) -> dict:
        """
        Orchestrates inference across all Phase 4 models.
        Ensemble Architecture:
                RegimeFilter
                     ↓
        ┌────────────┼────────────┐
        ↓            ↓            ↓
     XGBoost        LSTM       Chronos
        ↓            ↓            ↓
        └────────────┼────────────┘
                     ↓
              Final Prediction
        """
        
        # 1. Regime Filter serves as the base weighting context
        regime_output = self.regimefilter.predict(features)
        regime = regime_output.get("regime", "neutral")
        
        # 2. Individual Model Predictors
        shortpulse_out = self.shortpulse.predict(event_text) # NLP immediate sentiment
        xgboost_out = self.trendforce.predict(features) # Trend 24h
        lstm_out = self.volatilitynet.predict(sequence) # Volatility risks
        chronos_out = self.chronos.predict(price_history=price_history) # Future price sequence
        
        # 3. Numeric Translation for Ensembling
        # Map categorical models into proxy percent changes using their confidence
        # Baseline assumption: A max confidence 'up' normally correlates to a ~3.0% move in crypto 
        def to_numeric(model_out, baseline_impact=3.0):
            if not isinstance(model_out, dict): return 0.0
            direction = model_out.get("direction", "neutral")
            conf = model_out.get("confidence", 0.0)
            if direction == "up": return baseline_impact * conf
            if direction == "down": return -baseline_impact * conf
            return 0.0

        import numpy as np

        def normalize(x):
            return max(min(x, 10.0), -10.0)

        xgb_change = normalize(to_numeric(xgboost_out, 3.0))
        lstm_change = normalize(to_numeric(lstm_out, 5.0))
        
        # Chronos is natively numeric (predicts actual prices)
        # Handle Chronos dynamic confidence and normalization
        if len(price_history) > 0 and price_history[-1] > 0:
            median_pred = chronos_out.get("median_prediction", price_history[-1])
            chronos_raw = ((median_pred - price_history[-1]) / price_history[-1]) * 100.0
            chronos_change = normalize(chronos_raw)
            
            q10 = chronos_out.get("predicted_quantiles", {}).get("0.10", median_pred)
            q90 = chronos_out.get("predicted_quantiles", {}).get("0.90", median_pred)
            spread = abs(q90 - q10)
            
            # smaller spread = higher confidence
            chronos_conf = max(0.3, min(1.0, 1.0 - (spread / max(median_pred, 1e-6))))
        else:
            chronos_change = 0.0
            chronos_conf = 0.0 # Model failure/fallback detection

        xgb_conf = xgboost_out.get("confidence", 0.5)
        lstm_conf = lstm_out.get("confidence", 0.5)

        # 4. Regime-Based Dynamic Ensembling
        if regime == "risk-on":
            wc = 0.6; wx = 0.3; wl = 0.1
        elif regime == "risk-off":
            wc = 0.3; wx = 0.1; wl = 0.6
        else:
            wc = 0.4; wx = 0.4; wl = 0.2
            
        # Ignore dead models
        if xgb_conf < 0.05: wx = 0.0
        if lstm_conf < 0.05: wl = 0.0
        if chronos_conf < 0.05: wc = 0.0
        
        # Confidence-weighted fusion securely bounded by Regime modifiers
        total_weight = (chronos_conf * wc) + (xgb_conf * wx) + (lstm_conf * wl) + 1e-6
        final_change = (
            (chronos_change * chronos_conf * wc) + 
            (xgb_change * xgb_conf * wx) + 
            (lstm_change * lstm_conf * wl)
        ) / total_weight
        
        # Disagreement penalty over active signals
        signals = [np.sign(chronos_change), np.sign(xgb_change), np.sign(lstm_change)]
        agreement = abs(sum(signals)) / len(signals)
        
        # Make FinBERT informational/directional bias mapped efficiently
        sent_conf = shortpulse_out.get("confidence", 0.5)
        short_dir = shortpulse_out.get("direction")
        if short_dir == "down":
            final_change -= 0.5 * sent_conf
        elif short_dir == "up":
            final_change += 0.5 * sent_conf

        # 5. Clamping unrealistic outputs (Crypto shouldn't project > 15% randomly per tick)
        final_change = max(min(final_change, 15.0), -15.0)

        # 6. Strict Directional Consistency (Must-Fix)
        if final_change > 0.5:
            final_direction = "up"
        elif final_change < -0.5:
            final_direction = "down"
        else:
            final_direction = "neutral"

        # Volatility boundary derivation
        volatility_modifier = lstm_out.get("confidence", 0.5) * 4.0
        expected_min_pct = final_change - volatility_modifier
        expected_max_pct = final_change + volatility_modifier

        # Average blended confidence weighted down by aggregate disagreement
        base_confidence = (chronos_conf + xgb_conf + lstm_conf) / 3.0
        final_confidence = base_confidence * agreement

        output_payload = {
            "regime_context": regime,
            "final_prediction": {
                "direction": final_direction,
                "confidence": round(final_confidence, 3),
                "predicted_change_pct": round(final_change, 2),
                "expected_min_pct": round(expected_min_pct, 2),
                "expected_max_pct": round(expected_max_pct, 2),
            },
            "model_breakdown": {
                "shortpulse_finbert": shortpulse_out,
                "trendforce_xgboost": xgboost_out,
                "volatilitynet_lstm": lstm_out,
                "chronos_benchmark": chronos_out
            },
            "debug": {
                "chronos_change": round(chronos_change, 2),
                "xgb_change": round(xgb_change, 2),
                "lstm_change": round(lstm_change, 2),
                "agreement": round(agreement, 3),
                "weights": {
                    "chronos": wc,
                    "xgb": wx,
                    "lstm": wl
                }
            }
        }
        
        # 7. Local Disk Logging for Analytics
        import json
        from datetime import datetime, timezone
        import os
        try:
            log_dir = "data/ml"
            os.makedirs(log_dir, exist_ok=True)
            log_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_features": features,
                "prediction": output_payload["final_prediction"],
                "models": output_payload["model_breakdown"]
            }
            with open(os.path.join(log_dir, "inference_logs.jsonl"), "a") as f:
                f.write(json.dumps(log_record) + "\n")
        except Exception as e:
            logger.error(f"Failed to log inference: {e}")

        return output_payload

orchestrator = None

def get_orchestrator() -> PredictionOrchestrator:
    global orchestrator
    if orchestrator is None:
        orchestrator = PredictionOrchestrator(use_gpu=True)
    return orchestrator


# ─── ASYNC INFERENCE ENGINE ──────────────────────────────────────────────────

import asyncio
from core.http import LRUCache

_prediction_cache = LRUCache(max_size=1000, ttl_seconds=300)
_ml_timeout_count = 0


def _heuristic_neutral() -> dict:
    """Lightweight neutral fallback when models timeout or crash."""
    return {
        "regime_context": "neutral",
        "final_prediction": {
            "direction": "neutral",
            "confidence": 0.05,
            "predicted_change_pct": 0.0,
            "expected_min_pct": -1.0,
            "expected_max_pct": 1.0,
        },
        "model_breakdown": {},
        "debug": {"fallback": True},
    }


async def generate_predictions_async(
    event_text: str,
    features: Dict[str, Any],
    sequence: list,
    price_history: list,
    cache_key: str = "",
) -> dict:
    """
    Production-grade async inference with:
    • Parallel model execution via asyncio.to_thread
    • 2s hard timeout
    • LRU + TTL cache (1000 entries, 5 min)
    • Heuristic neutral fallback on timeout/crash
    """
    global _ml_timeout_count

    # Cache check
    if cache_key:
        cached = _prediction_cache.get(cache_key)
        if cached:
            return cached

    orch = get_orchestrator()

    async def _run_inference():
        return await asyncio.to_thread(
            orch.generate_predictions,
            event_text,
            features,
            sequence,
            price_history,
        )

    try:
        result = await asyncio.wait_for(_run_inference(), timeout=2.0)
    except asyncio.TimeoutError:
        _ml_timeout_count += 1
        logger.warning("ML inference timed out (%d total)", _ml_timeout_count)
        return _heuristic_neutral()
    except Exception as exc:
        logger.error("ML inference crashed: %s", exc)
        return _heuristic_neutral()

    # Cache the result
    if cache_key:
        _prediction_cache.set(cache_key, result)

    return result


def get_ml_timeout_count() -> int:
    return _ml_timeout_count
