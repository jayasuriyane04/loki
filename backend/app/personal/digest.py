"""Conversation digests: when a conversation has gone quiet, LOKI writes a short dated episodic memory of it.

This is what makes "the project we discussed yesterday" or "the issue we hit with the database" answerable: Phase 3
memory stores facts from single messages; digests remember conversations as a whole (topic, decisions, problems,
what was left open). Runs only for users who allow memory, digests and background processing.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select

from app.db.models import Conversation, Memory, Message, User
from app.db.session import SessionLocal
from app.llm.base import ChatMessage, LLMError
from app.memory import store
from app.memory.secrets import find_secrets, redact
from app.personal.preferences import load as load_prefs

log = logging.getLogger(__name__)

IDLE = timedelta(minutes=15)
MIN_MESSAGES = 4

DIGEST_PROMPT = """You write LOKI's long-term memory of a finished conversation with {name}. In 1-3 sentences, starting
with "On {date}, {name} and LOKI", say what it was about, any decisions made, problems hit and how they were
resolved, and anything left open. Third person, plain prose. Only include what {name} said, asked for or agreed to,
not LOKI's general explanations. Never include passwords, keys or other secrets. If nothing worth remembering
happened (small talk, a one-off question), reply with exactly: NOTHING"""


async def digest_pending(llm, embeddings, *, limit: int = 5, now: datetime | None = None) -> int:
    """Digest up to `limit` conversations that went quiet and changed since their last digest. Returns how many."""
    now = now or datetime.now(UTC)
    done = 0
    async with SessionLocal() as db:
        counts = (select(Message.conversation_id, func.count().label("n"))
                  .where(Message.role.in_(("user", "assistant"))).group_by(Message.conversation_id).subquery())
        candidates = list(await db.scalars(
            select(Conversation).join(counts, counts.c.conversation_id == Conversation.id)
            .where(Conversation.is_temporary.is_(False), counts.c.n >= MIN_MESSAGES,
                   Conversation.updated_at < now - IDLE,
                   or_(Conversation.digested_at.is_(None), Conversation.digested_at < Conversation.updated_at))
            .order_by(Conversation.updated_at).limit(limit * 3)))
        for conv in candidates:
            if done >= limit:
                break
            prefs = await load_prefs(db, conv.user_id)
            if not (prefs.background_processing and prefs.proactive.conversation_digests
                    and await store.memory_enabled(db, conv.user_id)):
                conv.digested_at = now  # respect the choice; don't re-check every tick
                continue
            user = await db.get(User, conv.user_id)
            msgs = list(await db.scalars(select(Message).where(
                Message.conversation_id == conv.id, Message.role.in_(("user", "assistant")))
                .order_by(Message.created_at.desc()).limit(30)))
            transcript = "\n".join(
                f"{user.display_name if m.role == 'user' else 'LOKI'}: {redact(m.content)[:400]}" for m in reversed(msgs))
            try:
                text = (await llm.complete([
                    ChatMessage("system", DIGEST_PROMPT.format(name=user.display_name, date=f"{conv.updated_at:%d %B %Y}")),
                    ChatMessage("user", transcript),
                ], max_tokens=200)).strip()
            except LLMError as e:
                log.warning("digest failed", extra={"error": str(e)})
                break  # model down: try again next tick
            conv.digested_at = now
            if not text or text.upper().startswith("NOTHING") or find_secrets(text) or len(text) > 800:
                await db.commit()
                continue
            vec = (await embeddings.embed_documents([text]))[0]
            existing = await db.scalar(select(Memory).where(
                Memory.source_conversation_id == conv.id, Memory.source == "summary"))
            if existing:  # the conversation continued: replace the old digest
                existing.content, existing.embedding, existing.event_at = text, vec, conv.updated_at
                existing.project = conv.project
            else:
                db.add(Memory(user_id=conv.user_id, kind="episodic", content=text, importance=0.6,
                              project=conv.project, source="summary", source_conversation_id=conv.id,
                              event_at=conv.updated_at, embedding=vec, embedding_model=embeddings.model, use_count=0))
            await db.commit()
            done += 1
            log.info("conversation digested", extra={"conversation_id": str(conv.id), "project": conv.project})
        await db.commit()  # persist digested_at for conversations skipped by preference
    return done
