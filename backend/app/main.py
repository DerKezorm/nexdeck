"""The application: routers, background services and the built frontend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
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
from .services import history, provisioning
from .services.collector import collector
from .services.hass_ws import hass_listener
from .services.health import health as health_service
from .services.logs import log_tailer
from .services.loop import set_main_loop

logger = logging.getLogger("nexdeck")


async def _housekeeping() -> None:
    """Condense history and prune logs every few minutes."""
    while True:
        await asyncio.sleep(300)
        try:
            with db_session() as db:
                history.condense(db)
            log_tailer.prune()
        except Exception:  # noqa: BLE001
            logger.exception("Housekeeping failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    set_main_loop(asyncio.get_running_loop())
    get_engine()
    migrate()
    with db_session() as db:
        system.load_demo_flag(db)
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
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for module in (system, setup, auth, users, avatars, boards, widgets, integrations, stream, notices, channels, push, tokens, icons, assets, discovery, logs, mail, oidc, plex, search, appearance):
    app.include_router(module.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # noqa: ANN001
    response: Response = await call_next(request)
    # Never let a browser guess the type of anything this server sends. It is
    # the one header that matters as much for an uploaded file as for a page.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if not request.url.path.startswith("/api/"):
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
