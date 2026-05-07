# GeoAtlas — Remaining Development Tasks
> Excluding Phase 6 (Hardening & Scaling)

## Phase 4 — Prediction Engine (Finalization)

### 1. Production Inference Pipeline
- [x] **Unified Inference Engine**: Integrate `xgboost_regime.joblib` into `backend/workers/model_runtime.py`.
- [x] **Live Feature State (Redis)**: Implement a worker to maintain real-time rolling aggregates (7d volatility, sentiment momentum) required by the model.
- [x] **Veto & Ranking Server**: Port the "Top-K" and "Sentiment-Trend Veto" logic into the production inference worker.

### 2. Advanced Model Expansion
- [x] **VolatilityNet (Deep Learning)**: Implement the standalone PyTorch LSTM for secondary volatility spike confirmation.
- [x] **ChronosNet**: Integrate `amazon/chronos-t5-base` for raw price trajectory forecasting via HuggingFace.

### 3. Loop Closure & Validation
- [x] **Verification Task**: Finalize the Celery script `verify_event_outcome` to settle every prediction's success/failure after the T+1d horizon.
- [x] **Accuracy API**: Create `/predictions/accuracy` endpoint to feed the UI with real-time precision/recall metrics.

---

## Phase 5 — Platform Features

### 1. Alerting Infrastructure
- [ ] **Signal → Alert Hook**: Background task to check every new model prediction against user-defined asset/confidence thresholds.
- [ ] **Email Provider**: Implement SendGrid adapter for critical geopolitical alerts.
- [ ] **Web Push**: Implement Firebase cloud messaging (FCM) for real-time dashboard notifications.

### 2. Visual Intelligence
- [ ] **Macro Dashboard**: Build the high-level interactive world map for visualizing the global "Geopolitical Heatmap."
- [ ] **Prediction History UI**: Finalize the "closed-loop" view where users see their past predictions and how they actually performed.
- [ ] **Multi-Asset Panel**: Update the frontend asset view to support the newly added TradFi (AAPL/SPY) context alongside Crypto.

---

## High-Impact Immediate Targets
1. **Model Deployment**: Moving XGBoost from a `.py` script into the live ingestion flow.
2. **Outcome Settlement**: Writing the code that tells us "We were right/wrong" for yesterday's prediction.
3. **The Multi-Asset Map**: Visualizing how global news is causing cross-asset correlations on the frontend.
