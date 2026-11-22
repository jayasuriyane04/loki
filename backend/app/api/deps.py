from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_token
from app.db.models import Session, User
from app.db.session import get_db

_TOUCH_INTERVAL = timedelta(minutes=5)


async def resolve_session(db: AsyncSession, token: str | None) -> Session | None:
    """Return the live session for a cookie token, or None. Shared by HTTP and WebSocket auth."""
    if not token:
        return None
    now = datetime.now(UTC)
    sess = await db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if sess is None or sess.revoked_at is not None or sess.expires_at <= now or not sess.user.is_active:
        return None
    if now - sess.last_seen_at > _TOUCH_INTERVAL:
        sess.last_seen_at = now
        await db.commit()
    return sess


async def current_session(request: Request, db: AsyncSession = Depends(get_db)) -> Session:
    sess = await resolve_session(db, request.cookies.get(get_settings().session_cookie_name))
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return sess


async def current_user(sess: Session = Depends(current_session)) -> User:
    return sess.user
