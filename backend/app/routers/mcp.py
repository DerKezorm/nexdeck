"""MCP over HTTP (``POST /api/mcp``), and the keys, rights and requests behind it (``/api/v1/mcp``).

The protocol is JSON-RPC 2.0 as MCP's "Streamable HTTP" transport has it,
without streams: every request gets its answer as ``application/json``, a
notification gets 202, ``GET`` gets 405. No session is kept; every request
names its key.

Walls, in this order: a request that carries an ``Origin`` is refused
(browsers send one, MCP programs do not, so no web page can talk to this with
a key it guessed or stole, and DNS rebinding goes nowhere); MCP must be on;
the key must be valid; the key must stay under its rate. The session cookie
counts for nothing here, and neither does an API token: the CSRF check and
the middleware for reading tokens leave this address to its own walls.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import __version__
from ..db import db_session
from ..deps import AdminUser, CurrentUser, DbSession, MemberUser, error, refuse_at_home
from ..models import McpKey, McpRequest, User, utcnow
from ..services import journal, mcp, mcp_calls
from ..services.mcp import McpError
from ..services.public_url import public_url

logger = logging.getLogger("nexdeck.mcp")

router = APIRouter(tags=["mcp"])

#: Protocol versions this server speaks, newest first.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
#: What one message may weigh. The largest argument a tool takes is a few words.
MAX_BODY = 1024 * 1024
INSTRUCTIONS = (
    "nexdeck is a homelab dashboard: boards hold cards, a card shows one service (its colour, numbers, rows) and may "
    "offer buttons. Start with needs_attention or find_cards, then card_details for one card. press_button presses "
    "only what card_details lists for that card right now; it may wait for the account to allow it, then "
    "request_status tells what came of it."
)


def _refuse(code: int, name: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": {"code": name, "message": message}}, status_code=code, headers=headers)


def _base(request: Request, db: Any) -> str:
    from ..services.home_network import public_base

    return public_url(db) or public_base(request).rstrip("/")


def challenge(request: Request, db: Any) -> str:
    """``WWW-Authenticate`` of a refused key. With connectors allowed it says where a program learns to sign in."""
    if mcp.stored(db)["oauth_allowed"]:
        return f'Bearer resource_metadata="{_base(request, db)}/.well-known/oauth-protected-resource"'
    return "Bearer"


def _rpc_error(message_id: Any, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


async def handle(db: Any, caller: mcp.Caller, message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message: its answer, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
    if "id" not in message:
        # A notification (``notifications/initialized``), or the answer to something this server never asks.
        return None
    method = message.get("method")
    message_id = message["id"]
    if not isinstance(method, str):
        return _rpc_error(message_id, -32600, "Invalid request.")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        logger.info("MCP session begun by key %s.", caller.key_id)
        return {"jsonrpc": "2.0", "id": message_id, "result": {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "nexdeck", "version": __version__},
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": message_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": mcp_calls.listed(caller)}}
    if method == "tools/call":
        answer = await mcp_calls.call(db, caller, params.get("name"), params.get("arguments", {}))
        return {"jsonrpc": "2.0", "id": message_id, "result": answer}
    return _rpc_error(message_id, -32601, "Method not found.")


@router.post("/api/mcp", summary="MCP (JSON-RPC over HTTP) with a key in Authorization: Bearer")
async def endpoint(request: Request) -> Response:
    if request.headers.get("origin"):
        return _refuse(status.HTTP_403_FORBIDDEN, "origin_refused", "MCP is not for web pages.")
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else None
    with db_session() as db:
        if not mcp.allowed(db):
            return _refuse(status.HTTP_404_NOT_FOUND, "not_found", "There is no such address.")
        caller = mcp.authenticate(db, token)
        if caller is None:
            return _refuse(status.HTTP_401_UNAUTHORIZED, "key_invalid", "No valid key.", {"WWW-Authenticate": challenge(request, db)})
        if not mcp.brake(caller.key_id):
            return _refuse(status.HTTP_429_TOO_MANY_REQUESTS, "slow_down", "Too many requests with this key. Wait a minute.",
                           {"Retry-After": "60"})
        journal.set_actor(f"{caller.username} via MCP")
        # After initialize a client names the version it agreed on; one not spoken here is refused (the transport's rule).
        asked = request.headers.get("mcp-protocol-version")
        if asked is not None and asked not in PROTOCOL_VERSIONS:
            return _refuse(status.HTTP_400_BAD_REQUEST, "protocol_version", "This MCP protocol version is not spoken here.")
        body = await request.body()
        if len(body) > MAX_BODY:
            return _refuse(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "too_large", "One message holds at most 1 MB.")
        try:
            message = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            # RecursionError: JSON nested deeper than Python's stack, sent to break the server.
            return JSONResponse(_rpc_error(None, -32700, "Parse error."), status_code=status.HTTP_400_BAD_REQUEST)
        answer = await handle(db, caller, message)
    if answer is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(answer)


@router.get("/api/mcp", include_in_schema=False)
def no_stream() -> Response:
    # No server-sent stream: every answer comes with its request.
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})


# ---------------------------------------------------------------------------
# Through the interface
# ---------------------------------------------------------------------------

api = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@api.get("/status", summary="Whether MCP is on, and the address programs use")
def mcp_status(request: Request, user: CurrentUser, db: DbSession) -> dict:
    value = mcp.stored(db)
    return {"allowed": value["allowed"], "max_level": value["max_level"], "oauth_allowed": value["oauth_allowed"],
            "endpoint": f"{_base(request, db)}/api/mcp"}


@api.get("/tools", summary="Every tool with its group, level and default right")
def tool_list(user: CurrentUser, db: DbSession) -> list[dict]:
    blocked = set(mcp.stored(db)["blocked_tools"])
    return [{"name": tool["name"], "group": tool["group"], "level": tool["level"], "description": tool["description"],
             "default_right": mcp.DEFAULT_RIGHT[tool["group"]], "blocked": tool["name"] in blocked,
             "admin_only": bool(tool.get("admin_only"))}
            for tool in mcp_calls.TOOLS if tool["name"] not in mcp_calls.UNBLOCKABLE]


def _key_out(db: Any, row: McpKey, owner: User | None = None) -> dict[str, Any]:
    boards = None
    if row.boards is not None:
        # Only boards the account may still see: one it lost since says nothing, and the key does not see it.
        owner = owner or db.get(User, row.user_id)
        visible = mcp.visible_boards(db, owner) if owner is not None else set()
        boards = [number for number in row.boards if number in visible]
    return {"id": row.id, "name": row.name, "prefix": row.prefix, "kind": row.kind, "level": row.level, "boards": boards,
            "tool_rights": dict(row.tool_rights or {}), "created_at": row.created_at, "last_used_at": row.last_used_at,
            "expires_at": row.expires_at, "revoked": row.revoked, "client": row.client if row.kind == "oauth" else None}


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    level: Literal["read", "act"]
    #: 30, 90 or 365; None: the key does not run out on its own.
    expires_days: int | None = None
    #: Board ids; None: every board the account may see, later ones too.
    boards: list[int] | None = Field(default=None, max_length=1000)


class RightsIn(BaseModel):
    tool_rights: dict[str, str] = Field(max_length=100)


class AdminIn(BaseModel):
    allowed: bool
    max_level: Literal["read", "act"]
    oauth_allowed: bool = False
    blocked_tools: list[str] = Field(default_factory=list, max_length=100)


def _refused(failure: McpError) -> Exception:
    return error(failure.code, failure.message, failure.status)


@api.get("/keys", summary="My MCP keys")
def key_list(user: CurrentUser, db: DbSession) -> list[dict]:
    rows = db.scalars(select(McpKey).where(McpKey.user_id == user.id).order_by(McpKey.id))
    return [_key_out(db, row, user) for row in rows]


@api.post("/keys", status_code=status.HTTP_201_CREATED, summary="Make an MCP key")
def make_key(body: KeyIn, request: Request, user: MemberUser, db: DbSession) -> dict:
    """The key is shown once.

    ⚠️ Not from an API token and not from a session opened at home without a
    password, like an API token itself: either would be a way to mint access
    that outlives what made it.
    """
    refuse_at_home(request)
    if getattr(request.state, "auth_kind", "") == "token":
        raise error("session_required", "An API token cannot make an MCP key. Sign in and make it there.", status.HTTP_403_FORBIDDEN)
    if not mcp.allowed(db):
        raise error("mcp_off", "An administrator has not switched MCP on.", status.HTTP_403_FORBIDDEN)
    try:
        row, token = mcp.make_key(db, user, body.name, body.level, body.expires_days, body.boards)
    except McpError as failure:
        raise _refused(failure) from None
    return {"key": _key_out(db, row, user), "token": token}


def _own_key(db: Any, user: User, key_id: int) -> McpKey:
    row = db.get(McpKey, key_id)
    if row is None or row.user_id != user.id:
        raise error("not_found", "There is no such key.", status.HTTP_404_NOT_FOUND)
    return row


@api.put("/keys/{key_id}/rights", summary="Set what a key may do with each tool")
def set_rights(key_id: int, body: RightsIn, user: MemberUser, db: DbSession) -> dict:
    row = _own_key(db, user, key_id)
    clean: dict[str, str] = {}
    for name, right in body.tool_rights.items():
        tool = mcp_calls.BY_NAME.get(name)
        if tool is None or name in mcp_calls.UNBLOCKABLE or right not in mcp.RIGHTS:
            raise error("unknown_tool", "Unknown tool or right.", status.HTTP_422_UNPROCESSABLE_CONTENT)
        if tool["group"] in mcp.LOOKING and right == "ask":
            raise error("never_asked", "A tool that only looks is allowed or denied, never asked for.", status.HTTP_422_UNPROCESSABLE_CONTENT)
        if right != mcp.DEFAULT_RIGHT[tool["group"]]:
            clean[name] = right
    row.tool_rights = clean
    db.commit()
    logger.info("Rights of MCP key %r (%s) set by %s: %d differ from the defaults.", row.name, row.prefix, user.username, len(clean))
    return _key_out(db, row, user)


@api.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Withdraw an MCP key")
def revoke_key(key_id: int, user: CurrentUser, db: DbSession) -> None:
    row = _own_key(db, user, key_id)
    if row.revoked:
        raise error("not_found", "There is no such key.", status.HTTP_404_NOT_FOUND)
    # The row stays so the same hash can never come back.
    row.revoked = True
    row.revoked_at = utcnow()
    db.commit()
    logger.info("MCP key %r (%s) of %s was withdrawn.", row.name, row.prefix, user.username)


# -- requests -----------------------------------------------------------------------------


def _request_out(row: McpRequest) -> dict[str, Any]:
    try:
        arguments = mcp.arguments_of(row)
    except McpError:
        arguments = {}
    return {"id": row.id, "key_name": row.key_name, "tool": row.tool, "card_id": row.widget_id, "card": row.card,
            "board": row.board, "action": row.action, "label": row.label, "danger": row.danger,
            "params": arguments.get("params") if isinstance(arguments.get("params"), dict) else {},
            "impact": list(row.impact or []), "status": row.status, "created_at": row.created_at,
            "expires_at": row.expires_at, "result": row.result}


def _own_request(db: Any, user: User, request_id: int) -> McpRequest:
    mcp.expire(db)
    row = db.get(McpRequest, request_id)
    if row is None or row.user_id != user.id:
        raise error("not_found", "There is no such request.", status.HTTP_404_NOT_FOUND)
    return row


#: The states a request can be in, for ``?status=``.
STATES = ("waiting", "approved", "declined", "expired", "failed")


@api.get("/requests", summary="My requests that wait for approval, and the decided ones")
def request_list(user: CurrentUser, db: DbSession, state: Annotated[str | None, Query(alias="status")] = None) -> list[dict]:
    if state is not None and state not in STATES:
        raise error("bad_status", f"The status is one of {', '.join(STATES)}.", status.HTTP_422_UNPROCESSABLE_CONTENT)
    mcp.expire(db)
    query = select(McpRequest).where(McpRequest.user_id == user.id)
    if state is not None:
        query = query.where(McpRequest.status == state)
    return [_request_out(row) for row in db.scalars(query.order_by(McpRequest.id.desc()).limit(200))]


@api.get("/requests/{request_id}", summary="One request of mine")
def one_request(request_id: int, user: CurrentUser, db: DbSession) -> dict:
    return _request_out(_own_request(db, user, request_id))


@api.post("/requests/{request_id}/approve", summary="Allow a request: press exactly what it asked for")
async def approve(request_id: int, user: MemberUser, db: DbSession) -> dict:
    row = _own_request(db, user, request_id)
    try:
        mcp.claim(db, row, "approved", user)
    except McpError as failure:
        raise _refused(failure) from None
    await mcp_calls.approve(db, user, row)
    return {"status": row.status, "result": row.result}


@api.post("/requests/{request_id}/decline", summary="Decline a request")
def decline(request_id: int, user: CurrentUser, db: DbSession) -> dict:
    row = _own_request(db, user, request_id)
    try:
        mcp.claim(db, row, "declined", user)
    except McpError as failure:
        raise _refused(failure) from None
    logger.info("MCP request %s declined by %s.", row.id, user.username)
    return {"status": row.status, "result": row.result}


# -- the administrator ----------------------------------------------------------------------


@api.get("/admin", summary="Whether MCP is on, its ceiling and the blocked tools")
def admin_setting(user: AdminUser, db: DbSession) -> dict:
    return mcp.stored(db)


@api.put("/admin", summary="Switch MCP on or off, set its ceiling and block tools")
def write_admin_setting(body: AdminIn, user: AdminUser, db: DbSession) -> dict:
    try:
        value = mcp.store(db, allowed=body.allowed, max_level=body.max_level, oauth_allowed=body.oauth_allowed,
                          blocked_tools=body.blocked_tools)
    except McpError as failure:
        raise _refused(failure) from None
    logger.info("MCP is %s (highest level %s, connectors %s, %d tool(s) blocked), set by %s.", "on" if value["allowed"] else "off",
                value["max_level"], "allowed" if value["oauth_allowed"] else "not allowed", len(value["blocked_tools"]), user.username)
    return value


@api.get("/admin/keys", summary="Every MCP key of every account")
def all_keys(user: AdminUser, db: DbSession) -> list[dict]:
    owners = {row.id: row for row in db.scalars(select(User))}
    return [{**_key_out(db, row, owners.get(row.user_id)), "user": owners[row.user_id].username if row.user_id in owners else ""}
            for row in db.scalars(select(McpKey).order_by(McpKey.id))]


@api.delete("/admin/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Lock any account's MCP key")
def lock_key(key_id: int, user: AdminUser, db: DbSession) -> None:
    row = db.get(McpKey, key_id)
    if row is None or row.revoked:
        raise error("not_found", "There is no such key.", status.HTTP_404_NOT_FOUND)
    row.revoked = True
    row.revoked_at = utcnow()
    row.revoked_by = user.id
    db.commit()
    logger.info("MCP key %r (%s) of account %s was locked by %s.", row.name, row.prefix, row.user_id, user.username)
