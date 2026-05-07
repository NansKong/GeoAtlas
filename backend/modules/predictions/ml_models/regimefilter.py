import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import os
import joblib
import logging

logger = logging.getLogger(__name__)

class RegimeFilterPredictor:
    """
    Random Forest model to classify the overarching market regime.
    Always-on background calculation ensuring base prediction rates are sensible.
    """
    def __init__(self, model_path: str = "data/ml/regimefilter.joblib"):
        self.model_path = model_path
        self.model = None
        self._load_model()
        
    def _load_model(self):
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
            except Exception as e:
                logger.error(f"Failed to load RF model: {e}")

    def train(self, dataset_path: str):
        if not os.path.exists(dataset_path):
            logger.error("Dataset not found for RegimeFilter.")
            return

        df = pd.read_csv(dataset_path)
        df = df.dropna(subset=["sentiment_score", "severity"])

        # Simple feature matrix
        X = df[["sentiment_score", "severity"]]
        # Let's say label_1h acts as a proxy for regime
        label_map = {"negative": 0, "neutral": 1, "positive": 2}
        y = df["label_1h"].map(label_map).fillna(1)
        
        self.model = RandomForestClassifier(n_estimators=50, max_depth=3, n_jobs=-1, random_state=42)
        
        try:
            self.model.fit(X, y)
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            joblib.dump(self.model, self.model_path)
            logger.info("RegimeFilter trained and saved.")
        except Exception as e:
            logger.error(f"Random Forest training failed: {e}")

    def predict(self, feature_dict: dict) -> dict:
        if not self.model:
            return {"regime": "neutral", "confidence": 0.0}
            
        df = pd.DataFrame([feature_dict])
        
        # Ensure exact column order required by scikit-learn
        expected_cols = ["sentiment_score", "severity"]
        for c in expected_cols:
            if c not in df.columns:
                df[c] = 0.0
                
        df = df[expected_cols]
                
        pred_idx = self.model.predict(df)[0]
        probs = self.model.predict_proba(df)[0]
        
        reverse_map = {0: "risk-off", 1: "neutral", 2: "risk-on"}
        regime = reverse_map.get(pred_idx, "neutral")
        
        return {
            "regime": regime,
            "confidence": float(max(probs)),
            "model_version": "RegimeFilter-RF-v1"
        }
