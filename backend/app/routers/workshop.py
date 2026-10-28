"""The Card shop: turning it on, the catalog, installing from it, updates and recalls (KARTEN-14, KARTEN-15).

Everything here is for administrators. The shop is off until one turns it on, and while it is off nothing here asks
GitHub (KARTEN-14 AC-2, EC-5). The address-by-address contract is ``API.md`` of the shop work.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__
from ..deps import AdminUser, DbSession, error
from ..workshop import catalog, state

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])
logger = logging.getLogger("nexdeck.workshop")


class SettingsBody(BaseModel):
    enabled: bool | None = None
    repo: str | None = None


def _shop_off() -> Any:
    return error("shop_off", "The Card shop is off. Turn it on to load the catalog from GitHub.", 409)


def require_on(db: DbSession) -> str:
    """The repository to ask, or the refusal of a shop that is off."""
    if not state.enabled(db):
        raise _shop_off()
    return state.repo(db)


def _state(db: DbSession, user_id: int) -> dict[str, Any]:
    repo = state.repo(db)
    kept = catalog.known(repo) if state.enabled(db) else None
    return {
        "enabled": state.enabled(db),
        "repo": repo,
        "token_set": bool(state.token()),
        "risk_acknowledged": state.risk_acknowledged(db, user_id),
        "nexdeck_version": __version__,
        "catalog": None if kept is None else {
            "fetched_at": _iso(kept.fetched_at), "generated_at": kept.generated_at, "count": len(kept.entries),
        },
    }


def _iso(seconds: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")


@router.get("/state", summary="Whether the Card shop is on, where its catalog is, and whether a key is set")
def read_state(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Asks nobody: this is what the shop shows while it is still off."""
    return _state(db, user.id)


@router.put("/settings", summary="Turn the Card shop on or off, or name another repository for its catalog")
def change_settings(body: SettingsBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Turning it on asks nothing yet; the first request comes with the first look at the catalog. Turning it off forgets the catalog (EC-5)."""
    if body.repo is not None and not state.REPO.match(body.repo):
        raise error("bad_repo", "The repository is written owner/name, for example DerKezorm/nexdeck-workshop.")
    before = (state.enabled(db), state.repo(db))
    state.configure(db, enabled=body.enabled, repo=body.repo)
    db.commit()
    after = (state.enabled(db), state.repo(db))
    if after != before:
        logger.info("%s changed the Card shop: %s, %s.", user.username, "on" if after[0] else "off", after[1])
    if not after[0] or after[1] != before[1]:
        catalog.forget()
    return _state(db, user.id)
