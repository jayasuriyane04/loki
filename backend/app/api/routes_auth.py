import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_session, current_user
from app.core.config import get_settings
from app.core.ratelimit import login_limiter, register_limiter
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.db.models import Session, User
from app.db.session import get_db
from app.schemas import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _start_session(db: AsyncSession, user: User, request: Request, response: Response) -> None:
    s = get_settings()
    token = new_session_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            user_agent=(request.headers.get("user-agent") or "")[:255],
            expires_at=datetime.now(UTC) + timedelta(hours=s.session_ttl_hours),
        )
    )
    await db.commit()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    if not register_limiter.hit(_client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-ups from this address. Try later.")
    user = User(email=body.email.lower(), display_name=body.display_name, password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.") from None
    log.info("user registered", extra={"user_id": str(user.id)})
    await _start_session(db, user, request, response)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()
    key = f"{_client_ip(request)}|{email}"
    if not login_limiter.hit(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-in attempts. Wait a few minutes.")
    user = await db.scalar(select(User).where(User.email == email))
    if not verify_password(body.password, user.password_hash if user else None) or not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    login_limiter.reset(key)
    await _start_session(db, user, request, response)
    log.info("user logged in", extra={"user_id": str(user.id)})
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    db_sess = await db.get(Session, sess.id)
    if db_sess:
        db_sess.revoked_at = datetime.now(UTC)
        await db.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user
