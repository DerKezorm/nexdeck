"""The guards: rules that must hold for every address and every text.

Each guard asserts it looked at something (a floor), so an empty scan can
never pass by accident.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.routing import APIRoute

from app import deps
from app.adapters import all_adapters, get_adapter
from app.adapters.nexview import FINDING_LABELS
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"
FRONTEND = ROOT / "frontend" / "src"

#: Addresses that work without any sign-in, each with the reason.
PUBLIC: dict[str, str] = {
    "GET /api/health": "the container healthcheck",
    "GET /api/v1/setup/status": "the app decides between wizard and sign-in from it",
    "POST /api/v1/setup": "creates the first administrator; refuses once one exists",
    "GET /api/v1/setup/boards-exist": "a count, no content",
    "POST /api/v1/auth/login": "the sign-in itself",
    "POST /api/v1/auth/logout": "clears the cookie of the caller",
    "GET /api/v1/auth/providers": "the sign-in buttons",
    "GET /api/v1/auth/oidc/{slug}/login": "starts a sign-in",
    "GET /api/v1/auth/oidc/{slug}/callback": "the provider returns here",
    "GET /api/v1/icons/{name}.{ext}": "logos, like any image; kiosk displays have no session",
    "GET /api/v1/assets/{asset_id}/{filename}": "board backgrounds for kiosk displays",
    "GET /api/v1/kiosk": "checks the kiosk token itself",
    "GET /{path:path}": "the single-page app",
}

AUTH_DEPENDENCIES = {deps.optional_user, deps.current_user, deps.admin_user, deps.not_guest}


def _dependencies(dependant) -> set:  # noqa: ANN001
    found = set()
    for sub in dependant.dependencies:
        found.add(sub.call)
        found |= _dependencies(sub)
    return found


def test_every_address_decides_who_may_call_it() -> None:
    """Every route either carries an auth dependency or is listed as public with a reason."""
    unguarded: list[str] = []
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = f"{method} {route.path}"
            checked += 1
            if key in PUBLIC:
                continue
            if not _dependencies(route.dependant) & AUTH_DEPENDENCIES:
                unguarded.append(key)
    assert checked >= 80, "the route table shrank; is the app wired?"
    assert unguarded == [], "addresses without an auth decision (add a dependency, or list them in PUBLIC with a reason):\n  " + "\n  ".join(unguarded)


def test_public_list_has_no_dead_entries() -> None:
    existing = {f"{m} {r.path}" for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    dead = [key for key in PUBLIC if key not in existing]
    assert dead == [], f"PUBLIC lists addresses that no longer exist: {dead}"


def test_every_operation_has_a_readable_summary() -> None:
    short: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        if len((route.summary or "").split()) < 2:
            short.append(f"{sorted(route.methods)} {route.path}: {route.summary!r}")
    assert short == [], "operations whose summary says too little on /api/docs:\n  " + "\n  ".join(short)


GERMAN = re.compile(r"[äöüÄÖÜß]")


def test_backend_texts_are_english() -> None:
    """No German letters in any string the backend could show or log."""
    offenders: list[str] = []
    scanned = 0
    for path in BACKEND.rglob("*.py"):
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if GERMAN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert scanned >= 60
    assert offenders == [], "German text in the backend:\n  " + "\n  ".join(offenders)


PERSONAL_EMAIL = re.compile(r"[\w.+-]+@(?!example\.|localhost)[\w-]+\.[a-z]{2,}", re.IGNORECASE)
PRIVATE_LAN = re.compile(r"\b10\.10\.\d+\.\d+\b")


def test_no_personal_data_in_the_repository() -> None:
    """Placeholders and examples never carry a real address."""
    offenders: list[str] = []
    scanned = 0
    for folder, patterns in ((BACKEND, ("*.py",)), (FRONTEND, ("*.ts", "*.tsx", "*.json")), (ROOT / "docs", ("*.md",)), (ROOT, ("README.md", "docker-compose.yml", ".env.example"))):
        for pattern in patterns:
            for path in folder.glob(pattern) if folder == ROOT else folder.rglob(pattern):
                if "node_modules" in path.parts or "fixtures" in path.parts:
                    continue
                scanned += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                if PERSONAL_EMAIL.search(text) and "mailto:admin@localhost" not in text:
                    offenders.append(f"{path.relative_to(ROOT)}: e-mail address")
                if PRIVATE_LAN.search(text):
                    offenders.append(f"{path.relative_to(ROOT)}: private network address")
    assert scanned >= 80
    assert offenders == [], "\n".join(offenders)


def test_no_em_dashes_in_texts() -> None:
    offenders: list[str] = []
    for folder, patterns in ((BACKEND, ("*.py",)), (FRONTEND, ("*.ts", "*.tsx", "*.json"))):
        for pattern in patterns:
            for path in folder.rglob(pattern):
                if ".test." in path.name or path.name == "format.ts":
                    continue
                if "—" in path.read_text(encoding="utf-8", errors="replace"):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], "em dashes in:\n  " + "\n  ".join(offenders)


def test_error_details_carry_code_and_message() -> None:
    """Every HTTPException in the routers goes through ``error()`` or spells out both fields."""
    offenders: list[str] = []
    for path in (BACKEND / "routers").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"HTTPException\((.*?)\)", text, re.DOTALL):
            body = match.group(1)
            if '"code"' not in body or '"message"' not in body:
                offenders.append(f"{path.name}: {body[:60]!r}")
    assert offenders == []


# -- texts the frontend translates by their English wording --------------------

GERMAN_TEXTS = ROOT / "frontend" / "src" / "i18n" / "texts.de.json"
ADAPTERS = BACKEND / "adapters"
LABEL_LITERAL = re.compile(r'"(?:label|subtitle)": "([^"]+)"')
ACTION_LABEL = re.compile(r'Action\([^)]*?label="([^"]+)"')


def _german_texts() -> dict[str, dict[str, str]]:
    return json.loads(GERMAN_TEXTS.read_text(encoding="utf-8"))


def _looks_like_data(text: str) -> bool:
    """Sizes, dates, sensor identifiers and protocol names pass through untranslated."""
    if len(text) < 3 or any(ch.isdigit() for ch in text) or "_" in text or "=" in text:
        return True
    if not any(ch.isalpha() for ch in text):
        return True
    return text.islower() and " " not in text and len(text) <= 5


def test_every_adapter_text_has_a_german_translation() -> None:
    """Field labels, help texts, widget names and descriptions are English in the
    adapters; the interface translates them by their English text."""
    german = _german_texts()["adapter"]
    missing: set[str] = set()
    checked = 0
    for adapter in all_adapters():
        texts = [adapter.description]
        for field in adapter.fields:
            texts += [field.label, field.help, *(label for _value, label in field.options)]
        for widget in adapter.widgets:
            texts += [widget.label, widget.description]
            for field in widget.options:
                texts += [field.label, field.help, *(label for _value, label in field.options)]
        for text in texts:
            if text:
                checked += 1
                if text not in german:
                    missing.add(text)
    assert checked > 200
    assert not missing, f"adapter texts without a German entry: {sorted(missing)}"


def test_every_data_label_has_a_german_translation() -> None:
    """Labels of values, chips, rows and actions come from the adapters as English
    words; the cards translate them by text."""
    texts = _german_texts()
    # A word that names a widget may also label a value; the frontend falls back the same way.
    german = {**texts["adapter"], **texts["labels"]}
    missing: set[str] = set()
    checked = 0
    for path in ADAPTERS.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pattern in (LABEL_LITERAL, ACTION_LABEL):
            for text in pattern.findall(source):
                if _looks_like_data(text):
                    continue
                checked += 1
                if text not in german:
                    missing.add(text)
    for text in FINDING_LABELS.values():
        checked += 1
        if text not in german:
            missing.add(text)
    assert checked > 80
    assert not missing, f"data labels without a German entry: {sorted(missing)}"


def test_german_texts_are_complete_and_clean() -> None:
    texts = _german_texts()
    assert len(texts["adapter"]) > 200 and len(texts["labels"]) > 80
    for section in ("adapter", "labels"):
        for english, german in texts[section].items():
            assert english.strip() and german.strip(), (section, english)
            assert "\u2014" not in german, (section, english)


def test_client_only_widgets_are_exactly_the_basics() -> None:
    """The settings sheet hides the refresh interval for widgets that draw themselves."""
    assert all(widget.client_only or widget.kind == "problems" for widget in get_adapter("core").widgets), "problems reads the server's live state"
    others = [f"{adapter.kind}.{widget.kind}" for adapter in all_adapters() if adapter.kind != "core" for widget in adapter.widgets if widget.client_only]
    assert others == []


def test_only_confirmed_adapters_are_out_of_beta() -> None:
    """Beta means "not yet seen against a live instance". The list below is what was
    confirmed, every widget of every adapter against a real service (2026-09-05);
    an adapter leaves it only by being confirmed, never by default."""
    confirmed = {adapter.kind for adapter in all_adapters() if not adapter.beta and adapter.needs_integration}
    # iCal and the JSON API talk to no particular product; they were never beta.
    assert confirmed == {"emby", "homeassistant", "ical", "jellyfin", "jsonapi", "lidarr", "nexview", "plex", "radarr", "reolink", "sabnzbd", "seerr", "sonarr", "synology", "unifi"}
