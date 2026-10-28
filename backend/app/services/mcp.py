"""AI from outside, over MCP: keys per account, two levels, rights per tool, requests that wait for approval.

**Off by default.** An administrator switches it on under System (``allowed``)
and sets the highest level a key may have (``max_level``). Then every account
that is not a guest makes keys of its own. A key acts as its account and never
sees more: every tool goes through the account's board rights, cut down to the
boards the key was given, and a card it may not see answers like one that does
not exist.

Two levels: ``read`` looks (cards, the chronicle, history), ``act`` may also
press the buttons cards offer. The administrator's ceiling holds for keys made
before it was lowered too.

**Rights per tool.** Each tool belongs to a group with a default right:
reading is allowed, pressing asks first, the administrators' tools (diagnosis,
container logs) are denied until a key says otherwise. A tool that is denied,
above the key's level, only for administrators, or blocked for everybody by
the administrator does not exist for the key: it is missing from ``tools/list``
and answers like an unknown one. Reading tools are never asked for; there is
nothing to approve about looking.

**Requests.** "Ask", and every dangerous button even where pressing is
allowed, keeps the call as an :class:`McpRequest` with its arguments fixed. The
account allows or declines it within ``REQUEST_MINUTES``; only then the button
is pressed, with exactly those arguments and with the rights as they stand at
that moment.

**The key.** ``ndm_`` and 43 random characters, shown once. Only its SHA-256
is stored, and its first characters to tell keys apart. It travels in
``Authorization: Bearer``, never in an address, and ``journal.redact`` masks it
in every log line.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models import Board, McpKey, McpRequest, Role, Setting, User, utcnow
from ..security import hash_token, new_opaque_token

logger = logging.getLogger("nexdeck.mcp")

SETTING = "mcp"
LEVELS = ("read", "act")
RIGHTS = ("allow", "ask", "deny")
#: The groups of tools and the right a key has with each until it says otherwise.
DEFAULT_RIGHT = {"read": "allow", "act": "ask", "admin": "deny"}
#: Groups whose tools only look: allowed or denied, never asked for.
LOOKING = ("read", "admin")
KEY_PREFIX = "ndm"
#: What a token MCP takes begins with: a key made by hand, or a connector's access token.
TOKEN_PREFIXES = (f"{KEY_PREFIX}_", "ndo_")
#: Keys an account may hold; withdrawn and run-out ones do not count.
MAX_KEYS = 20
#: The lifetimes a key can be made with; None: it does not run out on its own.
EXPIRY_DAYS = (30, 90, 365)
#: Requests one key may make in a minute.
PER_MINUTE = 240
#: ``last_used_at`` is written at most this often: a busy program must not write the database with every call.
USED_EVERY = timedelta(minutes=1)
#: How long a request waits for its account.
REQUEST_MINUTES = 10
#: Waiting requests per account and per key: a program in a loop must not fill the bell.
MAX_WAITING = 20
MAX_WAITING_PER_KEY = 10
#: The arguments of one request, as canonical JSON.
MAX_REQUEST_BYTES = 64 * 1024


class McpError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# -- the administrator's setting ----------------------------------------------------------


def stored(db: Session) -> dict[str, Any]:
    """``allowed``, ``max_level``, ``oauth_allowed``, ``blocked_tools``, with the defaults filled in."""
    row = db.get(Setting, SETTING)
    value = dict(row.value or {}) if row is not None else {}
    blocked = value.get("blocked_tools")
    return {
        "allowed": bool(value.get("allowed", False)),
        "max_level": value.get("max_level") if value.get("max_level") in LEVELS else "act",
        "oauth_allowed": bool(value.get("oauth_allowed", False)),
        "blocked_tools": sorted({name for name in blocked if isinstance(name, str)}) if isinstance(blocked, list) else [],
    }


def store(db: Session, *, allowed: bool, max_level: str, oauth_allowed: bool, blocked_tools: list[str]) -> dict[str, Any]:
    from .mcp_calls import BY_NAME, UNBLOCKABLE

    if max_level not in LEVELS:
        raise McpError("bad_level", "The highest level is read or act.", 422)
    unknown = [name for name in blocked_tools if name not in BY_NAME or name in UNBLOCKABLE]
    if unknown:
        raise McpError("unknown_tool", f"There is no tool that can be blocked by the name {unknown[0]!r}.", 422)
    value = {"allowed": bool(allowed), "max_level": max_level, "oauth_allowed": bool(oauth_allowed),
             "blocked_tools": sorted(set(blocked_tools))}
    db.merge(Setting(key=SETTING, value=value))
    db.commit()
    return stored(db)


def allowed(db: Session) -> bool:
    return stored(db)["allowed"]


def at_least(level: str, need: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(need)


# -- keys ---------------------------------------------------------------------------------


def _aware(at: datetime | None) -> datetime | None:
    return at if at is None or at.tzinfo else at.replace(tzinfo=UTC)


def counts(row: McpKey) -> bool:
    """Withdrawn or run out, a key no longer counts against the twenty."""
    expires = _aware(row.expires_at)
    return not row.revoked and (expires is None or expires > utcnow())


def visible_boards(db: Session, user: User) -> set[int]:
    from ..deps import board_permission

    return {board.id for board in db.scalars(select(Board)) if board_permission(db, board, user) is not None}


def make_key(db: Session, user: User, name: str, level: str, expires_days: int | None, boards: list[int] | None) -> tuple[McpKey, str]:
    """A new key; the token is returned once and never stored.

    ``boards``: the key sees only these, of the boards the account may see;
    None: every one it may see, later ones too. A board it may not see is
    refused like one that does not exist.
    """
    if level not in LEVELS:
        raise McpError("bad_level", "The level is read or act.", 422)
    if expires_days is not None and expires_days not in EXPIRY_DAYS:
        raise McpError("bad_expiry", "A key runs out after 30, 90 or 365 days, or never.", 422)
    if boards is not None:
        if not boards or not set(boards) <= visible_boards(db, user):
            raise McpError("unknown_board", "There is no such board.", 422)
        boards = sorted(set(boards))
    if not at_least(stored(db)["max_level"], level):
        raise McpError("level_not_allowed", "The administrator does not allow keys of this level.", 403)
    from .mcp_oauth import holds

    # Connectors count while they can still refresh, not only for the hour their access token lasts.
    if holds(db, user.id) >= MAX_KEYS:
        raise McpError("too_many_keys", f"An account holds at most {MAX_KEYS} keys. Withdraw one first.", 409)
    token, token_hash, prefix = new_opaque_token(KEY_PREFIX)
    row = McpKey(user_id=user.id, name=name.strip()[:80] or "MCP", kind="key", level=level, token_hash=token_hash, prefix=prefix,
                 boards=boards, tool_rights={},
                 expires_at=utcnow() + timedelta(days=expires_days) if expires_days else None)
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("MCP key %r (%s) made for %s, level %s, %s, %s.", row.name, row.prefix, user.username, level,
                "every board" if boards is None else f"{len(boards)} board(s)",
                f"ending {row.expires_at:%Y-%m-%d}" if row.expires_at else "with no end")
    return row, token


@dataclass(frozen=True)
class Caller:
    """Who calls over MCP: the key and its account, as they stand at this moment."""

    user_id: int
    username: str
    role: str
    key_id: int
    key_name: str
    #: The key's level, never above the administrator's ceiling.
    level: str
    rights: dict[str, str]
    blocked: frozenset[str]
    #: The boards the key may see, of its account's; None: every one.
    boards: frozenset[int] | None

    @property
    def actor(self) -> str:
        """How the key is named in the action log and the chronicle."""
        return f"{self.key_name} (MCP)"

    def right(self, tool: dict[str, Any]) -> str | None:
        """What the key may do with a tool: ``allow``, ``ask``, or None when the tool does not exist for it."""
        name = tool["name"]
        if name in self.blocked:
            return None
        if tool.get("admin_only") and self.role != Role.admin.value:
            return None
        if not at_least(self.level, tool["level"]):
            return None
        if tool.get("always"):
            return "allow"
        group = tool["group"]
        chosen = self.rights.get(name, DEFAULT_RIGHT[group])
        if chosen not in RIGHTS:
            chosen = DEFAULT_RIGHT[group]
        if group in LOOKING and chosen == "ask":
            # Looking changes nothing; there is nothing to approve.
            chosen = "allow"
        return None if chosen == "deny" else chosen


def authenticate(db: Session, token: str | None) -> Caller | None:
    """The key and account behind a token, or None. MCP being on is the caller's question."""
    # A shortcut, not a wall: a token that is no key (``ndm_``) and no connector's access token (``ndo_``,
    # ``services/mcp_oauth.py``) is not even hashed and looked up. Without it the answer is the same (only hashes
    # are compared), so no test can tell it is there.
    if not token or not token.startswith(TOKEN_PREFIXES) or len(token) > 200:
        return None
    key = db.scalar(select(McpKey).where(McpKey.token_hash == hash_token(token)))
    if key is None:
        return None
    caller = _caller(db, key)
    if caller is not None:
        now = utcnow()
        last = _aware(key.last_used_at)
        if last is None or now - last >= USED_EVERY:
            key.last_used_at = now
            db.commit()
    return caller


