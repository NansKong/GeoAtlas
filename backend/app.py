import spaces

@spaces.GPU
def _zero_gpu_init():
    """Satisfies Hugging Face ZeroGPU runtime requirement."""
    return "ZeroGPU Online"

import os
import gradio as gr
from main import app as fastapi_app   # FastAPI instance with all routers

# ── Gradio dashboard ─────────────────────────────────────────────────────────
with gr.Blocks(title="GeoAtlas Intelligence API") as demo:
    gr.Markdown(
        """
        # 🌍 GeoAtlas Intelligence API

        The GeoAtlas backend service is **Online and Healthy** 🟢

        * 📖 **Interactive Swagger UI:** [Open /docs](/docs)
        * 📘 **ReDoc Documentation:** [Open /redoc](/redoc)
        * 🩺 **System Health Check:** [Open /health](/health)
        * ⚡ **API Base Route:** `/api/v1`
        """
    )
    _gpu_btn = gr.Button("Warmup GPU", visible=False)
    _gpu_btn.click(fn=_zero_gpu_init)
    demo.load(fn=_zero_gpu_init)

# ── Launch: Gradio owns the single uvicorn server on port 7860 ───────────────
# On HF Spaces, `python app.py` is executed directly. We use demo.launch() with
# the FastAPI app mounted so that ALL routes (/api/v1, /docs, /health) and the
# Gradio UI share a single uvicorn process on port 7860 — no double-bind.
demo.launch(
    server_name="0.0.0.0",
    server_port=int(os.getenv("PORT", 7860)),
    app=fastapi_app,   # FastAPI routes are surfaced through Gradio's uvicorn
)
