"""Sign in, sign out, the own profile and sessions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select

from ..config import get_settings
from ..deps import COOKIE_NAME, CurrentUser, DbSession, error
from ..models import Notice, OidcProvider, Session, User, utcnow
from ..schemas import LoginBody, MePatch, PasswordBody, UserPublic
from ..security import (
    create_session_token,
    has_usable_password,
    hash_password,
    now_ms,
    verify_password,
)
from ..services import login_guard

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger("nexdeck.auth")


def cookie_secure(request: Request) -> bool:
    mode = get_settings().cookie_secure
    if mode == "always":
        return True
    if mode == "never":
        return False
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.session_days * 86400, path=settings.url_base or "/",
        httponly=True, samesite="lax", secure=cookie_secure(request),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=get_settings().url_base or "/", httponly=True)


def user_public(user: User, request: Request | None = None) -> UserPublic:
    return UserPublic(
        id=user.id, username=user.username, display_name=user.display_name or user.username, role=user.role,
        locale=user.locale, theme=user.theme, start_board_id=user.start_board_id, disabled=user.disabled,
        seen_version=user.seen_version, has_password=has_usable_password(user.password_hash),
        auth_kind=getattr(request.state, "auth_kind", "session") if request is not None else "session",
    )


def open_session(db: DbSession, user: User, request: Request, response: Response) -> None:
    session = Session(user_id=user.id, user_agent=request.headers.get("user-agent", "")[:300])
    db.add(session)
    db.commit()
    set_session_cookie(response, request, create_session_token(user.id, session.id))


@router.post("/login", response_model=UserPublic, summary="Sign in with user name and password")
def login(body: LoginBody, request: Request, response: Response, db: DbSession) -> UserPublic:
    """Opens a browser session. Wrong attempts are throttled per address."""
    address = request.client.host if request.client else "?"
    login_guard.check(address)
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        login_guard.failed(address)
        logger.info("Sign-in refused for %r from %s.", body.username, address)
        raise error("bad_credentials", "User name or password is wrong.", status.HTTP_401_UNAUTHORIZED)
    login_guard.succeeded(address)
    open_session(db, user, request, response)
    return user_public(user, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of this browser")
def logout(request: Request, response: Response, db: DbSession) -> None:
    from ..security import read_session_token

    raw = request.cookies.get(COOKIE_NAME)
    claims = read_session_token(raw) if raw else None
    if claims is not None:
        session = db.get(Session, claims.session_id)
        if session is not None:
            session.revoked = True
            db.commit()
    clear_session_cookie(response)


@router.get("/me", response_model=UserPublic, summary="Who am I")
def me(user: CurrentUser, request: Request) -> UserPublic:
    return user_public(user, request)


@router.patch("/me", response_model=UserPublic, summary="Change own profile settings")
def patch_me(body: MePatch, user: CurrentUser, request: Request, db: DbSession) -> UserPublic:
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.locale is not None:
        user.locale = body.locale
    if body.theme is not None:
        user.theme = body.theme
    if body.start_board_id is not None:
        user.start_board_id = body.start_board_id or None
    if body.seen_version is not None:
        user.seen_version = body.seen_version
    db.commit()
    return user_public(user, request)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change own password")
def change_password(body: PasswordBody, user: CurrentUser, db: DbSession) -> None:
    """Every other session of the account is signed out afterwards."""
    if has_usable_password(user.password_hash) and not verify_password(body.current_password, user.password_hash):
        raise error("bad_credentials", "The current password is wrong.", status.HTTP_403_FORBIDDEN)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_ms = now_ms()
    db.commit()


@router.get("/sessions", summary="List own browser sessions")
def sessions(user: CurrentUser, db: DbSession) -> list[dict]:
    rows = db.scalars(select(Session).where(Session.user_id == user.id, Session.revoked.is_(False)).order_by(Session.last_seen_at.desc()))
    return [{"id": s.id, "user_agent": s.user_agent, "created_at": s.created_at, "last_seen_at": s.last_seen_at} for s in rows]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out another session")
def revoke_session(session_id: int, user: CurrentUser, db: DbSession) -> None:
    session = db.get(Session, session_id)
    if session is None or session.user_id != user.id:
        raise error("not_found", "There is no such session.", status.HTTP_404_NOT_FOUND)
    session.revoked = True
    db.commit()


@router.get("/unread", summary="Count unread notices")
def unread(user: CurrentUser, db: DbSession) -> dict:
    count = db.scalar(select(func.count(Notice.id)).where(Notice.user_id == user.id, Notice.read_at.is_(None))) or 0
    return {"unread": int(count), "now": datetime.now(UTC).isoformat()}


@router.get("/providers", summary="List sign-in providers")
def providers(db: DbSession) -> list[dict]:
    """Public: the buttons on the sign-in page."""
    rows = db.scalars(select(OidcProvider).where(OidcProvider.enabled.is_(True)).order_by(OidcProvider.id))
    return [{"slug": p.slug, "label": p.label} for p in rows]


def utc_now_iso() -> str:
    return utcnow().isoformat()
