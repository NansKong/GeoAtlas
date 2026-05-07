from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from core.config import settings
from core.metrics import collect_metrics_text
from modules.users.router import billing_router, institutional_router, router as auth_router, users_router
from modules.events.router import router as events_router, news_router
from modules.market.router import router as market_router
from modules.market.service import market_stream_manager
from modules.boards.router import alerts_router, router as boards_router, pins_router
from modules.predictions.router import router as predictions_router
import asyncio
from workers.market_snapshot import run_snapshot_loop, db_buffer

_snapshot_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    global _snapshot_task
    print(f"🌍 GeoAtlas API starting — env: {settings.APP_ENV}")
    await market_stream_manager.start()

    # Start the DB write buffer flush loop
    db_buffer.start()

    _snapshot_task = asyncio.create_task(run_snapshot_loop(), name="market-snapshot-worker")
    print("✅ Created snapshot task in lifespan!")
    yield

    # ── Shutdown (signal-safe) ───────────────────────────────────────────────
    print("⏳ GeoAtlas shutting down — draining buffers...")

    # 1. Cancel the snapshot loop
    if _snapshot_task:
        _snapshot_task.cancel()
        try:
            await _snapshot_task
        except asyncio.CancelledError:
            pass

    # 2. Drain the DB buffer (flush remaining records)
    await db_buffer.drain()

    # 3. Shutdown market stream
    await market_stream_manager.shutdown()

    # 4. Close the global HTTP client
    from core.http import close_global_client
    await close_global_client()

    print("✅ GeoAtlas API shut down cleanly")


app = FastAPI(
    title="GeoAtlas API",
    description="Geopolitical Intelligence + Market Prediction Platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(institutional_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(news_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(boards_router, prefix="/api/v1")
app.include_router(pins_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")


# ─── Health (Enhanced) ───────────────────────────────────────────────────────

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

    # Determine overall status
    open_circuits = [
        name for name, ctx in PROVIDERS.items()
        if ctx.breaker.state == CircuitState.OPEN
    ]
    status = "degraded" if open_circuits else "ok"

    return {
        "status": status,
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


@app.get("/", tags=["Root"])
async def root():
    return {"message": "GeoAtlas API — visit /docs for Swagger UI"}
