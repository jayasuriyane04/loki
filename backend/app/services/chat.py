import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_conversations import get_owned_conversation
from app.core.config import Settings
from app.db.models import Conversation, Message, User
from app.llm.base import ChatMessage, LLMError, StreamChunk
from app.llm.router import LLMRouter, StreamStarted
from app.knowledge.service import KnowledgeService, attach_citations
from app.memory import store
from app.memory.service import MemoryService
from app.schemas import ConversationSummary, MessageOut, WSUserMessage
from app.services.prompts import build_system_prompt, title_from_message

log = logging.getLogger(__name__)

Send = Callable[[dict[str, Any]], Awaitable[None]]
HISTORY_LOOKBACK = 60


class TurnError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_context(system_prompt: str, history: list[Message], char_budget: int) -> list[ChatMessage]:
    """System prompt + the most recent turns that fit the budget (oldest dropped first).

    `history` is chronological and already ends with the new user message.
    """
    picked: list[ChatMessage] = []
    used = 0
    for m in reversed(history):
        if m.role not in ("user", "assistant") or not m.content.strip() or m.status == "error":
            continue
        if used + len(m.content) > char_budget and picked:
            break
        picked.append(ChatMessage(role=m.role, content=m.content))  # type: ignore[arg-type]
        used += len(m.content)
    picked.reverse()
    # Most providers require the dialogue to start with a user turn.
    while picked and picked[0].role != "user":
        picked.pop(0)
    return [ChatMessage(role="system", content=system_prompt), *picked]


@dataclass
class TurnResult:
    """What post-turn work (memory extraction, compression) needs to know about a finished turn."""

    conversation_id: uuid.UUID
    temporary: bool
    memory_on: bool
    user_text: str
    assistant_text: str
    assistant_status: str


