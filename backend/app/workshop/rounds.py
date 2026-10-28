"""The look at the catalog that the collector makes once a day, for the notices of KARTEN-15 (KARTEN-14 AC-12)."""

from __future__ import annotations

from ..db import db_session
from . import catalog, state, updates


async def once() -> None:
    """Called every minute: with the shop on, a catalog older than a day is fetched again; with it off nothing is asked (EC-3)."""
    with db_session() as db:
        on, repo = state.enabled(db), state.repo(db)
    if not on:
        return
    try:
        found, _warning = await catalog.load(repo, max_age=catalog.DAILY, retry_after=catalog.RETRY_DAILY)
    except catalog.CatalogError:
        return
    updates.look(found)
