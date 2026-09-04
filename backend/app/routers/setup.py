"""First start: the setup wizard's endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select

from .. import __version__
from ..config import get_settings
from ..deps import DbSession, error
from ..models import Board, OidcProvider, Role, User
from ..schemas import SetupBody, SetupStatus, UserPublic
from ..security import hash_password
from ..services import demo_board
from ..services.collector import collector
from .auth import open_session, user_public

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])
logger = logging.getLogger("nexdeck.setup")


def needs_setup(db: DbSession) -> bool:
    return (db.scalar(select(func.count(User.id))) or 0) == 0


@router.get("/status", response_model=SetupStatus, summary="Is the first start still pending")
def setup_status(db: DbSession) -> SetupStatus:
    """Public: the app decides between the wizard and the sign-in page from this."""
    providers = [{"slug": p.slug, "label": p.label} for p in db.scalars(select(OidcProvider).where(OidcProvider.enabled.is_(True)))]
    return SetupStatus(needs_setup=needs_setup(db), version=__version__, demo=get_settings().demo, providers=providers)


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED, summary="Create the first administrator")
async def run_setup(body: SetupBody, request: Request, response: Response, db: DbSession) -> UserPublic:
    """Creates the administrator, the starter board and, when asked, the demo."""
    if not needs_setup(db):
        raise error("already_set_up", "nexdeck is already set up.", status.HTTP_409_CONFLICT)
    user = User(username=body.username, display_name=body.display_name.strip() or body.username, password_hash=hash_password(body.password), role=Role.admin.value, locale=body.locale)
    db.add(user)
    db.flush()
    if body.demo:
        board = demo_board.create_demo(db, owner_id=user.id)
    else:
        board = demo_board.create_starter(db, owner_id=user.id, docker_host=body.docker_host.strip())
    user.start_board_id = board.id
    db.commit()
    logger.info("Setup finished: administrator %r created, board %r.", user.username, board.slug)
    if collector.running:
        await collector.start()
    open_session(db, user, request, response)
    return user_public(user, request)


@router.get("/boards-exist", summary="Do any boards exist yet")
def boards_exist(db: DbSession) -> dict:
    return {"boards": int(db.scalar(select(func.count(Board.id))) or 0)}
