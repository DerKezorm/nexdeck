"""User management for administrators."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from ..deps import AdminUser, CurrentUser, DbSession, error
from ..models import Role, User
from ..schemas import UserCreate, UserPatch, UserPublic
from ..security import hash_password, now_ms
from ..services import avatars
from .auth import user_public

router = APIRouter(prefix="/api/v1/users", tags=["users"])


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
    if body.role is not None:
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.disabled is not None:
        user.disabled = body.disabled
        if body.disabled:
            user.password_changed_ms = now_ms()
    if body.locale is not None:
        user.locale = body.locale
    if body.password:
        user.password_hash = hash_password(body.password)
        user.password_changed_ms = now_ms()
    db.commit()
    return user_public(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a user")
def delete_user(user_id: int, admin: AdminUser, db: DbSession) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise error("not_found", "There is no such user.", status.HTTP_404_NOT_FOUND)
    if user.id == admin.id:
        raise error("self_delete", "You cannot delete your own account.")
    admins = db.scalar(select(func.count(User.id)).where(User.role == Role.admin.value, User.disabled.is_(False))) or 0
    if user.role == Role.admin.value and admins <= 1:
        raise error("last_admin", "The last administrator cannot be deleted.")
    avatars.remove(user.avatar)
    db.delete(user)
    db.commit()
