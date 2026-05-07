import os
import sys
import pandas as pd
import logging
from pathlib import Path
from dotenv import load_dotenv

# Fix python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Load variables from the backend/.env file so pydantic Settings() works
load_dotenv(BACKEND_ROOT / ".env")

from workers.model_runtime import predict_regime_xgboost

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def run_backtest():
    logger.info("Initializing Backtest for New XGBoost Prediction Pipeline...")
    
    dataset_path = BACKEND_ROOT / "tmp" / "phase4" / "multi_asset_dataset.csv"
    if not dataset_path.exists():
        logger.error(f"Dataset missing at {dataset_path}. Please run dataset_builder.py first.")
        return
        
    df = pd.read_csv(dataset_path)
    if "volatility_7d" not in df.columns or "sentiment_momentum" not in df.columns or "target" not in df.columns:
         logger.error("Dataset missing required columns ('volatility_7d', 'sentiment_momentum', 'target').")
         return

    # 0. Feature Engineering exactly as train_xgboost.py implemented it
    import numpy as np
    if "sentiment_momentum" in df.columns:
        df["sentiment_trend"] = np.sign(df["sentiment_momentum"])
    if "event_count" in df.columns:
        df["event_spike"] = (df["event_count"] > df["event_count"].rolling(7).mean()).astype(int)
    if "volatility_7d" in df.columns:
        df["volatility_spike"] = (df["volatility_7d"] > df["volatility_7d"].rolling(14).mean()).astype(int)

    total_records = len(df)
    logger.info(f"Loaded {total_records} historical records. Starting Backtest...")
    
    correct_direction = 0
    total_tested = 0
    total_predictions = 0

    for i in range(total_records):
        row = df.iloc[i]
        
        # 1. Feature construct mapping dataset columns mapping dynamically
        features = row.to_dict()
        
        # Add legacy fallback names if necessary
        if "volatility_7d" in features:
             features["7d_vol"] = min(5.0, float(features["volatility_7d"]))
        
        # Clean nulls
        for k in features:
            if pd.isna(features[k]):
                features[k] = 0.0
        
        # 2. Predict
        try:
            pred = predict_regime_xgboost(features)
            
            if not pred:
                continue
                
            prediction_val = pred["prediction"]
            confidence = pred["confidence"]
            
            # Predict dir: 1 if > 0 else -1
            predicted_dir = 1 if prediction_val > 0 else -1
            
            # Actual dir: the dataset might have 'target' (1: breakout, 0: nothing)
            # Or future_return 
            if "future_return" in df.columns:
                actual_return = float(row["future_return"])
                if abs(actual_return) < 0.005: 
                    actual_dir = 0 # Neutral
                else:
                    actual_dir = 1 if actual_return > 0 else -1
            else:
                 actual_dir = int(row["target"]) # Adjust based on schema

            # Filter low confidence
            if confidence >= 0.6:
                total_predictions += 1
                if predicted_dir == actual_dir:
                    correct_direction += 1
            
            total_tested += 1
            if total_tested % 500 == 0:
                logger.info(f"Processed {total_tested} events. "
                            f"Predictions made (conf>0.6): {total_predictions}. "
                            f"Acc: {(correct_direction/max(total_predictions, 1))*100:.1f}%")
                
        except Exception as e:
            logger.error(f"Failed prediction on index {i}: {e}")

    final_accuracy = (correct_direction / max(total_predictions, 1)) * 100.0
    logger.info(f"--- BACKTEST COMPLETE ---")
    logger.info(f"Total Evaluated: {total_tested}")
    logger.info(f"Predictions Fired (>= 0.6 conf): {total_predictions}")
    logger.info(f"Directional Accuracy: {final_accuracy:.2f}%")

if __name__ == "__main__":
    run_backtest()
