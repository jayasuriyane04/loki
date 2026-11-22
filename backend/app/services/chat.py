import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_conversations import get_owned_conversation
from app.core.config import Settings
from app.db.models import Conversation, Message, User
from app.llm.base import ChatMessage, LLMError, StreamChunk
from app.llm.router import LLMRouter, StreamStarted
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


class ChatService:
    def __init__(self, llm: LLMRouter, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

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
    ) -> None:
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

        rows = await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LOOKBACK)
        )
        history = list(reversed(list(rows)))
        system = build_system_prompt(user.display_name, voice=msg.input_mode == "voice")
        context = build_context(system, history, self.settings.context_char_budget)

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
            await self._finish(db, conv, assistant, parts, started, send, began)
            raise
        except LLMError as e:
            log.warning("llm failure", extra={"provider": e.provider, "error": str(e), "began": began})
            if not began:
                raise TurnError("llm_unavailable", str(e)) from e
            assistant.status = "error"
            await self._finish(db, conv, assistant, parts, started, send, began)
            await send({"type": "error", "code": "llm_stream_failed", "message": str(e)})
            return
        await self._finish(db, conv, assistant, parts, started, send, began)
        if not parts:
            await send(
                {
                    "type": "error",
                    "code": "empty_reply",
                    "message": "The model returned no answer (it may have spent its output budget on reasoning).",
                }
            )

    async def _finish(
        self,
        db: AsyncSession,
        conv: Conversation,
        assistant: Message,
        parts: list[str],
        started: float,
        send: Send,
        began: bool,
    ) -> None:
        if not began:
            return
        assistant.content = "".join(parts)
        assistant.latency_ms = _ms_since(started)
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
