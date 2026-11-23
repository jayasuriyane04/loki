"""Developer dashboard data: live metrics from traces, offline evaluation reports, and message feedback."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.observability import metrics
from app.observability.trace import sink

router = APIRouter(prefix="/api", tags=["metrics"])


@router.get("/metrics/summary")
async def metrics_summary(days: int = Query(7, ge=1, le=90), user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    await sink.flush()  # include what happened in the last few seconds
    return await metrics.summary(db, user.id, days)


@router.get("/metrics/traces")
async def metrics_traces(limit: int = Query(30, ge=1, le=200), user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    await sink.flush()
    return await metrics.recent_traces(db, user.id, limit)


@router.get("/metrics/evals/{name}")
async def metrics_eval(name: str, user: User = Depends(current_user)):
    report = metrics.eval_report(name)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return report


class FeedbackIn(BaseModel):
    rating: int | None = Field(None, ge=-1, le=1, description="1 = helpful, -1 = not helpful, null = clear")
    note: str | None = Field(None, max_length=1000)


@router.post("/messages/{message_id}/feedback", status_code=204)
async def message_feedback(message_id: uuid.UUID, body: FeedbackIn, user: User = Depends(current_user),
                           db: AsyncSession = Depends(get_db)):
    msg = await db.scalar(select(Message).join(Conversation, Conversation.id == Message.conversation_id).where(
        Message.id == message_id, Conversation.user_id == user.id, Message.role == "assistant"))
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    msg.feedback = body.rating or None
    msg.feedback_note = (body.note or "").strip() or None if body.rating else None
    await db.commit()
