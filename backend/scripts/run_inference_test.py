import os
import sys
import logging
from pprint import pprint

# Set HuggingFace download timeout dynamically to prevent large models like Chronos from timing out
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"

# Fix python path if running directly from script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.predictions.inference import get_orchestrator

logging.basicConfig(level=logging.WARNING)

def test_ensemble():
    print("Loading Orchestrator and loading models into VRAM (this may take a few seconds due to Chronos)...")
    orchestrator = get_orchestrator()
    
    # 1. Provide a dummy event text that represents a strong positive shock
    print("\n--- Constructing positive macro-economic event ---")
    event_text = "The Federal Reserve unexpectedly slashed interest rates by 50 basis points. Markets broadly rally as liquidity fears evaporate."
    
    # 2. Extract features simulating a high-severity economic data event
    features = {
        # "event_type": "economic_data",
        "severity": 4.5,
        "sentiment_score": 0.85
    }
    
    # 3. Simulate sequential historical sentiment/volatility blocks (10 ticks) for LSTM
    sequence = [0.1, 0.2, 0.15, 0.3, 0.5, 0.6, 0.55, 0.7, 0.8, 0.85]
    # 4. Provide dummy historical price points mimicking an uptrend across 24h
    price_history = [100.0 + (i * 0.5) for i in range(24)]
    
    print("\nExecuting unified prediction engine ensemble...")
    result = orchestrator.generate_predictions(
        event_text=event_text,
        features=features,
        sequence=sequence,
        price_history=price_history
    )
    
    print("\n--- DEBUG: Model Outputs ---")
    pprint(result.get("model_breakdown", {}))
    
    print("\n================ FINAL INFERENCE ENSEMBLE RESULT ================\n")
    pprint(result.get("final_prediction", {}), sort_dicts=False)

if __name__ == "__main__":
    test_ensemble()
