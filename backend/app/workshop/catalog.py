"""The catalog of the Workshop repository: fetched from GitHub, checked, and kept in memory (KARTEN-14).

``catalog.json`` is the contract between the repository and nexdeck (``format`` 1). A catalog that cannot be read, or is
empty, is an error and not an empty list (EC-6). GitHub out of reach is a sentence of its own (AC-10): the cards that
were installed run on without it.

⚠️ Every request to GitHub goes through :func:`fetch`: the host is fixed (``api.github.com``), the repository comes from
the setting and has been matched against a pattern, and the key of the operator is sent to that host and no other.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from ..adapters.base import outbound_client
from . import state

logger = logging.getLogger("nexdeck.workshop")

API = "https://api.github.com"
#: How a file is asked for: the bytes themselves, without the JSON wrapper around them.
ACCEPT = "application/vnd.github.raw+json"
CATALOG_PATH = "catalog.json"
#: What the catalog may weigh and hold.
MAX_CATALOG_BYTES = 12 * 1024 * 1024
MAX_ENTRIES = 5000
#: Opening the shop asks again after this many seconds (AC-12); once a day the collector asks for the notices of KARTEN-15.
OPEN_EVERY = 600
DAILY = 24 * 3600
#: After a failed attempt nothing is asked again for this long, so a GitHub that is down is not asked at every click.
RETRY_AFTER = 60
RETRY_DAILY = 3600


class CatalogError(Exception):
    """Something the shop tells an administrator in a sentence. ``status`` is the HTTP status it becomes."""

    def __init__(self, code: str, message: str, status: int = 502, **more: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.more = code, message, status, more

    def view(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.more}


def now() -> float:
    """The clock of the shop; a test sets it."""
    return time.time()


# -- the shape of the catalog -------------------------------------------------------------------

Text = Annotated[str, StringConstraints(max_length=2000)]
Short = Annotated[str, StringConstraints(max_length=200)]
LocalText = Short | Annotated[dict[str, Short], Field(max_length=20)]
VERSION = r"^\d{1,6}(\.\d{1,6}){0,3}$"
Version = Annotated[str, StringConstraints(pattern=VERSION, max_length=20)]
#: A path inside the repository: no leading slash, no ``..``, plain characters.
SAFE_PATH = re.compile(r"^(?!/)(?!.*(^|/)\.\.?(/|$))[A-Za-z0-9._@+ -]+(/[A-Za-z0-9._@+ -]+)*$")


def _safe(path: str) -> str:
    if not SAFE_PATH.match(path) or len(path) > 300:
        raise ValueError("not a path inside the repository")
    return path


class Person(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Annotated[str, StringConstraints(pattern=r"^\d{1,20}$")]
    login: Annotated[str, StringConstraints(max_length=100)] = ""


class Removal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    level: Literal["harmful", "not_useful", "withdrawn"]
    reason: Text = ""
    at: Short = ""


class Read(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Short = ""
    path: Short = ""


class Press(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: LocalText = ""
    method: Annotated[str, StringConstraints(max_length=10)] = ""
    path: Short = ""


class Files(BaseModel):
    model_config = ConfigDict(extra="ignore")
    definition: str
    readme: str | None = None
    changelog: str | None = None
    light: str | None = None
    dark: str | None = None

    def checked(self) -> Files:
        for name in ("definition", "readme", "changelog", "light", "dark"):
            value = getattr(self, name)
            if value is not None:
                _safe(value)
        return self


class Entry(BaseModel):
    """One entry of ``catalog.json``."""

    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, StringConstraints(pattern=r"^\d{1,20}/[a-z0-9][a-z0-9_-]{0,59}$")]
    type: Literal["card", "integration"]
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")]
    name: LocalText
    description: Text = ""
    author: Person
    version: Version
    min_nexdeck: Version | None = None
    category: Literal["media", "downloads", "network", "server", "smart_home", "other"] = "other"
    requires: list[Annotated[str, StringConstraints(pattern=r"^(custom:)?[a-z0-9][a-z0-9_-]{0,59}$")]] = Field(default_factory=list, max_length=10)
    class_: Literal["read", "buttons", "login"] = Field(default="read", alias="class")
    reads: list[Read] = Field(default_factory=list, max_length=50)
    buttons: list[Press] = Field(default_factory=list, max_length=10)
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    files: Files
    thumbs: int = Field(default=0, ge=0)
    discussion: Short | None = None
    based_on: Short | None = None
    license: Short | None = None
    updated_at: Short = ""
    removed: Removal | None = None

    @property
    def author_id(self) -> str:
        return self.id.partition("/")[0]


@dataclass
class Catalog:
    """A catalog as it was read, and when."""

    entries: list[Entry]
    generated_at: str
    fetched_at: float
    #: Whether the recalls in it were looked at already (``service.announce``).
    announced: bool = False
    by_id: dict[str, Entry] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {entry.id: entry for entry in self.entries}


def parse(raw: bytes) -> Catalog:
    """The catalog out of the bytes of ``catalog.json``, or ``CatalogError`` saying what is wrong."""

    def broken(why: str) -> CatalogError:
        return CatalogError("catalog_invalid", f"The catalog cannot be read: {why}.")

    if len(raw) > MAX_CATALOG_BYTES:
        raise broken("it is larger than 12 MB")
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise broken("it is not JSON") from None
    if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("entries"), list):
        raise broken("it is not a catalog of format 1")
    listed = data["entries"]
    if len(listed) > MAX_ENTRIES:
        raise broken(f"it has more than {MAX_ENTRIES} entries")
    if not listed:
        raise CatalogError("catalog_empty", "The catalog has no entries. Something is wrong with it, or with the repository.")
    entries: list[Entry] = []
    seen: set[str] = set()
    for number, one in enumerate(listed, start=1):
        try:
            entry = Entry.model_validate(one)
            entry.files.checked()
            if entry.id != f"{entry.author.id}/{entry.slug}":
                raise ValueError("the id does not match author and short name")
        except (ValidationError, ValueError) as failure:
            where = one.get("id") if isinstance(one, dict) and isinstance(one.get("id"), str) else f"number {number}"
            raise broken(f"entry {where[:80]} is wrong ({str(failure).splitlines()[0][:100]})") from None
        if entry.id in seen:
            raise broken(f"entry {entry.id} is there twice")
        seen.add(entry.id)
        entries.append(entry)
    return Catalog(entries, str(data.get("generated_at") or ""), now())


# -- asking GitHub -------------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    """One client for the life of the process (building one loads the CA bundle on the event loop)."""
    global _client
    if _client is None or _client.is_closed:
        _client = outbound_client(timeout=15, follow_redirects=True, headers={"User-Agent": "nexdeck", "Accept": ACCEPT})
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def fetch(repo: str, path: str, limit: int) -> bytes:
    """A file of the repository, at most ``limit`` bytes."""
    url = f"{API}/repos/{repo}/contents/{quote(path, safe='/')}"
    headers = {"Authorization": f"Bearer {key}"} if (key := state.token()) else {}
    try:
        async with http_client().stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                await response.aread()
                raise _refused(response)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    raise CatalogError("catalog_invalid", f"A file of the repository is larger than {limit // 1024} KB.")
            return bytes(body)
    except httpx.HTTPError as failure:
        # ⚠️ The class of the failure only: the text of an httpx error can carry the address, and a log is not the place for more.
        logger.info("GitHub could not be reached for %s: %s", path, failure.__class__.__name__)
        raise CatalogError("github_unreachable", UNREACHABLE) from None


UNREACHABLE = "GitHub cannot be reached. Cards you installed keep working."


def _refused(response: httpx.Response) -> CatalogError:
    code = response.status_code
    if code == 429 or (code == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
        return CatalogError("github_rate_limited", "GitHub allows no more requests for now. Try again later. Cards you installed keep working.")
    if code in (401, 403, 404):
        return CatalogError(
            "github_rejected",
            "GitHub did not give the catalog out. The repository may be private, the key missing or wrong, or the address not right.",
            github_status=code,
        )
    return CatalogError("github_unreachable", UNREACHABLE, github_status=code)


# -- keeping it ------------------------------------------------------------------------------------


@dataclass
class _Kept:
    catalog: Catalog | None = None
    failed_at: float = 0.0
    failure: CatalogError | None = None


_kept: dict[str, _Kept] = {}
_lock: asyncio.Lock | None = None


def forget() -> None:
    """The shop was turned off, or a test starts over: the next look asks again."""
    _kept.clear()


def known(repo: str) -> Catalog | None:
    """What was fetched last, without asking anybody."""
    kept = _kept.get(repo)
    return kept.catalog if kept else None


async def load(repo: str, *, max_age: float = OPEN_EVERY, retry_after: float = RETRY_AFTER) -> tuple[Catalog, CatalogError | None]:
    """The catalog, from memory while it is younger than ``max_age`` seconds, else fetched.

    The second value is why an older catalog is shown instead of a new one (GitHub out of reach), or ``None``. Raises
    ``CatalogError`` when there is nothing to show (EC-6, AC-10).
    """
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        kept = _kept.setdefault(repo, _Kept())
        if kept.catalog is not None and now() - kept.catalog.fetched_at < max_age:
            return kept.catalog, None
        if kept.failure is not None and now() - kept.failed_at < retry_after:
            return _stale(kept, kept.failure)
        try:
            catalog = parse(await fetch(repo, CATALOG_PATH, MAX_CATALOG_BYTES))
        except CatalogError as failure:
            kept.failed_at, kept.failure = now(), failure
            if failure.code == "catalog_invalid" or failure.code == "catalog_empty":
                logger.warning("The catalog of %s is not usable: %s", repo, failure.message)
            return _stale(kept, failure)
        kept.catalog, kept.failure = catalog, None
        return catalog, None


def _stale(kept: _Kept, failure: CatalogError) -> tuple[Catalog, CatalogError | None]:
    # A catalog that is wrong is an error even when an older one is at hand: the shop must not hide it (EC-6).
    if kept.catalog is not None and failure.code.startswith("github_"):
        return kept.catalog, failure
    raise failure
