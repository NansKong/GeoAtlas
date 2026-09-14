import spaces

@spaces.GPU
def _zero_gpu_init():
    """Satisfies Hugging Face ZeroGPU runtime requirement."""
    return "ZeroGPU Online"

import os
import uvicorn
import gradio as gr
from main import app

# Create a clean status dashboard for the Hugging Face Space UI
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

# Mount Gradio at root so Hugging Face Space displays the dashboard,
# while FastAPI handles all API routes (/api/v1, /docs, /health, /ws)
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
