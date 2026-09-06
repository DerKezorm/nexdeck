"""Request dependencies: who is calling, and what may they touch.

Three ways in: the session cookie (browsers), a bearer API token (scripts
and integrations) and a kiosk token (wall displays, read-only unless the
token allows actions). Cookie sessions on unsafe methods must carry the
``X-Nexdeck-Request`` header, which a cross-site form cannot add.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSessionType

from .db import get_db
from .models import (
    ApiToken,
    Board,
    BoardShare,
    Integration,
    KioskToken,
    Role,
    Session,
    ShareLevel,
    User,
    utcnow,
)
from .security import hash_token, read_kiosk_cookie, read_session_token
from .services import journal

COOKIE_NAME = "nexdeck_session"
KIOSK_COOKIE = "nexdeck_kiosk"
CSRF_HEADER = "x-nexdeck-request"
KIOSK_HEADER = "x-kiosk-token"

DbSession = Annotated[DbSessionType, Depends(get_db)]


def error(code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _touch_session(db: DbSessionType, session: Session) -> None:
    # Write at most once a minute; every request would be a write on SQLite.
    last = session.last_seen_at
    if last is None or datetime.now(UTC) - last > timedelta(minutes=1):
        session.last_seen_at = utcnow()
        db.commit()


def _user_from_cookie(request: Request, db: DbSessionType) -> User | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    claims = read_session_token(raw)
    if claims is None:
        return None
    session = db.get(Session, claims.session_id)
    if session is None or session.revoked or session.user_id != claims.user_id:
        return None
    user = db.get(User, claims.user_id)
    if user is None or user.disabled:
        return None
    if claims.issued_ms < user.password_changed_ms:
        return None
    _touch_session(db, session)
    request.state.auth_kind = "session"
    return user


def _user_from_bearer(request: Request, db: DbSessionType) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    if not token.startswith("nd_"):
        return None
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    if row is None or not usable_token(row):
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    # ⚠️ A password change ended every session cookie from the start and left
    # every API token alone. Someone who had made one kept their way in after
    # the account was locked out and the password reset.
    if int(row.created_at.timestamp() * 1000) < user.password_changed_ms:
        return None
    last = row.last_used_at
    if last is None or datetime.now(UTC) - last > timedelta(minutes=1):
        row.last_used_at = utcnow()
        db.commit()
    request.state.auth_kind = "token"
    return user


def usable_token(row: ApiToken | KioskToken) -> bool:
    """Not withdrawn, and not past its end."""
    if row.revoked:
        return False
    if row.expires_at is None:
        return True
    return row.expires_at > datetime.now(UTC)


def optional_user(request: Request, db: DbSession) -> User | None:
    user = _user_from_bearer(request, db)
    if user is None:
        user = _user_from_cookie(request, db)
        if user is not None and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(CSRF_HEADER) != "1":
                raise error("csrf", "This request must come from the nexdeck app.", status.HTTP_403_FORBIDDEN)
    # Every line written while serving this call now carries who is doing it.
    # A log that says a connection was deleted and not by whom answers half a
    # question, and it is the wrong half.
    journal.set_actor(user.username if user is not None else "")
    return user


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise error("unauthenticated", "Sign in first.", status.HTTP_401_UNAUTHORIZED)
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def admin_user(user: CurrentUser) -> User:
    if user.role != Role.admin.value:
        raise error("forbidden", "Only administrators may do this.", status.HTTP_403_FORBIDDEN)
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def not_guest(user: CurrentUser) -> User:
    if user.role == Role.guest.value:
        raise error("forbidden", "Guests may only look.", status.HTTP_403_FORBIDDEN)
    return user


MemberUser = Annotated[User, Depends(not_guest)]


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


def require_integration(db: DbSessionType, integration_id: int, user: User | None) -> Integration:
    """A connection by its number, if this person may build on it.

    ⚠️ Four places used to load a connection straight from a number that came
    out of a widget option or a query string: the merged calendar, the JSON
    card, the Docker discovery and the log card. A connection reserved for
    administrators was reachable through all four by anyone who could edit a
    widget, which is every member with a board of their own.

    Reading a card that an administrator built on a locked connection stays
    allowed; that is his decision when he shares the board. This is about
    naming a connection yourself.
    """
    integration = db.get(Integration, int(integration_id))
    if integration is None:
        raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
    if integration.admin_only and (user is None or user.role != Role.admin.value):
        raise error("integration_locked", "This connection is reserved for administrators.", status.HTTP_403_FORBIDDEN)
    return integration


# ---------------------------------------------------------------------------
# Board permissions
# ---------------------------------------------------------------------------

LEVELS = {ShareLevel.view.value: 1, ShareLevel.edit.value: 2, ShareLevel.act.value: 3, "owner": 4}


def board_permission(db: DbSessionType, board: Board, user: User | None) -> str | None:
    """``owner``, ``act``, ``edit``, ``view`` or None."""
    if user is None:
        return None
    if user.role == Role.admin.value or board.owner_id == user.id:
        return "owner"
    best: str | None = None
    for share in db.scalars(select(BoardShare).where(BoardShare.board_id == board.id)):
        applies = (share.user_id is not None and share.user_id == user.id) or (share.role is not None and share.role == user.role)
        if not applies:
            continue
        if best is None or LEVELS[share.level] > LEVELS[best]:
            best = share.level
    if best in ("edit", "act") and user.role == Role.guest.value:
        best = "view"
    return best


def board_is_shared_with(db: DbSessionType, board: Board, user: User) -> bool:
    """Is there a share for this person or their role?

    Asked apart from ``board_permission`` on purpose: that one answers "owner"
    for every administrator, which says what he may do, not what belongs to him
    or was handed to him.
    """
    for share in db.scalars(select(BoardShare).where(BoardShare.board_id == board.id)):
        if (share.user_id is not None and share.user_id == user.id) or (share.role is not None and share.role == user.role):
            return True
    return False


def _decide(db: DbSessionType, board: Board | None, user: User | None, level: str) -> tuple[Board, str]:
    """The permission part, once the board itself is beyond doubt."""
    if board is None:
        raise error("not_found", "There is no such board.", status.HTTP_404_NOT_FOUND)
    permission = board_permission(db, board, user)
    if permission is None:
        if user is None:
            raise error("unauthenticated", "Sign in first.", status.HTTP_401_UNAUTHORIZED)
        raise error("forbidden", "You may not open this board.", status.HTTP_403_FORBIDDEN)
    if LEVELS[permission] < LEVELS[level]:
        raise error("forbidden", f"You may not {level} on this board.", status.HTTP_403_FORBIDDEN)
    if level in ("edit",) and board.provisioned:
        raise error("provisioned", "This board comes from a file and is edited there.", status.HTTP_409_CONFLICT)
    return board, permission


def require_board_id(db: DbSessionType, board_id: int, user: User | None, level: str) -> tuple[Board, str]:
    """A board by its number, for the code that already holds one.

    ⚠️ Never route an id through the slug lookup. A slug may be digits, so a
    user who names a board "7" would be asked about board 7 whenever the
    server looked up the board a page or a widget belongs to, and would be
    told they own it. That was reachable from every widget address.
    """
    return _decide(db, db.get(Board, int(board_id)), user, level)


def require_board(db: DbSessionType, slug_or_id: str, user: User | None, level: str) -> tuple[Board, str]:
    """A board by what stands in the address: its slug, or its number."""
    board = db.scalar(select(Board).where(Board.slug == slug_or_id))
    if board is None and slug_or_id.isdigit():
        board = db.get(Board, int(slug_or_id))
    return _decide(db, board, user, level)


# ---------------------------------------------------------------------------
# Kiosk
# ---------------------------------------------------------------------------


def kiosk_from_request(request: Request, db: DbSessionType) -> KioskToken | None:
    """A wall display, by its cookie or by the header a script would send.

    ⚠️ ``?kiosk=`` used to be read here as well, and the browser appended it to
    every image, video and event address because none of those can set a
    header. The display exchanges its token for a cookie at the door instead;
    see ``routers/kiosk.py``.
    """
    row = _kiosk_from_cookie(request, db) or _kiosk_from_header(request, db)
    if row is None or not usable_token(row):
        return None
    last = row.last_used_at
    if last is None or datetime.now(UTC) - last > timedelta(minutes=5):
        row.last_used_at = utcnow()
        db.commit()
    request.state.auth_kind = "kiosk"
    return row


def _kiosk_from_cookie(request: Request, db: DbSessionType) -> KioskToken | None:
    raw = request.cookies.get(KIOSK_COOKIE)
    if not raw:
        return None
    kiosk_id = read_kiosk_cookie(raw)
    return None if kiosk_id is None else db.get(KioskToken, kiosk_id)


def _kiosk_from_header(request: Request, db: DbSessionType) -> KioskToken | None:
    token = request.headers.get(KIOSK_HEADER)
    if not token or not token.startswith("nk_"):
        return None
    return db.scalar(select(KioskToken).where(KioskToken.token_hash == hash_token(token)))


def board_for_viewer(db: DbSessionType, slug_or_id: str, user: User | None, kiosk: KioskToken | None) -> tuple[Board, str]:
    """A board for someone who may be a user or a kiosk display."""
    if kiosk is not None:
        board = db.get(Board, kiosk.board_id)
        if board is None or (board.slug != slug_or_id and str(board.id) != slug_or_id):
            raise error("forbidden", "This kiosk token belongs to another board.", status.HTTP_403_FORBIDDEN)
        return board, "act" if kiosk.allow_actions else "view"
    return require_board(db, slug_or_id, user, "view")


def board_for_viewer_id(db: DbSessionType, board_id: int, user: User | None, kiosk: KioskToken | None) -> tuple[Board, str]:
    """The same, for the code that already holds the board's number."""
    if kiosk is not None:
        if int(kiosk.board_id) != int(board_id):
            raise error("forbidden", "This kiosk token belongs to another board.", status.HTTP_403_FORBIDDEN)
        board = db.get(Board, int(board_id))
        if board is None:
            raise error("not_found", "There is no such board.", status.HTTP_404_NOT_FOUND)
        return board, "act" if kiosk.allow_actions else "view"
    return require_board_id(db, board_id, user, "view")
