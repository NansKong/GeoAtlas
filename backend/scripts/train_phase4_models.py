import os
import sys
import logging
from pathlib import Path

# Fix python path if running directly from script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.predictions.dataset_builder import build_training_dataset
from modules.predictions.ml_models import (
    TrendForcePredictor,
    VolatilityNetPredictor,
    RegimeFilterPredictor
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    dataset_path = "data/ml/predict_dataset.csv"
    
    logger.info("--- Step 1: Building Dataset ---")
    try:
        build_training_dataset(output_path=dataset_path)
    except Exception as e:
        logger.error(f"Failed to build dataset. Ensure your GeoAtlas database is running and accessible. Error: {e}")
        return

    if not os.path.exists(dataset_path):
        logger.error("Dataset not generated. Aborting training.")
        return
        
    logger.info("--- Step 2: Training RegimeFilter (RandomForest) ---")
    rf = RegimeFilterPredictor()
    rf.train(dataset_path)
    
    logger.info("--- Step 3: Training TrendForce (XGBoost GPU) ---")
    xgb = TrendForcePredictor()
    xgb.train(dataset_path)
    
    logger.info("--- Step 4: Training VolatilityNet (PyTorch LSTM CUDA) ---")
    lstm = VolatilityNetPredictor()
    lstm.train(dataset_path)
    
    logger.info("--- Phase 4 Prediction Models Trained successfully! ---")
    logger.info("Artifacts saved in data/ml/ (or the root data dir)")

if __name__ == "__main__":
    main()
