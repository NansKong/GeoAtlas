import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import gradio as gr

try:
    import spaces
    @spaces.GPU
    def _zero_gpu_init():
        """Satisfies Hugging Face ZeroGPU runtime requirement."""
        return "ZeroGPU Online"
except ImportError:
    def _zero_gpu_init():
        return "Local Online"

# ── Import FastAPI routers ──────────────────────────────────────────────────
from core.config import settings
from core.metrics import collect_metrics_text
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from modules.users.router import billing_router, institutional_router, router as auth_router, users_router
from modules.events.router import router as events_router, news_router
from modules.market.router import router as market_router
from modules.market.service import market_stream_manager
from modules.boards.router import alerts_router, router as boards_router, pins_router
from modules.predictions.router import router as predictions_router
from workers.market_snapshot import run_snapshot_loop, db_buffer

# ── Gradio UI ─────────────────────────────────────────────────────────────────
with gr.Blocks(title="GeoAtlas Intelligence API") as demo:
    gr.Markdown(
        """
        # [GeoAtlas] Intelligence API

        The GeoAtlas backend service is **Online and Healthy**

        * Interactive Swagger UI: [Open /docs](/docs)
        * ReDoc Documentation: [Open /redoc](/redoc)
        * System Health Check: [Open /health](/health)
        * API Base Route: `/api/v1`
        """
    )
    _gpu_btn = gr.Button("Warmup GPU", visible=False)
    _gpu_btn.click(fn=_zero_gpu_init)
    demo.load(fn=_zero_gpu_init)

_snapshot_task = None

@asynccontextmanager
async def _lifespan(fastapi_app):
    global _snapshot_task
    print(f"[GeoAtlas] API starting - env: {settings.APP_ENV}")
    await market_stream_manager.start()
    db_buffer.start()
    _snapshot_task = asyncio.create_task(run_snapshot_loop(), name="market-snapshot-worker")
    print("[GeoAtlas] Created snapshot task in lifespan!")
    yield
    print("[GeoAtlas] Shutting down - draining buffers...")
    if _snapshot_task:
        _snapshot_task.cancel()
        try:
            await _snapshot_task
        except asyncio.CancelledError:
            pass
    await db_buffer.drain()
    await market_stream_manager.shutdown()
    from core.http import close_global_client
    await close_global_client()
    print("[GeoAtlas] API shut down cleanly")


def _configure_fastapi_app(app):
    """Configures CORS, /health, /metrics, and all /api/v1 routers on the target FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router,          prefix="/api/v1")
    app.include_router(users_router,         prefix="/api/v1")
    app.include_router(billing_router,       prefix="/api/v1")
    app.include_router(institutional_router, prefix="/api/v1")
    app.include_router(events_router,        prefix="/api/v1")
    app.include_router(news_router,          prefix="/api/v1")
    app.include_router(market_router,        prefix="/api/v1")
    app.include_router(predictions_router,   prefix="/api/v1")
    app.include_router(boards_router,        prefix="/api/v1")
    app.include_router(pins_router,          prefix="/api/v1")
    app.include_router(alerts_router,        prefix="/api/v1")

    @app.get("/health", tags=["Health"])
    async def health():
        from core.http import PROVIDERS, CircuitState
        from core.market_cache import get_market_snapshot

        snapshot = await get_market_snapshot()
        last_updated = snapshot.get("last_updated")
        snapshot_age = None
        if last_updated:
            try:
                dt = datetime.fromisoformat(last_updated)
                snapshot_age = round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
            except Exception:
                pass

        open_circuits = [
            name for name, ctx in PROVIDERS.items()
            if ctx.breaker.state == CircuitState.OPEN
        ]
        return {
            "status": "degraded" if open_circuits else "ok",
            "version": "0.1.0",
            "env": settings.APP_ENV,
            "snapshot_age_sec": snapshot_age,
            "db_buffer_size": db_buffer.size,
            "providers": {
                name: {
                    "health_score": round(ctx.health.get_composite_score(), 3),
                    "circuit": ctx.breaker.state.name,
                    "limiter_delay": round(ctx.limiter.delay, 4),
                    "latency_ema_ms": round(ctx.health.latency_ema, 1),
                }
                for name, ctx in PROVIDERS.items()
            },
            "open_circuits": open_circuits,
        }

    @app.get("/metrics", tags=["Observability"])
    async def metrics():
        payload = collect_metrics_text()
        return Response(content=payload, media_type="text/plain; version=0.0.4; charset=utf-8")


# Intercept Gradio's App.create_app so that when demo.launch() builds the server app,
# all our FastAPI routers, middleware, and endpoints are attached directly to it!
_orig_create_app = gr.routes.App.create_app

def _custom_create_app(*args, **kwargs):
    app = _orig_create_app(*args, **kwargs)
    _configure_fastapi_app(app)
    return app

gr.routes.App.create_app = _custom_create_app


# ── HF Spaces launches this file with `python app.py` ───────────────────────
if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", 7860)),
        show_error=True,
        app_kwargs={"lifespan": _lifespan},
    )
