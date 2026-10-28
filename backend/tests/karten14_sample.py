"""A pretend GitHub with a Workshop repository in it, for the tests of the Card shop (KARTEN-14, KARTEN-15).

Nothing here reaches the network: ``respx`` answers every request to ``api.github.com`` from the files of the pretend
repository, and fails the test for a request to any other address.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import forget_all_custom
from app.cards import exchange, load
from app.cards import integration as integration_loader
from app.services.collector import collector
from app.workshop import catalog, files

from .cards_sample import VALUE_CARD, changed
from .conftest import CSRF, setup_admin

REPO = "DerKezorm/nexdeck-workshop"
AUTHOR = "4242"
#: A PNG, as far as the shop looks: the signature and some bytes.
PNG = b"\x89PNG\r\n\x1a\n" + b"picture"


def card_text(slug: str = "queue-size", text: str = VALUE_CARD, version: str = "1.0.0") -> str:
    return changed('version: "1.0.0"', f'version: "{version}"', changed("slug: queue-size", f"slug: {slug}", text))


def entry(text: str, author: str = AUTHOR, **more: Any) -> dict[str, Any]:
    """The catalog entry of a card text, with the checksum of exactly that text."""
    if exchange._INTEGRATION.search(text):  # noqa: SLF001
        short, version, minimum, requires, buttons, kind = integration_loader.load_integration(text, saved=[]).definition.short, "1.0.0", None, [], False, "integration"
    else:
        data = load.load_definition(text).definition
        short, version, minimum, requires, buttons, kind = data.slug, data.version, data.min_nexdeck, list(data.requires), bool(data.buttons), "card"
    found: dict[str, Any] = {
        "id": f"{author}/{short}", "type": kind, "slug": short, "name": "Name of " + short, "description": "A card for the tests.",
        "author": {"id": author, "login": "someone"}, "version": version,
        "min_nexdeck": minimum, "category": "media", "requires": requires,
        "class": "buttons" if buttons else "read", "reads": [], "buttons": [],
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "files": {
            "definition": f"entries/{author}/{short}/definition.yaml", "readme": f"entries/{author}/{short}/README.md",
            "changelog": f"entries/{author}/{short}/CHANGELOG.md", "light": f"entries/{author}/{short}/preview-light.png",
            "dark": f"entries/{author}/{short}/preview-dark.png",
        },
        "thumbs": 3, "discussion": None, "based_on": None, "updated_at": "2026-10-20T10:00:00Z", "removed": None,
    }
    found.update(more)
    return found


class GitHub:
    """The pretend repository: the files by path, what to do when asked, and what was asked."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.entries: list[dict[str, Any]] = []
        #: ``ok``, ``down`` (nothing answers), or an HTTP status that every request gets.
        self.mode: str | int = "ok"
        self.requests: list[httpx.Request] = []
        self.catalog_override: bytes | None = None
        #: Where every request is sent on with a redirect, when set; and what arrived at ``stranger.example.com`` meanwhile.
        self.redirect: str | None = None
        self.strangers: list[httpx.Request] = []
        #: The repository was renamed: its old address answers with a redirect to ``/repositories/1/…`` on the same host.
        self.renamed = False

    def publish(self, text: str, **more: Any) -> dict[str, Any]:
        """Put a definition in the repository with its texts and pictures, and list it in the catalog (replacing an older one)."""
        found = entry(text, **more)
        self.entries = [one for one in self.entries if one["id"] != found["id"]] + [found]
        place = found["files"]
        self.files[place["definition"]] = text.encode("utf-8")
        self.files[place["readme"]] = f"About {found['slug']}.".encode()
        self.files[place["changelog"]] = f"Changes of {found['version']}.".encode()
        self.files[place["light"]] = self.files[place["dark"]] = PNG
        return found

    def catalog_bytes(self) -> bytes:
        if self.catalog_override is not None:
            return self.catalog_override
        return json.dumps({"format": 1, "generated_at": "2026-10-28T00:00:00Z", "entries": self.entries}).encode()

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.redirect is not None:
            return httpx.Response(302, headers={"location": self.redirect})
        if self.mode == "down":
            raise httpx.ConnectError("no route to host")
        if isinstance(self.mode, int):
            return httpx.Response(self.mode, json={"message": "no"})
        prefix = f"/repos/{REPO}/contents/"
        if self.renamed and request.url.path.startswith(prefix):
            return httpx.Response(301, headers={"location": f"https://api.github.com/repositories/1/contents/{request.url.path[len(prefix):]}"})
        if self.renamed and request.url.path.startswith("/repositories/1/contents/"):
            prefix = "/repositories/1/contents/"
        if not request.url.path.startswith(prefix):
            return httpx.Response(404, json={"message": "Not Found"})
        path = unquote(request.url.path[len(prefix):])
        body = self.catalog_bytes() if path == "catalog.json" else self.files.get(path)
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404, json={"message": "Not Found"})

    def stranger(self, request: httpx.Request) -> httpx.Response:
        self.strangers.append(request)
        return httpx.Response(200, content=self.catalog_bytes())

    def count(self, path: str = "") -> int:
        return len([one for one in self.requests if unquote(one.url.path).endswith(path)])


@pytest.fixture
def github() -> Iterator[GitHub]:
    fake = GitHub()
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as network:
        network.route(host="api.github.com").mock(side_effect=fake.answer)
        network.route(host="stranger.example.com").mock(side_effect=fake.stranger)
        catalog.forget()
        files.forget()
        yield fake
    catalog.forget()
    files.forget()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """The clock of the shop, as a list of one number a test moves."""
    now = [1_000_000.0]
    monkeypatch.setattr(catalog, "now", lambda: now[0])
    yield now


@pytest.fixture
def shop(client: TestClient, github: GitHub, clock: list[float], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An administrator is signed in and the shop is on, in front of the pretend repository."""
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    turned = client.put("/api/v1/workshop/settings", json={"enabled": True}, headers=CSRF)
    assert turned.status_code == 200, turned.text
    yield client
    # An own kind made by a test stays in the registry of the process: the tests that count the kinds would see it.
    forget_all_custom()