def caller_of_key(db: Session, key_id: int) -> Caller | None:
    """The caller behind a key as it stands now, for a request its account allows: the same checks as a call."""
    key = db.get(McpKey, key_id)
    return None if key is None or not allowed(db) else _caller(db, key, pending=True)


def _caller(db: Session, key: McpKey, *, pending: bool = False) -> Caller | None:
    """The caller behind a key, or None when something about it or its account stops it.

    ``pending``: for an approval, not for a call. A connector's access token
    runs out after an hour while the person reads the bell, and its refresh
    token is good for thirty days: the connector is still there, only the
    token of this hour is not. A call needs the token; an approval of what the
    connector asked while it was valid does not.
    """
    from . import mcp_oauth, two_factor

    if not (mcp_oauth.connector_alive(db, key) if pending and key.kind == "oauth" else counts(key)):
        return None
    setting = stored(db)
    if key.kind == "oauth" and not setting["oauth_allowed"]:
        # Connectors switched off: their tokens stop at once, not when they run out.
        return None
    user = db.get(User, key.user_id)
    if user is None or user.disabled or user.role == Role.guest.value:
        # ⚠️ A guest may only look, and may not make a key; one made before
        # the account was made a guest stops with the downgrade.
        return None
    # A password change ends every key of the account, as it ends every session and API token.
    if int(_aware(key.created_at).timestamp() * 1000) < user.password_changed_ms:
        return None
    if two_factor.must_set_up(db, user, None):
        # The installation wants a second factor this account has not set up: its keys wait like its tokens.
        return None
    ceiling = setting["max_level"]
    level = key.level if key.level in LEVELS else "read"
    if not at_least(ceiling, level):
        # Lowered after the key was made, the ceiling holds for it all the same.
        level = ceiling
    # Whether a right is one of RIGHTS is ``Caller.right``'s question alone: one place decides what a stray value means.
    rights = {name: right for name, right in (key.tool_rights or {}).items() if isinstance(name, str) and isinstance(right, str)}
    return Caller(user_id=user.id, username=user.username, role=user.role, key_id=key.id, key_name=key.name, level=level,
                  rights=rights, blocked=frozenset(setting["blocked_tools"]),
                  boards=None if key.boards is None else frozenset(int(number) for number in key.boards))


