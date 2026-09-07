"""The application: routers, background services and the built frontend."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .db import db_session, get_engine
from .migrations import migrate
from .routers import (
    appearance,
    assets,
    auth,
    avatars,
    backups,
    boards,
    channels,
    discovery,
    icons,
    integrations,
    logs,
    mail,
    notices,
    oidc,
    plex,
    push,
    search,
    setup,
    stream,
    system,
    tokens,
    users,
    widgets,
)
from .routers import journal as journal_router
from .security import prune_sessions
from .services import backup, history, journal, provisioning, retention
from .services.collector import collector
from .services.hass_ws import hass_listener
from .services.health import health as health_service
from .services.logs import log_tailer
from .services.loop import set_main_loop

logger = logging.getLogger("nexdeck")


def _housekeeping_once() -> None:
    with db_session() as db:
        history.condense(db)
        journal.enforce_expiry(db)
        retention.prune_old_records(db)
        sessions_gone = prune_sessions(db)
    if sessions_gone:
        logger.info("Swept %d session(s) that had run out.", sessions_gone)
    log_tailer.prune()
    try:
        backup.write_one_if_due()
    except Exception:  # noqa: BLE001 - a snapshot that fails must not stop the housekeeping
        logger.exception("The scheduled snapshot could not be written.")


async def _housekeeping() -> None:
    """Condense history, prune logs and end a deep log level every few minutes."""
    while True:
        await asyncio.sleep(300)
        try:
            # ⚠️ In a thread, not here. Condensing walks three tables and used
            # to do it on the event loop, so every five minutes the server went
            # quiet for as long as it took.
            await asyncio.to_thread(_housekeeping_once)
        except Exception:  # noqa: BLE001
            logger.exception("Housekeeping failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ⚠️ Not ``basicConfig``. That wrote to standard output and nowhere else,
    # so the question "what happened at four in the morning" had no answer on
    # a machine whose container log had rotated away.
    journal.setup()
    set_main_loop(asyncio.get_running_loop())
    # Synchronous routes run here, and each one holds a database connection
    # while it does. Keeping the number below the pool means a request waits
    # for a thread, where waiting is normal, instead of waiting for a
    # connection, where it ends in a 500 after thirty seconds.
    anyio.to_thread.current_default_thread_limiter().total_tokens = get_settings().request_threads
    get_engine()
    migrate()
    with db_session() as db:
        system.load_demo_flag(db)
        journal.apply_stored(db)
    provisioning.load_all()
    await collector.start()
    await health_service.start()
    await hass_listener.start()
    housekeeping = asyncio.create_task(_housekeeping(), name="housekeeping")
    provisioning_task = asyncio.create_task(provisioning.watch(), name="provisioning")
    logger.info("nexdeck %s ready.", __version__)
    try:
        yield
    finally:
        housekeeping.cancel()
        provisioning_task.cancel()
        await hass_listener.stop()
        await health_service.stop()
        await log_tailer.stop()
        await collector.stop()
        set_main_loop(None)


app = FastAPI(
    title="nexdeck",
    version=__version__,
    description="The live homelab dashboard of the nexapps family.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

_cors = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if "*" in _cors:
    # ⚠️ Refusing to start is the friendly answer here. Starlette does not
    # send a literal "*" when credentials are allowed: it echoes back whatever
    # Origin asked, and sets Access-Control-Allow-Credentials with it. The
    # preflight then also waves through X-Nexdeck-Request, which is the header
    # that stops another site from acting as the signed-in user. So the one
    # value that looks like "let anyone read the public parts" is in fact
    # "let any site the operator visits do anything as them". Measured on
    # 07.09.2026 against a running instance.
    raise RuntimeError(
        "NEXDECK_CORS_ORIGINS='*' cannot be combined with signing in, because it would let any "
        "site act as the signed-in user. Name the origins instead, comma separated.",
    )
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for module in (system, setup, auth, users, avatars, backups, boards, widgets, integrations, stream, notices, channels, push, tokens, icons, assets, discovery, logs, journal_router, mail, oidc, plex, search, appearance):
    app.include_router(module.router)


#: What an ordinary request body may weigh. Comfortably above the largest
#: upload the interface offers (a 12 MB background) and far below anything
#: that hurts.
MAX_BODY = 16 * 1024 * 1024
#: The one address that legitimately receives a large file, and its ceiling.
BIG_BODY_PATH = "/api/v1/backups/restore"
MAX_BIG_BODY = 512 * 1024 * 1024


def body_limit(path: str) -> int:
    return MAX_BIG_BODY if path.rstrip("/").endswith(BIG_BODY_PATH) else MAX_BODY


@app.middleware("http")
async def refuse_a_body_nobody_asked_for(request: Request, call_next):  # noqa: ANN001
    """Weigh the body before anything reads it.

    ⚠️ FastAPI reads the form before it resolves the dependencies, so the
    ceiling inside a handler is checked after the file has already been
    written. A 30 GB multipart part sent to ``POST /auth/me/avatar`` landed in
    the temp directory in full, and only then came the 401: no account needed,
    no limit anywhere, the disk beside the database. The comment on the limit
    in ``backups.py`` claimed the opposite in so many words.

    This is the cheap half, and it covers the ordinary case: a browser and
    every HTTP client sends ``Content-Length``. A body without one is refused
    by the handlers instead, which read in blocks and count as they go.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit():
        allowed = body_limit(request.url.path)
        if int(declared) > allowed:
            return JSONResponse(
                {"detail": {"code": "too_large", "message": f"The body is larger than {allowed // (1024 * 1024)} MB."}},
                status_code=413,
            )
    return await call_next(request)


