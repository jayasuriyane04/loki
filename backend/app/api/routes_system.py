from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.db.session import get_db
from app.llm.router import LLMRouter
from app.schemas import ModelsOut, ProviderStatus

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/voice", dependencies=[Depends(current_user)])
async def voice_status(request: Request):
    """Speech recognition / synthesis providers, their load state, and available voices."""
    return request.app.state.voice.describe()


@router.get("/models", response_model=ModelsOut, dependencies=[Depends(current_user)])
async def models(request: Request):
    llm: LLMRouter = request.app.state.llm
    primary, fallback = await llm.health()
    return ModelsOut(
        primary=ProviderStatus(**asdict(primary)),
        fallback=ProviderStatus(**asdict(fallback)) if fallback else None,
    )
