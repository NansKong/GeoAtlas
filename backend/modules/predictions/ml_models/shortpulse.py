import torch
from transformers import pipeline
import logging

logger = logging.getLogger(__name__)

class ShortPulsePredictor:
    """
    FinBERT + Linear head for Short-term 1h-6h sentiment-driven directional mapping.
    Mops raw financial text to Positive/Negative/Neutral.
    """
    def __init__(self, use_gpu: bool = True):
        # We prefer "ProsusAI/finbert" which is well-established for financial sentiment.
        model_name = "ProsusAI/finbert"
        
        device = 0 if use_gpu and torch.cuda.is_available() else -1
        logger.info(f"Loading ShortPulse/FinBERT model: {model_name} on device {device}")
        
        try:
            self.classifier = pipeline("sentiment-analysis", model=model_name, tokenizer=model_name, device=device)
        except Exception as e:
            logger.error(f"Failed to load FinBERT: {e}")
            self.classifier = None

    def predict(self, text: str) -> dict:
        """
        Returns the direction and score.
        Example: {'direction': 'up', 'confidence': 0.85, 'horizon': '1h'}
        """
        if not self.classifier:
            return {"direction": "neutral", "confidence": 0.0, "horizon": "1h"}
        
        result = self.classifier(text[:2048])
        if not result:
            return {"direction": "neutral", "confidence": 0.0, "horizon": "1h"}
            
        best = result[0]
        label = best["label"].lower() # positive, negative, neutral
        score = best["score"]
        
        if "pos" in label:
            direction = "up"
        elif "neg" in label:
            direction = "down"
        else:
            direction = "neutral"
            
        return {
            "direction": direction,
            "confidence": float(score),
            "horizon": "1h",
            "model_version": "ShortPulse-FinBERT-v1"
        }