# -- the brake ------------------------------------------------------------------------------

_calls_lock = threading.Lock()
_calls: dict[int, deque[float]] = defaultdict(deque)


def brake(key_id: int, now: float | None = None) -> bool:
    """True while the key stays under ``PER_MINUTE`` requests in the last minute; counts this one."""
    now = time.monotonic() if now is None else now
    with _calls_lock:
        seen = _calls[key_id]
        while seen and now - seen[0] >= 60:
            seen.popleft()
        if len(seen) >= PER_MINUTE:
            return False
        seen.append(now)
        return True


def forget_calls() -> None:
    with _calls_lock:
        _calls.clear()


# -- requests ---------------------------------------------------------------------------------


def canonical(arguments: dict[str, Any]) -> str:
    """The arguments as one fixed text: sorted keys, no spaces. What is shown is what runs."""
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def add_request(db: Session, caller: Caller, tool: str, arguments: dict[str, Any], *, widget_id: int | None, card: str, board: str,
                action: str, label: str, danger: bool, impact: list[Any], row: str = "") -> McpRequest:
    text = canonical(arguments)
    if len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise McpError("too_large", "The arguments of a request hold at most 64 kB.", 413)
    expire(db)
    waiting = db.scalar(select(func.count()).select_from(McpRequest)
                        .where(McpRequest.user_id == caller.user_id, McpRequest.status == "waiting")) or 0
    if waiting >= MAX_WAITING:
        raise McpError("too_many_requests", f"{MAX_WAITING} requests wait for this account already. Let it decide first.", 429)
    of_key = db.scalar(select(func.count()).select_from(McpRequest)
                       .where(McpRequest.key_id == caller.key_id, McpRequest.status == "waiting")) or 0
    if of_key >= MAX_WAITING_PER_KEY:
        raise McpError("too_many_requests", f"{MAX_WAITING_PER_KEY} requests of this key wait already. Let the account decide first.", 429)
    now = utcnow()
    row = McpRequest(user_id=caller.user_id, key_id=caller.key_id, key_name=caller.key_name, tool=tool, arguments=text,
                     digest=digest(text), widget_id=widget_id, card=card[:200], board=board[:200], action=action[:80],
                     label=label[:120], row=row[:200], danger=danger, impact=list(impact or []), status="waiting", created_at=now,
                     expires_at=now + timedelta(minutes=REQUEST_MINUTES))
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("MCP request %s made: %s on card %s by key %s.", row.id, tool, widget_id, caller.key_id)
    return row


