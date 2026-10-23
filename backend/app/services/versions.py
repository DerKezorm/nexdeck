"""Which version each connected service runs, and whether a newer one is out.

The running version is what the service says about itself when its
connection is tested (``Adapter.running_version``); nexdeck asks nothing new
of the service for it. The newest version is the latest release of the
project on GitHub, for the services listed in ``UPSTREAM``. A service that is
not on GitHub (Plex, Synology, UniFi, Proxmox and the like) shows the version
it runs and "not known" for the newest.

Both are kept for six hours and shared by every card and the System page, so
a board with three update cards costs a service one look per six hours, and
GitHub one request per project.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from ..adapters.base import AdapterError, Context
from .upstream import UPSTREAM

logger = logging.getLogger("nexdeck.versions")

#: Six hours. Releases come every few weeks; a service changes version when someone updates it.
TTL = 6 * 3600
#: A failed look is tried again sooner, so a service that was down at the wrong moment does not wait six hours.
RETRY = 15 * 60
#: At most this many services are asked at once.
PARALLEL = 4


#: A version as services and release tags write it: 4.0.11.2680, v10.10.3, version/2025.8.1, 6.2-beta.
#: ⚠️ An underscore ends a version: Duplicati tags v2.1.0.5_stable_2025-05-27.
VERSION = re.compile(r"(?<![0-9A-Za-z.])v?(\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.]+)?)(?![0-9A-Za-z.])")


def version_in(text: str | None) -> str | None:
    """The first version written in a sentence or a tag, or None."""
    found = VERSION.search(str(text or ""))
    return found.group(1) if found else None


def _numbers(version: str) -> tuple[int, ...]:
    main = version.split("-", 1)[0]
    return tuple(int(part) for part in main.split("."))


def compare(running: str | None, newest: str | None) -> str:
    """``behind``, ``current`` or ``unknown``.

    Compared by their numbers, the shorter one padded with zeros: Nextcloud
    reports 30.0.1.2 and tags v30.0.1. A service ahead of the newest release
    (a nightly, a beta) counts as current.
    """
    if not running or not newest:
        return "unknown"
    mine, theirs = _numbers(running), _numbers(newest)
    width = max(len(mine), len(theirs))
    mine, theirs = mine + (0,) * (width - len(mine)), theirs + (0,) * (width - len(theirs))
    if mine == theirs:
        # A beta of the version that is now out is behind it.
        return "behind" if "-" in running and "-" not in newest else "current"
    return "behind" if mine < theirs else "current"


def major_jump(running: str | None, newest: str | None) -> bool:
    """A new first number, except for versions named by the year (Home Assistant 2026.1): that is only January."""
    if compare(running, newest) != "behind":
        return False
    first, last = _numbers(str(running))[0], _numbers(str(newest))[0]
    return first != last and first < 1000


#: What a service that answers but names no version is told.
NOT_SAID = "The service does not say which version it runs."


@dataclass
class Reading:
    running: str | None = None
    newest: str | None = None
    url: str = ""
    published: int | None = None
    #: Why the running version is not known, in a sentence, or empty.
    problem: str = ""
    checked: float = 0.0

    @property
    def state(self) -> str:
        return compare(self.running, self.newest)

    def public(self) -> dict[str, Any]:
        body = asdict(self)
        body.pop("checked")
        body["state"] = self.state
        body["major"] = major_jump(self.running, self.newest)
        # Not reached at all, as opposed to reached and silent about its version.
        body["unread"] = bool(self.problem) and self.problem != NOT_SAID
        return body


#: What was read, by connection; and the newest release, by project.
_running: dict[int, Reading] = {}
_releases: dict[str, tuple[float, dict[str, Any] | None]] = {}
_lock = asyncio.Lock()


def forget() -> None:
    """For tests, and after a restore: everything is read again."""
    _running.clear()
    _releases.clear()


def forget_one(integration_id: int) -> None:
    _running.pop(integration_id, None)


async def newest_release(repo: str, ctx: Context) -> dict[str, Any] | None:
    """The latest release of a project, at most one request per project in six hours."""
    from ..adapters import get_adapter

    kept = _releases.get(repo)
    if kept is not None and time.time() - kept[0] < TTL:
        return kept[1]
    try:
        release = await get_adapter("github").newest_release({}, ctx, repo)
    except AdapterError:
        # GitHub out of reach, or its hourly allowance spent: asked again a quarter of an hour later.
        _releases[repo] = (time.time() - TTL + RETRY, kept[1] if kept else None)
        return kept[1] if kept else None
    _releases[repo] = (time.time(), release)
    return release


async def read(integration_id: int, kind: str, resolve: Any, ctx: Context) -> Reading:
    """The running and the newest version of one connection, from memory while it is fresh."""
    kept = _running.get(integration_id)
    now = time.time()
    if kept is not None and now - kept.checked < (TTL if not kept.problem else RETRY):
        reading = kept
    else:
        reading = Reading(checked=now)
        try:
            adapter, config, service_ctx = await resolve(integration_id)
            reading.running = await asyncio.wait_for(adapter.running_version(config, service_ctx), timeout=20)
            if reading.running is None:
                reading.problem = NOT_SAID
        except AdapterError as failure:
            reading.problem = failure.message
        except TimeoutError:
            reading.problem = "The service did not answer within twenty seconds."
        except Exception as failure:  # noqa: BLE001 - one odd answer must not take every other service down with it
            # ⚠️ A test that reads a field the service did not send raises
            # KeyError, and a secret that cannot be read its own error. Neither
            # was caught, and one such service failed the whole list.
            logger.warning("The version of connection %s could not be read: %s", integration_id, failure.__class__.__name__)
            reading.problem = f"The answer of the service could not be read ({failure.__class__.__name__})."
        _running[integration_id] = reading
    repo = UPSTREAM.get(kind)
    if repo:
        release = await newest_release(repo, ctx)
        if release is not None:
            reading.newest = version_in(release["tag"])
            reading.url = release["url"]
            reading.published = release["published"]
    return reading


async def read_many(connections: list[tuple[int, str]], resolve: Any, ctx: Context) -> dict[int, Reading]:
    """Several connections, a few at a time."""
    gate = asyncio.Semaphore(PARALLEL)

    async def one(integration_id: int, kind: str) -> tuple[int, Reading]:
        async with gate:
            return integration_id, await read(integration_id, kind, resolve, ctx)

    async with _lock:
        pairs = await asyncio.gather(*(one(number, kind) for number, kind in connections))
    return dict(pairs)
