"""Connectors: MCP programs that sign in with OAuth (``services/mcp_oauth.py`` says how it goes).

The public half (``router``) speaks OAuth to programs and needs no session:
the two metadata documents, registration, the authorization request that
hands the person to the consent page ``/connect``, the token endpoint and
revocation. It answers 404 like ``/api/mcp`` while MCP or connectors are off.

The consent page itself (``api``) talks to ``/api/v1/mcp/consent`` like every
page of the app: a signed-in session, the CSRF header on the POST, and never
an API token or a session opened at home without a password, for the same
reason those cannot make a key.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import db_session
from ..deps import DbSession, MemberUser, error, refuse_at_home
from ..models import Board, McpOAuthClient
from ..services import mcp, mcp_oauth
from ..services.home_network import public_base
from ..services.mcp import McpError
from ..services.mcp_oauth import OAuthError
from ..services.public_url import public_url

logger = logging.getLogger("nexdeck.mcp")

router = APIRouter(tags=["mcp"])
api = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

#: What a token or registration request may weigh: a few addresses and a name.
MAX_BODY = 16 * 1024
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def base(request: Request, db: Any) -> str:
    return public_url(db) or public_base(request).rstrip("/")


def _gone() -> JSONResponse:
    return JSONResponse({"detail": {"code": "not_found", "message": "There is no such address."}}, status_code=404)


def _oauth_error(failure: OAuthError) -> JSONResponse:
    return JSONResponse({"error": failure.code, "error_description": failure.description}, status_code=failure.status,
                        headers=NO_STORE)


# -- discovery ------------------------------------------------------------------------------------


def _resource_metadata(request: Request) -> Response:
    with db_session() as db:
        if not mcp_oauth.is_open(db):
            return _gone()
        root = base(request, db)
    return JSONResponse({"resource": mcp_oauth.resource_of(root), "authorization_servers": [root],
                         "bearer_methods_supported": ["header"], "scopes_supported": [mcp_oauth.SCOPE],
                         "resource_name": "nexdeck"}, headers={"Cache-Control": "no-store"})


@router.get("/.well-known/oauth-protected-resource", summary="Protected resource metadata of the MCP endpoint (RFC 9728)")
def resource_metadata(request: Request) -> Response:
    return _resource_metadata(request)


@router.get("/.well-known/oauth-protected-resource/api/mcp", summary="The same metadata at the address derived from the endpoint")
def resource_metadata_for_mcp(request: Request) -> Response:
    # RFC 9728, section 3.1: a program that starts from the endpoint's address puts its path behind the well-known one.
    return _resource_metadata(request)


@router.get("/.well-known/oauth-authorization-server", summary="Authorization server metadata for connectors (RFC 8414)")
def server_metadata(request: Request) -> Response:
    with db_session() as db:
        if not mcp_oauth.is_open(db):
            return _gone()
        root = base(request, db)
    return JSONResponse({
        "issuer": root,
        "authorization_endpoint": f"{root}/api/mcp/oauth/authorize",
        "token_endpoint": f"{root}/api/mcp/oauth/token",
        "registration_endpoint": f"{root}/api/mcp/oauth/register",
        "revocation_endpoint": f"{root}/api/mcp/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [mcp_oauth.SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }, headers={"Cache-Control": "no-store"})


# -- registration ---------------------------------------------------------------------------------


async def _read(request: Request) -> bytes | None:
    """The body, or None past ``MAX_BODY``; read in blocks, so a body without a length is weighed too."""
    taken = bytearray()
    async for block in request.stream():
        taken += block
        if len(taken) > MAX_BODY:
            return None
    return bytes(taken)


@router.post("/api/mcp/oauth/register", status_code=status.HTTP_201_CREATED, summary="Register a connector program (RFC 7591)")
async def register(request: Request) -> Response:
    with db_session() as db:
        if not mcp_oauth.is_open(db):
            return _gone()
    raw = await _read(request)
    try:
        body = json.loads(raw) if raw is not None else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        body = None
    sender = request.client.host if request.client else "?"
    with db_session() as db:
        try:
            client = mcp_oauth.register(db, body, sender)
        except OAuthError as failure:
            return _oauth_error(failure)
        answer = {"client_id": client.id, "client_name": client.name, "redirect_uris": list(client.redirect_uris),
                  "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
                  "response_types": ["code"], "client_id_issued_at": int(client.created_at.timestamp())}
    return JSONResponse(answer, status_code=status.HTTP_201_CREATED, headers=NO_STORE)


# -- the authorization request ------------------------------------------------------------------


@router.get("/api/mcp/oauth/authorize", summary="Start a connector's sign-in: on to the consent page")
def authorize(
    request: Request,
    client_id: str = Query("", max_length=64),
    redirect_uri: str = Query("", max_length=2048),
    response_type: str = Query("", max_length=32),
    code_challenge: str = Query("", max_length=128),
    code_challenge_method: str = Query("", max_length=16),
    state: str = Query("", max_length=1024),
    resource: str = Query("", max_length=2048),
    scope: str = Query("", max_length=200),
) -> Response:
    """Mistakes the program can be told of go back to it; a request that cannot even say where it came from goes on
    to the consent page, which explains it to the person (never a redirect to an address nobody registered)."""
    with db_session() as db:
        if not mcp_oauth.is_open(db):
            return _gone()
        root = base(request, db)
        try:
            mcp_oauth.client_for(db, client_id, redirect_uri)
            known = True
        except McpError:
            known = False
    if known:
        problem = ""
        if response_type != "code":
            problem, text = "unsupported_response_type", "Only response_type=code is spoken here."
        else:
            try:
                mcp_oauth.check_request_shape(code_challenge, code_challenge_method, resource, root)
            except OAuthError as failure:
                problem, text = failure.code, failure.description
        if problem:
            return RedirectResponse(mcp_oauth.back_to(redirect_uri, {"error": problem, "error_description": text,
                                                                     "state": state, "iss": root}), status_code=302)
    query = {"client_id": client_id, "redirect_uri": redirect_uri, "code_challenge": code_challenge,
             "code_challenge_method": code_challenge_method, "state": state, "resource": resource, "scope": scope}
    page = str(request.scope.get("root_path") or "") + "/connect"
    return RedirectResponse(f"{page}?{urlencode({key: value for key, value in query.items() if value})}", status_code=302)


# -- tokens -----------------------------------------------------------------------------------------


def _form(raw: bytes, content_type: str) -> dict[str, str]:
    text = raw.decode("utf-8", "replace")
    if content_type.startswith("application/json"):
        try:
            found = json.loads(text)
        except (ValueError, RecursionError):
            return {}
        return {str(key): str(value) for key, value in found.items() if isinstance(value, str)} if isinstance(found, dict) else {}
    return {key: values[0] for key, values in parse_qs(text, keep_blank_values=True).items()}


@router.post("/api/mcp/oauth/token", summary="Trade a code or a refresh token for a connector's tokens")
async def token(request: Request) -> Response:
    with db_session() as db:
        if not mcp_oauth.is_open(db):
            return _gone()
    raw = await _read(request)
    if raw is None:
        return _oauth_error(OAuthError("invalid_request", "The request is too large."))
    form = _form(raw, request.headers.get("content-type", ""))
    grant = form.get("grant_type", "")
    with db_session() as db:
        client = db.get(McpOAuthClient, form.get("client_id", "")) if form.get("client_id") else None
        if client is None:
            return _oauth_error(OAuthError("invalid_client", "Unknown client.", 401))
        root = base(request, db)
        try:
            if grant == "authorization_code":
                answer = mcp_oauth.trade_code(db, client, form, root)
            elif grant == "refresh_token":
                answer = mcp_oauth.refresh(db, client, form, root)
            else:
                raise OAuthError("unsupported_grant_type", "Only authorization_code and refresh_token.")
        except OAuthError as failure:
            logger.info("MCP connector token request refused: %s.", failure.code)
            return _oauth_error(failure)
    return JSONResponse(answer, headers=NO_STORE)


@router.post("/api/mcp/oauth/revoke", summary="Revoke a connector's token (RFC 7009)")
async def revoke(request: Request) -> Response:
    with db_session() as db:
        if not mcp_oauth.is_open(db):
            return _gone()
    raw = await _read(request)
    if raw is None:
        return _oauth_error(OAuthError("invalid_request", "The request is too large."))
    form = _form(raw, request.headers.get("content-type", ""))
    with db_session() as db:
        mcp_oauth.revoke(db, form.get("token", ""), form.get("client_id", ""))
    # RFC 7009, 2.2: the same answer for a token that was never there.
    return Response(status_code=status.HTTP_200_OK, headers=NO_STORE)


# -- the consent page -------------------------------------------------------------------------------


def _session_only(request: Request) -> None:
    refuse_at_home(request)
    if getattr(request.state, "auth_kind", "") != "session":
        raise error("session_required", "Sign in to connect a program.", status.HTTP_403_FORBIDDEN)


def _open_or_refuse(db: Any) -> None:
    if not mcp_oauth.is_open(db):
        raise error("oauth_off", "An administrator has not allowed connectors.", status.HTTP_403_FORBIDDEN)


def _refused(failure: McpError) -> Exception:
    return error(failure.code, failure.message, failure.status)


@api.get("/consent", summary="What a program asks for when it wants to connect")
def consent_info(
    request: Request,
    user: MemberUser,
    db: DbSession,
    client_id: str = Query("", max_length=64),
    redirect_uri: str = Query("", max_length=2048),
    code_challenge: str = Query("", max_length=128),
    code_challenge_method: str = Query("", max_length=16),
    resource: str = Query("", max_length=2048),
) -> dict:
    _session_only(request)
    _open_or_refuse(db)
    try:
        client = mcp_oauth.check_request(db, base(request, db), client_id=client_id, redirect_uri=redirect_uri,
                                         code_challenge=code_challenge, code_challenge_method=code_challenge_method,
                                         resource=resource)
    except McpError as failure:
        raise _refused(failure) from None
    visible = mcp.visible_boards(db, user)
    boards = [{"id": board.id, "name": board.name} for board in db.scalars(select(Board).order_by(Board.name)) if board.id in visible]
    return {"client_name": client.name, "redirect_host": urlsplit(redirect_uri).netloc, "max_level": mcp.stored(db)["max_level"],
            "boards": boards}


class ConsentIn(BaseModel):
    client_id: str = Field(max_length=64)
    redirect_uri: str = Field(max_length=2048)
    code_challenge: str = Field(max_length=128)
    code_challenge_method: str = Field(max_length=16)
    state: str = Field(default="", max_length=1024)
    resource: str = Field(default="", max_length=2048)
    allow: bool
    level: str = Field(default="read", max_length=8)
    #: Board ids; None: every board the account may see, later ones too.
    boards: list[int] | None = Field(default=None, max_length=1000)


@api.post("/consent", summary="Allow a program to connect, or turn it down")
def consent(body: ConsentIn, request: Request, user: MemberUser, db: DbSession) -> dict:
    _session_only(request)
    _open_or_refuse(db)
    root = base(request, db)
    try:
        client = mcp_oauth.check_request(db, root, client_id=body.client_id, redirect_uri=body.redirect_uri,
                                         code_challenge=body.code_challenge,
                                         code_challenge_method=body.code_challenge_method, resource=body.resource)
        if not body.allow:
            logger.info("MCP connector %r turned down by %s.", client.name, user.username)
            return {"redirect": mcp_oauth.back_to(body.redirect_uri, {"error": "access_denied", "state": body.state, "iss": root})}
        code = mcp_oauth.grant(db, user, client, redirect_uri=body.redirect_uri, code_challenge=body.code_challenge,
                               resource=body.resource, level=body.level, boards=body.boards)
    except McpError as failure:
        raise _refused(failure) from None
    return {"redirect": mcp_oauth.back_to(body.redirect_uri, {"code": code, "state": body.state, "iss": root})}
