import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_auth,
    routes_conversations,
    routes_knowledge,
    routes_memory,
    routes_personal,
    routes_productivity,
    routes_system,
    ws,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.db import migrate
from app.db.session import engine
from app.agent.notify import Notifier, ProactiveScheduler
from app.personal.folders import FolderWatcher
from app.knowledge.ingest import Ingestor
from app.tools.builtin.system import LOG_BUFFER
from app.tools.registry import load_builtin_tools
from app.knowledge.rerank import OnnxCrossEncoder
from app.knowledge.service import KnowledgeService
from app.llm.embeddings import build_embeddings
from app.llm.router import LLMRouter
from app.memory.service import MemoryService
from app.voice.manager import VoiceManager

settings = get_settings()
configure_logging(settings.log_level)
logging.getLogger().addHandler(LOG_BUFFER)  # lets the read_app_logs tool inspect recent logs
load_builtin_tools()
log = logging.getLogger("loki")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_migrate:
        # Alembic's env runs its own event loop, so it gets a worker thread.
        await asyncio.to_thread(migrate.upgrade, settings.database_url)
    app.state.llm = LLMRouter.from_settings(settings)
    # Background; never blocks start-up.
    warm = asyncio.create_task(app.state.llm.primary.warmup() if settings.llm_warmup else asyncio.sleep(0))
    app.state.embeddings = build_embeddings(settings)
    app.state.memory = MemoryService(app.state.llm, app.state.embeddings, settings)
    app.state.background = set()  # post-turn memory tasks
    reranker = OnnxCrossEncoder(settings.rerank_model_dir) if settings.rerank_model_dir else None
    app.state.knowledge = KnowledgeService(app.state.embeddings, reranker, settings)
    app.state.ingestor = Ingestor(app.state.embeddings, settings)
    await app.state.ingestor.start()  # re-queues documents left unfinished by a previous run
    rerank_load = asyncio.create_task(reranker.load() if reranker else asyncio.sleep(0))
    app.state.notifier = Notifier()
    app.state.folders = FolderWatcher(app.state.ingestor, app.state.notifier)
    app.state.scheduler = ProactiveScheduler(app.state.notifier, reminder_poll_s=settings.reminder_poll_s, services={
        "llm": app.state.llm, "embeddings": app.state.embeddings, "knowledge": app.state.knowledge,
        "folder_watcher": app.state.folders,
    })
    app.state.scheduler.start()  # also delivers reminders that fell due while LOKI was off
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
    rerank_load.cancel()
    await app.state.scheduler.stop()
    await app.state.ingestor.stop()
    for t in list(app.state.background):
        t.cancel()
    await asyncio.gather(*app.state.background, return_exceptions=True)
    await app.state.embeddings.aclose()
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
app.include_router(routes_memory.router)
app.include_router(routes_knowledge.router)
app.include_router(routes_productivity.router)
app.include_router(routes_personal.router)
app.include_router(routes_system.router)
app.include_router(ws.router)
