"""User management for administrators."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from ..deps import AdminUser, CurrentUser, DbSession, error
from ..models import ApiToken, Board, KioskToken, NotificationChannel, Page, Role, User, Widget
from ..schemas import UserCreate, UserPatch, UserPublic
from ..security import hash_password, now_ms
from ..services import avatars, history
from ..services.collector import collector
from .auth import user_public

router = APIRouter(prefix="/api/v1/users", tags=["users"])

logger = logging.getLogger("nexdeck.users")


@router.get("", summary="List users")
def list_users(user: CurrentUser, db: DbSession) -> list[dict]:
    """Every signed-in user sees names and roles, for sharing boards."""
    rows = db.scalars(select(User).order_by(User.username))
    if user.role == Role.admin.value:
        return [user_public(u).model_dump() for u in rows]
    return [
        {"id": u.id, "username": u.username, "display_name": u.display_name or u.username, "role": u.role, "avatar_url": avatars.url_for(u.avatar)}
        for u in rows
        if not u.disabled
    ]


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED, summary="Create a user")
def create_user(body: UserCreate, admin: AdminUser, db: DbSession, request: Request) -> UserPublic:
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise error("taken", "That user name is taken.", status.HTTP_409_CONFLICT)
    user = User(username=body.username, display_name=body.display_name.strip() or body.username, password_hash=hash_password(body.password), role=body.role, locale=body.locale)
    db.add(user)
    db.commit()
    logger.info("Account %r created as %s by %s.", user.username, user.role, admin.username)
    return user_public(user)


@router.patch("/{user_id}", response_model=UserPublic, summary="Change a user")
def patch_user(user_id: int, body: UserPatch, admin: AdminUser, db: DbSession) -> UserPublic:
    user = db.get(User, user_id)
    if user is None:
        raise error("not_found", "There is no such user.", status.HTTP_404_NOT_FOUND)
    if body.role is not None and user.id == admin.id and body.role != Role.admin.value:
        raise error("self_demotion", "You cannot take away your own administrator role.")
    if body.disabled and user.id == admin.id:
        raise error("self_disable", "You cannot disable your own account.")
    # What changed, not that something did: a log that says "a user was
    # changed" sends whoever reads it to the database to find out what.
    changed: list[str] = []
    if body.role is not None:
        if body.role != user.role:
            changed.append(f"role {user.role} -> {body.role}")
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.disabled is not None:
        if body.disabled != user.disabled:
            changed.append("disabled" if body.disabled else "enabled")
        user.disabled = body.disabled
        if body.disabled:
            user.password_changed_ms = now_ms()
    if body.locale is not None:
        user.locale = body.locale
    if body.password:
        user.password_hash = hash_password(body.password)
        user.password_changed_ms = now_ms()
        changed.append("password set by an administrator")
    db.commit()
    if changed:
        logger.info("Account %r: %s, by %s.", user.username, "; ".join(changed), admin.username)
    return user_public(user)


@router.get("/{user_id}/belongings", summary="What hangs off an account")
def belongings(user_id: int, admin: AdminUser, db: DbSession) -> dict:
    """So the question before deleting can name what is at stake."""
    user = db.get(User, user_id)
    if user is None:
        raise error("not_found", "There is no such user.", status.HTTP_404_NOT_FOUND)
    owned = list(db.scalars(select(Board).where(Board.owner_id == user.id)))
    return {
        "boards": [{"slug": board.slug, "name": board.name} for board in owned],
        "kiosk_tokens": int(db.scalar(select(func.count(KioskToken.id)).join(Board, KioskToken.board_id == Board.id).where(Board.owner_id == user.id)) or 0),
        "api_tokens": int(db.scalar(select(func.count(ApiToken.id)).where(ApiToken.user_id == user.id, ApiToken.revoked.is_(False))) or 0),
        "channels": int(db.scalar(select(func.count(NotificationChannel.id)).where(NotificationChannel.user_id == user.id)) or 0),
    }


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a user")
def delete_user(user_id: int, admin: AdminUser, db: DbSession, boards: str = "") -> None:
    user = db.get(User, user_id)
    if user is None:
        raise error("not_found", "There is no such user.", status.HTTP_404_NOT_FOUND)
    if user.id == admin.id:
        raise error("self_delete", "You cannot delete your own account.")
    admins = db.scalar(select(func.count(User.id)).where(User.role == Role.admin.value, User.disabled.is_(False))) or 0
    if user.role == Role.admin.value and admins <= 1:
        raise error("last_admin", "The last administrator cannot be deleted.")
    # ⚠️ The boards have to be decided about, not left behind. The foreign key
    # sets owner_id to NULL and the board itself stays, so it kept running:
    # every card kept asking its service, every kiosk link kept working, and it
    # showed up in nobody's list, because "mine" was false for everyone and
    # "shared" only true where a share existed. Nobody could find it to stop
    # it. Decided on 07.09.2026: ask, rather than pick one silently.
    theirs = list(db.scalars(select(Board).where(Board.owner_id == user.id)))
    if theirs and boards not in ("delete", "hand_over"):
        raise error(
            "boards_undecided",
            f"{user.username} still owns {len(theirs)} board(s). Say whether to delete them or hand them over.",
            status.HTTP_409_CONFLICT,
        )
    orphaned: list[int] = []
    for board in theirs:
        if boards == "hand_over":
            board.owner_id = admin.id
            continue
        widget_ids = list(db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)))
        for widget_id in widget_ids:
            history.forget_widget(db, widget_id)
        orphaned.extend(widget_ids)
        db.delete(board)

    avatars.remove(user.avatar)
    name = user.username
    db.delete(user)
    db.commit()
    for widget_id in orphaned:
        collector.unschedule(widget_id)
    if boards == "hand_over":
        logger.info("Account %r deleted by %s; %d board(s) handed over.", name, admin.username, len(theirs))
    else:
        logger.info("Account %r deleted by %s, with %d board(s).", name, admin.username, len(theirs))
