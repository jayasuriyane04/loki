import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import current_user
from app.db.models import Conversation, User
from app.db.session import get_db
from app.schemas import ConversationCreate, ConversationDetail, ConversationSummary, ConversationUpdate

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


async def get_owned_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, *, with_messages: bool = False
) -> Conversation | None:
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    if with_messages:
        stmt = stmt.options(selectinload(Conversation.messages))
    return await db.scalar(stmt)


async def _owned_or_404(db: AsyncSession, user: User, cid: uuid.UUID, with_messages: bool = False) -> Conversation:
    conv = await get_owned_conversation(db, user.id, cid, with_messages=with_messages)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.is_temporary.is_(False))
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.post("", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    conv = Conversation(user_id=user.id, title=body.title or "New conversation", is_temporary=body.is_temporary)
    db.add(conv)
    await db.commit()
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    return await _owned_or_404(db, user, conversation_id, with_messages=True)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _owned_or_404(db, user, conversation_id)
    conv.title = body.title.strip()
    await db.commit()
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    conv = await _owned_or_404(db, user, conversation_id)
    await db.delete(conv)
    await db.commit()
