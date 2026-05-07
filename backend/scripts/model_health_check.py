"""
Phase 4.2 — Model Integration Health Check
Verifies that VolatilityNet (LSTM) and ChronosNet (T5) can load without crashing.
"""
import sys
import os
from pathlib import Path

# 1. chdir into backend/ so pydantic-settings finds .env automatically
BACKEND_DIR = Path(__file__).resolve().parent.parent
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

# 2. Now safe to import (Settings will pick up .env from cwd)
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

from workers.model_runtime import _load_chronos_net, _load_volatility_lstm

print("\n========== Integration Health Check ==========\n")

# --- VolatilityNet ---
print("1. Loading VolatilityNet (PyTorch LSTM)...")
try:
    v = _load_volatility_lstm()
    if v:
        print("   SUCCESS: VolatilityNet initialized and weights loaded.")
    else:
        print("   SKIPPED: VolatilityNet returned None (weights file missing — expected in dev).")
except Exception as e:
    print(f"   FAILED: {e}")

# --- ChronosNet ---
print("\n2. Loading ChronosNet (amazon/chronos-t5-base)...")
try:
    c = _load_chronos_net()
    if c:
        print("   SUCCESS: ChronosNet foundation model loaded.")
        # Quick smoke test with dummy prices
        test_prices = [100.0, 101.2, 99.8, 102.5, 103.0, 101.0, 104.2, 105.0, 103.5, 106.0]
        result = c.predict(test_prices, horizon_steps=5)
        print(f"   Smoke test (10 prices -> 5-step forecast): {result}")
    else:
        print("   FAILED: ChronosNet returned None. Check logs above for details.")
except Exception as e:
    print(f"   FAILED: {e}")

print("\n================================================")