def expire(db: Session) -> int:
    """Waiting requests past their time become expired."""
    now = utcnow()
    done = db.execute(update(McpRequest).where(McpRequest.status == "waiting", McpRequest.expires_at <= now)
                      .values(status="expired", decided_at=now))
    db.commit()
    if done.rowcount:
        logger.info("%d MCP request(s) ran out.", done.rowcount)
    return int(done.rowcount or 0)


def sweep(db: Session, days: int) -> int:
    """Decided requests older than ``days`` go; a waiting one never does (it runs out first)."""
    cutoff = utcnow() - timedelta(days=days)
    gone = db.execute(delete(McpRequest).where(McpRequest.status != "waiting", McpRequest.created_at < cutoff))
    return int(gone.rowcount or 0)


def arguments_of(row: McpRequest) -> dict[str, Any]:
    """The arguments of a request; refused when the stored text no longer matches its digest."""
    if digest(row.arguments) != row.digest:
        raise McpError("request_changed", "The request does not match what was asked.", 409)
    value = json.loads(row.arguments)
    if not isinstance(value, dict):
        raise McpError("request_changed", "The request does not match what was asked.", 409)
    return value


def claim(db: Session, row: McpRequest, status: str, user: User) -> None:
    """Takes the request out of "waiting" in one step, or answers that another click was first.

    ⚠️ One step, not a read and then a write: two approvals at once would
    otherwise press the button twice, and an approval and a decline at once
    would both go through.
    """
    now = utcnow()
    taken = db.execute(update(McpRequest).where(McpRequest.id == row.id, McpRequest.status == "waiting", McpRequest.expires_at > now)
                       .values(status=status, decided_at=now, decided_by=user.id))
    db.commit()
    if taken.rowcount != 1:
        raise McpError("request_closed", "This request was decided already or ran out.", 409)
    db.refresh(row)


def finish(db: Session, row: McpRequest, status: str, result: dict[str, Any]) -> None:
    row.status = status
    row.result = result
    db.commit()
