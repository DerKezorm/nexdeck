"""nexdeck's own log, for administrators: read it, filter it, take it home.

The level can be changed here without a restart, because a restart usually
destroys the state somebody wanted to look at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from ..deps import AdminUser, DbSession, error
from ..services import journal

router = APIRouter(prefix="/api/v1/journal", tags=["system"])


class LinePublic(BaseModel):
    time: str
    level: str
    logger: str
    message: str
    request_id: str | None = None


class ModePublic(BaseModel):
    mode: str
    until: datetime | None = None
    #: An operator who set the level in the environment means it; the switch
    #: in the interface says so rather than pretending to work.
    fixed_by_env: bool = False
    modes: list[str] = Field(default_factory=lambda: list(journal.MODES))
    durations: list[int] = Field(default_factory=lambda: list(journal.ALLOWED_MINUTES))


class ModeChange(BaseModel):
    mode: Literal["quiet", "normal", "detailed", "trace"]
    #: Only for the deep levels. ``0`` means until the next restart.
    minutes: int = 0


@router.get("", summary="Read the newest lines of the log")
def read(
    admin: AdminUser,
    level: Annotated[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[LinePublic]:
    """Newest first. ``level`` means "this level and above"."""
    return [LinePublic(**vars(line)) for line in journal.read(limit=limit, level=level, search=search)]


@router.get("/level", summary="Which log level is in force")
def level(admin: AdminUser, db: DbSession) -> ModePublic:
    state = journal.state(db)
    return ModePublic(mode=state.mode, until=state.until, fixed_by_env=state.fixed_by_env)


@router.put("/level", summary="Change the log level without a restart")
def set_level(body: ModeChange, admin: AdminUser, db: DbSession) -> ModePublic:
    if journal.fixed_by_env():
        raise error(
            "fixed_by_env",
            "The log level comes from NEXDECK_LOG_LEVEL and cannot be changed here.",
            status.HTTP_409_CONFLICT,
        )
    try:
        state = journal.set_mode(db, body.mode, body.minutes)
    except ValueError as failure:
        raise error("bad_level", f"{failure} is not a level or not an allowed duration.") from failure
    return ModePublic(mode=state.mode, until=state.until, fixed_by_env=state.fixed_by_env)


@router.get("/download", summary="Download the whole log as a text file", include_in_schema=False)
def download(admin: AdminUser) -> Response:
    text, cut = journal.download()
    if cut:
        text += "\n[nexdeck] Cut off here: the log is larger than the download limit.\n"
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nexdeck-{stamp}.log"'},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Empty the log")
def clear(admin: AdminUser) -> None:
    journal.clear()
