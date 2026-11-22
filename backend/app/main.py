import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_auth, routes_conversations, routes_system, ws
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.db.models import Base
from app.db.session import engine
from app.llm.router import LLMRouter
from app.voice.manager import VoiceManager

settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("loki")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app.state.llm = LLMRouter.from_settings(settings)
    # Background; never blocks start-up.
    warm = asyncio.create_task(app.state.llm.primary.warmup() if settings.llm_warmup else asyncio.sleep(0))
    app.state.voice = VoiceManager.from_settings(settings)
    app.state.voice.start()  # loads STT/TTS in the background; the API is usable immediately
    log.info(
        "LOKI backend started",
        extra={
            "primary": f"{settings.llm_primary_provider}/{settings.llm_primary_model}",
            "fallback": f"{settings.llm_fallback_provider}/{settings.llm_fallback_model}"
            if settings.llm_fallback_provider
            else None,
            "database": settings.database_url.split("://")[0],
        },
    )
    yield
    warm.cancel()
    await app.state.voice.stop()
    await app.state.llm.aclose()
    await engine.dispose()


app = FastAPI(title="LOKI API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"path": request.url.path})
        response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
    duration = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = rid
    log.info(
        "request",
        extra={"method": request.method, "path": request.url.path, "status": response.status_code, "ms": duration},
    )
    request_id_var.reset(token)
    return response


app.include_router(routes_auth.router)
app.include_router(routes_conversations.router)
app.include_router(routes_system.router)
app.include_router(ws.router)