@app.middleware("http")
async def request_number(request: Request, call_next):  # noqa: ANN001
    """Give every call a short number, so its lines belong together.

    ⚠️ A dozen background tasks write into the same file at the same time. A
    line without this is a line nobody can place: you can see that something
    failed and not what it was part of.
    """
    token = journal.bind_request(secrets.token_hex(3))
    try:
        return await call_next(request)
    finally:
        journal.unbind_request(token)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # noqa: ANN001
    response: Response = await call_next(request)
    # Never let a browser guess the type of anything this server sends. It is
    # the one header that matters as much for an uploaded file as for a page.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.url.path.startswith("/api/"):
        # ⚠️ The API used to get no policy at all, on the grounds that JSON
        # needs none. Two addresses under it do not answer with JSON: the icon
        # proxy hands out SVG it fetched from a public collection, and the
        # image proxy passes through whatever content type the service sent.
        # SVG is a document that can run script, and it would have run in
        # nexdeck's own origin. A route that needs something looser sets its
        # own header; this is only the floor.
        response.headers.setdefault(
            "Content-Security-Policy",
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        )
        response.headers.setdefault("Referrer-Policy", "same-origin")
    else:
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # The app talks only to its own origin; icons and uploads are proxied.
        # Images may come from anywhere (media art from Plex or Jellyfin on
        # the LAN), and the iframe widget embeds any page by design. Live video
        # plays from a blob: MediaSource, so media-src must allow blob:.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https: http:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; "
            "frame-src *; worker-src 'self'; manifest-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'self'",
        )
    return response


@app.exception_handler(404)
async def not_found(request: Request, exc: Exception) -> Response:
    if request.url.path.startswith("/api/"):
        # ⚠️ A route that answers 404 says why: there is no such user, no such
        # board, no such account to give the board to. All of it was thrown
        # away here and replaced by "There is no such address.", so the browser
        # showed the same sentence for a missing board and for a mistyped URL,
        # and the reason existed only in the source. Only the 404 that Starlette
        # raises for a path nothing matched has no detail of its own.
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            return JSONResponse({"detail": exc.detail}, status_code=404)
        return JSONResponse({"code": "not_found", "message": "There is no such address."}, status_code=404)
    return _index()


# ---------------------------------------------------------------------------
# The built frontend
# ---------------------------------------------------------------------------


def _static_dir() -> Path | None:
    configured = get_settings().static_dir
    if configured and configured.is_dir():
        return configured
    fallback = Path(__file__).resolve().parent / "static"
    return fallback if fallback.is_dir() else None


def _index() -> Response:
    directory = _static_dir()
    if directory is None or not (directory / "index.html").exists():
        return JSONResponse({"code": "no_frontend", "message": "The frontend is not built. Run the Vite dev server or build it."}, status_code=503)
    return FileResponse(directory / "index.html", headers={"Cache-Control": "no-cache"})


_static = _static_dir()
if _static is not None and (_static / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str) -> Response:
    """Every non-API address is the single-page app."""
    directory = _static_dir()
    if directory is not None and path and not path.startswith("api/"):
        candidate = (directory / path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(directory.resolve())):
            return FileResponse(candidate)
    return _index()
