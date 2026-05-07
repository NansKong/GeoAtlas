import torch
import logging
import numpy as np
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class ChronosNetPredictor:
    """
    Chronos Time-Series Foundation Model (amazon/chronos-t5-base).
    Requires 'chronos' package: `pip install chronos-forecasting`
    """
    def __init__(self, use_gpu: bool = True):
        self.device = "cuda" if torch.cuda.is_available() and use_gpu else "cpu"
        self.model_name = "amazon/chronos-t5-base"
        logger.info(f"Loading ChronosNet: {self.model_name} on device {self.device}")
        
        try:
            from chronos import ChronosPipeline
            self.pipeline = ChronosPipeline.from_pretrained(
                self.model_name,
                device_map=self.device,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            )
            self.ready = True
        except ImportError:
            logger.error("Missing chronos package. Run: pip install git+https://github.com/amazon-science/chronos-forecasting.git")
            self.ready = False
        except Exception as e:
            logger.error(f"Failed to load ChronosPipeline: {e}")
            self.ready = False

    def predict(self, price_history: List[float], horizon_steps: int = 24) -> Dict[str, Any]:
        if not self.ready or len(price_history) < 2:
            return {"predicted_quantiles": [], "median_prediction": 0.0, "horizon": f"H{horizon_steps}"}

        try:
            series = torch.tensor(price_history)
            
            # chronos pipeline requires batch dimension
            forecast = self.pipeline.predict(series.unsqueeze(0), prediction_length=horizon_steps)
            
            # forecast acts as a distribution, usually shape (batch_size, num_samples, prediction_length)
            # We want the median path over the num_samples
            median_path = np.quantile(forecast[0].numpy(), 0.5, axis=0)
            low_path = np.quantile(forecast[0].numpy(), 0.1, axis=0)
            high_path = np.quantile(forecast[0].numpy(), 0.9, axis=0)
            
            # Get the final step prediction
            final_median = float(median_path[-1])
            final_low = float(low_path[-1])
            final_high = float(high_path[-1])
            
        except Exception as e:
            logger.error(f"Chronos prediction failed: {e}")
            final_median = price_history[-1]
            final_low = final_median
            final_high = final_median

        return {
            "median_prediction": final_median,
            "predicted_quantiles": {
                "0.10": final_low,
                "0.90": final_high
            },
            "horizon": f"H{horizon_steps}",
            "model_version": "ChronosNet-T5-v1"
        }
