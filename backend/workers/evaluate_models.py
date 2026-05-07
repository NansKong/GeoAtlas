import os
import logging
import pandas as pd
import torch
from transformers import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Verify GPU
CUDA_AVAILABLE = torch.cuda.is_available()
device_id = 0 if CUDA_AVAILABLE else -1
logger.info(f"CUDA Available: {CUDA_AVAILABLE}")
if CUDA_AVAILABLE:
    logger.info(f"Target GPU: {torch.cuda.get_device_name(0)}")

def test_finbert_sentiment():
    logger.info("Initializing ProsusAI/finbert NLP pipeline...")
    # This automatically downloads the best-in-class financial BERT model from HF
    # Because we pass device_id, it will load it securely into the RTX 2060 VRAM.
    sentiment_model = pipeline("text-classification", model="ProsusAI/finbert", device=device_id)
    
    # Test Sentences relating to geopolitical events
    test_events = [
        "The Federal Reserve aggressively lowered interest rates, prompting a massive rally in global tech stocks.",
        "A severe supply chain disruption in Taiwan has halted semiconductor manufacturing.",
        "China and the US remained deadlocked over routine agricultural tariffs without escalating tensions."
    ]
    
    logger.info("--- FinBERT Inference Results ---")
    for text in test_events:
        result = sentiment_model(text)[0]
        logger.info(f"Event: '{text}'")
        logger.info(f"  -> Prediction: {result['label'].upper()} (Confidence: {result['score']:.4f})\n")

def test_chronos_forecasting():
    logger.info("Initializing amazon/chronos-t5-large Zero-Shot Time Series...")
    try:
        from chronos import ChronosPipeline
    except ImportError:
        logger.error("The 'chronos-forecasting' package is not installed.")
        logger.error("Please run: pip install chronos-forecasting accelerate")
        return

    try:
        pipeline = ChronosPipeline.from_pretrained(
            "amazon/chronos-t5-large",
            device_map="cuda", # Force RTX 2060 mapping
            torch_dtype=torch.bfloat16,
        )
        logger.info("Chronos T5-Large loaded successfully into VRAM!")
        
        # Example: Mocking recent historical prices to predict the future limits
        context_tensor = torch.tensor([
            # Mock historical close prices leading up to an event
            150.0, 151.2, 149.8, 148.5, 145.0, 142.1, 144.0, 138.5, 137.9, 140.0
        ])
        
        # We ask chronos to predict the next 5 days of data
        forecast = pipeline.predict(context_tensor.unsqueeze(0), prediction_length=5)
        logger.info(f"Raw prediction tensor generated: {forecast.shape}")
        
    except Exception as e:
        logger.error(f"Failed to run Chronos: {e}")

if __name__ == "__main__":
    test_finbert_sentiment()
    logger.info("\n=========================\n")
    test_chronos_forecasting()