class ChatService:
    def __init__(
        self,
        llm: LLMRouter,
        settings: Settings,
        memory: MemoryService | None = None,
        knowledge: KnowledgeService | None = None,
    ) -> None:
        self.llm = llm
        self.settings = settings
        self.memory = memory
        self.knowledge = knowledge

    async def _resolve_conversation(
        self, db: AsyncSession, user: User, msg: WSUserMessage, send: Send
    ) -> Conversation:
        if msg.conversation_id is not None:
            conv = await get_owned_conversation(db, user.id, msg.conversation_id)
            if conv is None:
                raise TurnError("not_found", "Conversation not found.")
            if conv.title == "New conversation":
                has_messages = await db.scalar(select(Message.id).where(Message.conversation_id == conv.id).limit(1))
                if not has_messages:
                    conv.title = title_from_message(msg.content)
            return conv
        conv = Conversation(user_id=user.id, title=title_from_message(msg.content), is_temporary=msg.temporary)
        db.add(conv)
        await db.flush()
        await send({"type": "conversation", "conversation": _dump(ConversationSummary, conv)})
        return conv

    async def run_turn(
        self,
        db: AsyncSession,
        user: User,
        msg: WSUserMessage,
        send: Send,
        on_delta: Callable[[str, str], None] | None = None,
    ) -> TurnResult | None:
        """Run one user→assistant turn. `on_delta(message_id, text)` receives every streamed text piece (used for TTS)."""
        content = msg.content.strip()
        if not content:
            raise TurnError("bad_request", "Message is empty.")
        if len(content) > self.settings.max_message_chars:
            raise TurnError("bad_request", f"Message too long (max {self.settings.max_message_chars} characters).")

        conv = await self._resolve_conversation(db, user, msg, send)
        user_msg = Message(conversation_id=conv.id, role="user", content=content, input_mode=msg.input_mode)
        db.add(user_msg)
        conv.updated_at = datetime.now(UTC)
        await db.commit()
        await send({"type": "message_saved", "conversation_id": str(conv.id), "message": _dump(MessageOut, user_msg)})

        q = select(Message).where(Message.conversation_id == conv.id)
        if conv.summary_until is not None:  # older turns live in conv.summary
            q = q.where(Message.created_at > conv.summary_until)
        rows = await db.scalars(q.order_by(Message.created_at.desc()).limit(HISTORY_LOOKBACK))
        history = list(reversed(list(rows)))

        # Temporary chats neither read nor write long-term memory; nor does a user who turned memory off.
        memory_on = (
            self.memory is not None
            and self.settings.memory_extraction
            and not conv.is_temporary
            and await store.memory_enabled(db, user.id)
        )
        recall = None
        if memory_on:
            await send({"type": "state", "state": "retrieving"})
            recall = await self.memory.recall(db, user, content)  # type: ignore[union-attr]
            if recall.used:
                await send(
                    {
                        "type": "memories_used",
                        "conversation_id": str(conv.id),
                        "memories": [{"id": str(m.id), "kind": m.kind, "content": m.content} for m in recall.used],
                    }
                )
        # The user's own documents are searched in every chat, temporary ones included (they are not "memory").
        docs = None
        if self.knowledge is not None:
            if not memory_on:
                await send({"type": "state", "state": "retrieving"})
            docs = await self.knowledge.retrieve(db, user.id, content)
        system = build_system_prompt(
            user.display_name,
            voice=msg.input_mode == "voice",
            memory_block=recall.block if recall else None,
            documents_block=docs.block if docs else None,
            conversation_summary=conv.summary,
            temporary=conv.is_temporary,
        )
        context = build_context(system, history, self.settings.context_char_budget)

        sources = docs.sources if docs else []
        await send({"type": "state", "state": "processing"})
        assistant = Message(id=uuid.uuid4(), conversation_id=conv.id, role="assistant", content="")
        parts: list[str] = []
        started = time.perf_counter()
        began = False
        reasoning_announced = False
        try:
            async for item in self.llm.stream(context):
                if isinstance(item, StreamStarted):
                    began = True
                    assistant.provider, assistant.model = item.provider, item.model
                    await send(
                        {
                            "type": "assistant_start",
                            "conversation_id": str(conv.id),
                            "message_id": str(assistant.id),
                            "provider": item.provider,
                            "model": item.model,
                            "fell_back": item.fell_back,
                        }
                    )
                    continue
                chunk: StreamChunk = item
                if chunk.reasoning:
                    if not reasoning_announced:
                        reasoning_announced = True
                        await send({"type": "state", "state": "thinking"})
                    continue
                if chunk.delta:
                    if assistant.first_token_ms is None:
                        assistant.first_token_ms = _ms_since(started)
                    parts.append(chunk.delta)
                    if on_delta:
                        on_delta(str(assistant.id), chunk.delta)
                    await send({"type": "token", "message_id": str(assistant.id), "delta": chunk.delta})
                if chunk.done:
                    assistant.prompt_tokens = chunk.prompt_tokens
                    assistant.completion_tokens = chunk.completion_tokens
            assistant.status = "complete" if parts else "error"
        except asyncio.CancelledError:
            assistant.status = "interrupted"
            await self._finish(db, conv, assistant, parts, started, send, began, sources)
            raise
        except LLMError as e:
            log.warning("llm failure", extra={"provider": e.provider, "error": str(e), "began": began})
            if not began:
                raise TurnError("llm_unavailable", str(e)) from e
            assistant.status = "error"
            await self._finish(db, conv, assistant, parts, started, send, began, sources)
            await send({"type": "error", "code": "llm_stream_failed", "message": str(e)})
            return
        await self._finish(db, conv, assistant, parts, started, send, began, sources)
        if not parts:
            await send(
                {
                    "type": "error",
                    "code": "empty_reply",
                    "message": "The model returned no answer (it may have spent its output budget on reasoning).",
                }
            )
            return None
        return TurnResult(conv.id, conv.is_temporary, memory_on, content, assistant.content, assistant.status)

    async def _finish(
        self,
        db: AsyncSession,
        conv: Conversation,
        assistant: Message,
        parts: list[str],
        started: float,
        send: Send,
        began: bool,
        sources: list[dict] | None = None,
    ) -> None:
        if not began:
            return
        assistant.content = "".join(parts)
        assistant.latency_ms = _ms_since(started)
        if sources:
            # Only numbers that match a passage the model was actually shown count as citations.
            assistant.citations, invented = attach_citations([dict(s) for s in sources], assistant.content)
            if invented:
                log.warning("model cited passages that don't exist", extra={"numbers": invented})
        db.add(assistant)
        conv.updated_at = datetime.now(UTC)
        await db.commit()
        log.info(
            "assistant turn finished",
            extra={
                "conversation_id": str(conv.id),
                "status": assistant.status,
                "provider": assistant.provider,
                "model": assistant.model,
                "latency_ms": assistant.latency_ms,
                "first_token_ms": assistant.first_token_ms,
                "completion_tokens": assistant.completion_tokens,
            },
        )
        try:
            await send({"type": "assistant_end", "message": _dump(MessageOut, assistant)})
        except Exception:  # client may already be gone (e.g. cancel on disconnect)
            pass


def _ms_since(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)


def _dump(model: type, obj: object) -> dict[str, Any]:
    return model.model_validate(obj).model_dump(mode="json")
