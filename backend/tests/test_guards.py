"""The guards: rules that must hold for every address and every text.

Each guard asserts it looked at something (a floor), so an empty scan can
never pass by accident.
"""

from __future__ import annotations

import inspect
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
    "POST /api/v1/auth/login/second-step": "its other half; the ticket from the first step is the credential",
    "POST /api/v1/auth/forgot": "somebody who forgot their password has nothing to sign in with",
    "GET /api/v1/auth/reset/{token}": "the link is the credential, and it says nothing about who holds it",
    "POST /api/v1/auth/reset": "the same link, redeemed",
    "POST /api/v1/auth/logout": "clears the cookie of the caller",
    "GET /api/v1/auth/providers": "the sign-in buttons",
    "GET /api/v1/auth/oidc/{slug}/login": "starts a sign-in",
    "GET /api/v1/auth/oidc/{slug}/callback": "the provider returns here",
    "GET /api/v1/icons/{name}.{ext}": "logos, like any image; kiosk displays have no session",
    "GET /api/v1/assets/{asset_id}/{filename}": "board backgrounds for kiosk displays",
    "GET /api/v1/kiosk": "checks the kiosk token itself",
    "POST /api/v1/kiosk/session": "the door of a wall display: the token in the body is the credential",
    "GET /{path:path}": "the single-page app",
}

AUTH_DEPENDENCIES = {deps.optional_user, deps.current_user, deps.admin_user, deps.not_guest}


def api_routes() -> list[APIRoute]:
    """Every route of the app, however the framework keeps them.

    ⚠️ FastAPI 0.141 stopped flattening an included router into ``app.routes``
    and puts a wrapper there instead. Walking the list without descending
    found one route out of a hundred and eighty, and the guard below would
    have passed on an app with no authentication at all. That is what the
    floor in each test is for; this walks both shapes.
    """
    found: list[APIRoute] = []
    pending = list(app.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        inner = getattr(route, "original_router", None)
        if inner is not None:
            pending.extend(inner.routes)
    return found


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
    for route in api_routes():
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = f"{method} {route.path}"
            checked += 1
            if key in PUBLIC:
                continue
            if not _dependencies(route.dependant) & AUTH_DEPENDENCIES:
                unguarded.append(key)
    assert checked >= 80, "the route table shrank; is the app wired?"
    assert unguarded == [], "addresses without an auth decision (add a dependency, or list them in PUBLIC with a reason):\n  " + "\n  ".join(unguarded)


#: Addresses that change something and that a guest may still call, each with
#: the reason. Everything else that changes something must be closed to guests.
GUESTS_MAY_CHANGE: dict[str, str] = {
    "POST /api/v1/setup": "creates the first administrator; there is nobody yet",
    "POST /api/v1/auth/login": "signing in",
    "POST /api/v1/auth/login/second-step": "its other half",
    "POST /api/v1/auth/logout": "leaving",
    "POST /api/v1/auth/forgot": "somebody who forgot their password",
    "POST /api/v1/auth/reset": "the same link, redeemed",
    "POST /api/v1/kiosk/session": "a wall display at the door",
    "PATCH /api/v1/auth/me": "own display name, language and theme",
    "POST /api/v1/auth/password": "own password",
    "POST /api/v1/auth/me/avatar": "own picture",
    "DELETE /api/v1/auth/me/avatar": "own picture",
    "DELETE /api/v1/auth/sessions/{session_id}": "own sessions",
    "POST /api/v1/auth/two-factor/start": "own second factor",
    "POST /api/v1/auth/two-factor/confirm": "own second factor",
    "POST /api/v1/auth/two-factor/recovery-codes": "own second factor",
    "DELETE /api/v1/auth/two-factor": "own second factor",
    "POST /api/v1/notices/read": "marking one's own notices as read",
    "DELETE /api/v1/notices/{notice_id}": "one of one's own notices",
    "DELETE /api/v1/notices": "all of one's own read notices",
    "DELETE /api/v1/tokens/{token_id}": "one's own API token; the handler checks it belongs to the caller",
    "POST /api/v1/push/subscribe": "own browser notifications",
    "DELETE /api/v1/push/subscribe": "own browser notifications",
    "POST /api/v1/channels/{channel_id}/test": "own notification channel",
}


#: Asking a board for more than "view". A guest never gets more.
ABOVE_VIEW = re.compile(r'(require_board(_id)?|board_for_viewer(_id)?)\([^)]*"(edit|act)"|permission not in \("(edit|act)"')


def _handler_and_helpers(function) -> str:  # noqa: ANN001
    """A handler's source together with the helpers it names from its module.

    One level deep on purpose: several routes leave the permission check to a
    small helper next to them, and a guard that only read the handler would
    call those unguarded.
    """
    source = inspect.getsource(function)
    module = inspect.getmodule(function)
    for name, value in vars(module or object).items():
        if name in source and inspect.isfunction(value) and value is not function:
            source += inspect.getsource(value)
    return source


def test_a_guest_cannot_reach_anything_that_changes_something() -> None:
    """"Guests may only look" has to be true of every address, not most of them.

    ⚠️ The older guard asked whether a route carried *any* of the four auth
    dependencies, which a route open to every signed-in account does too. So it
    would have passed on a route that let a guest delete a board. This one asks
    which dependency, for everything that is not a read.
    """
    open_to_guests: list[str] = []
    checked = 0
    for route in api_routes():
        for method in sorted(route.methods - {"HEAD", "OPTIONS", "GET"}):
            key = f"{method} {route.path}"
            if key in PUBLIC or key in GUESTS_MAY_CHANGE:
                continue
            checked += 1
            if _dependencies(route.dependant) & {deps.admin_user, deps.not_guest}:
                continue
            # Or it asks for a level on a board, which a guest cannot have:
            # ``board_permission`` hands a guest "view" and nothing above it,
            # ownership included, since 07.09.2026.
            if ABOVE_VIEW.search(_handler_and_helpers(route.endpoint)):
                continue
            open_to_guests.append(key)
    assert checked >= 40, "hardly anything was checked, so this guard proves nothing"
    assert open_to_guests == [], (
        "addresses that change something and are open to guests (add AdminUser or MemberUser, "
        "or list them in GUESTS_MAY_CHANGE with a reason):\n  " + "\n  ".join(open_to_guests)
    )


def test_the_guest_exception_list_has_no_dead_entries() -> None:
    existing = {f"{m} {r.path}" for r in api_routes() for m in r.methods}
    dead = [key for key in GUESTS_MAY_CHANGE if key not in existing]
    assert dead == [], f"GUESTS_MAY_CHANGE lists addresses that no longer exist: {dead}"


def test_every_outbound_client_comes_from_the_one_factory() -> None:
    """Nobody builds an httpx client of their own.

    ⚠️ The guard against calling loopback and the link-local range hangs on the
    client, not on the call, because that is the only way it also sees the
    second hop of a redirect. A client built anywhere else carries no guard,
    and there were eighteen such places before 07.09.2026. Use
    ``outbound_client()`` from ``adapters.base``; it takes ``guard=False`` for
    the Docker socket, which reaches no host by name.
    """
    offenders: list[str] = []
    scanned = 0
    for path in BACKEND.rglob("*.py"):
        scanned += 1
        if path.name == "base.py" and path.parent.name == "adapters":
            continue  # the factory itself
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "httpx.AsyncClient(" in line:
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert scanned >= 60, "nothing was scanned, so this guard proves nothing"
    assert offenders == [], "clients built past the outbound guard:\n  " + "\n  ".join(offenders)


#: Word stems that mean a field is asking for a credential.
CREDENTIAL_STEMS = ("key", "token", "secret", "password", "passwd", "auth", "header", "credential")
#: Fields whose wording matches a stem while holding no credential, each with
#: the reason. Every entry here is a decision somebody has to defend.
NOT_A_CREDENTIAL: dict[tuple[str, str], str] = {
    ("proxmox", "token_id"): "names which token is used, like a user name; the secret is token_secret",
    ("pbs", "token_id"): "the same, next to its own token_secret",
}


def test_every_field_that_asks_for_a_credential_is_marked_secret() -> None:
    """``secret=True`` decides two things at once.

    ⚠️ It says whether the value is encrypted in the database, and whether it
    is masked before a connection is handed to a member. The JSON API adapter
    had one field that asks for credentials in so many words, placeholder
    ``X-Api-Key: abc``, and it carried neither. Every account down to a guest
    could read it in the clear from ``GET /api/v1/integrations``.
    """
    bare: list[str] = []
    checked = 0
    for adapter in all_adapters():
        for field in adapter.fields:
            checked += 1
            if field.secret or (adapter.kind, field.name) in NOT_A_CREDENTIAL:
                continue
            # Name and label only. A placeholder is an example address as often
            # as it is a credential, and "https://auth.example.com" is not one.
            wording = f"{field.name} {field.label}".lower()
            if any(stem in wording for stem in CREDENTIAL_STEMS):
                bare.append(f"{adapter.kind}.{field.name} ({field.label!r}, placeholder {field.placeholder!r})")
    assert checked >= 100, "no fields were scanned, so this guard proves nothing"
    assert bare == [], (
        "fields asking for a credential without secret=True (stored unencrypted, "
        "and readable by every member):\n  " + "\n  ".join(bare)
    )


def test_public_list_has_no_dead_entries() -> None:
    existing = {f"{m} {r.path}" for r in api_routes() for m in r.methods}
    dead = [key for key in PUBLIC if key not in existing]
    assert dead == [], f"PUBLIC lists addresses that no longer exist: {dead}"


def test_every_operation_has_a_readable_summary() -> None:
    short: list[str] = []
    for route in api_routes():
        if not route.include_in_schema:
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


def test_every_drawn_symbol_exists_in_the_frontend() -> None:
    """An adapter without a logo in the collections may name a drawn symbol
    instead. The frontend bundles a fixed set of them and quietly falls back to
    a grey box for anything else, which looks exactly like a broken logo."""
    source = (FRONTEND / "components" / "ServiceIcon.tsx").read_text(encoding="utf-8")
    block = source.split("SYMBOLS: Record", 1)[1].split("\n}", 1)[0]
    known = set(re.findall(r"^\s+'?([a-z0-9-]+)'?:", block, re.MULTILINE))
    assert len(known) > 40, "the symbol map was not found"
    missing = sorted(
        f"{adapter.kind}: {adapter.icon}"
        for adapter in all_adapters()
        if adapter.icon.startswith("lucide:") and adapter.icon.removeprefix("lucide:") not in known
    )
    assert missing == [], "adapters naming a symbol the frontend does not bundle:\n  " + "\n  ".join(missing)


def test_every_channel_text_has_a_german_translation() -> None:
    """The notification channels are written in English like the adapters, and
    the settings page translates them the same way. Without this guard a new
    field would stand there in English in a German interface, which is exactly
    what the walkthrough found on the adapters."""
    from app.services.channels import KINDS
    from app.services.notify import EVENTS

    german = _german_texts()["adapter"]
    missing: set[str] = set()
    checked = 0
    texts: list[str] = [kind.help for kind in KINDS.values()]
    for kind in KINDS.values():
        for field in kind.fields:
            texts += [field.label, field.help, *(label for _value, label in field.options)]
    texts += list(EVENTS.values())
    for text in texts:
        if text:
            checked += 1
            if text not in german:
                missing.add(text)
    assert checked > 25
    assert not missing, f"channel texts without a German entry: {sorted(missing)}"


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
    assert confirmed == {"adguard", "audiobookshelf", "authentik", "beszel", "deluge", "docker", "emby", "evcc", "glances", "gotify", "grafana", "headscale", "homeassistant", "ical", "jellyfin", "jsonapi", "kavita", "komga", "lidarr", "navidrome", "nextcloud", "nexview", "npm", "ntfy", "nzbget", "paperless", "pihole", "plex", "portainer", "prometheus", "prowlarr", "qbittorrent", "radarr", "reolink", "sabnzbd", "seerr", "sonarr", "syncthing", "synology", "tdarr", "technitium", "traefik", "transmission", "unifi", "unmanic"}


#: Routers whose changing addresses deliberately write nothing, with the reason.
QUIET_ROUTERS: dict[str, str] = {
    "notices": "marking one's own notices read or deleting them is housekeeping, not history",
    "journal": "clearing the log writes its own line from the service; the rest only reads",
}


def test_every_router_that_changes_something_writes_it_down() -> None:
    """A log window over a server that logs nothing shows an empty list.

    ⚠️ Measured on 06.09.2026: twenty-one of twenty-three routers wrote not one
    line. A hundred and nine addresses, and five of them left a trace. The
    window was the easy half; this is the half that keeps it worth opening.

    Coarse on purpose. It cannot tell whether the *right* thing is written, only
    that a router which changes state is not silent as a whole, which is
    exactly how it went wrong.
    """
    routers = Path(deps.__file__).parent / "routers"
    silent: list[str] = []
    checked = 0
    for path in sorted(routers.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        source = path.read_text(encoding="utf-8")
        changing = len(re.findall(r"@router\.(?:post|put|patch|delete)", source))
        if changing == 0:
            continue
        checked += 1
        if path.stem in QUIET_ROUTERS:
            continue
        if "logger." not in source:
            silent.append(f"{path.stem} ({changing} changing addresses)")
    assert checked >= 15, "the routers moved; is this looking at the right folder?"
    assert silent == [], (
        "routers that change something and write nothing (add a line, or list it in "
        "QUIET_ROUTERS with a reason):\n  " + "\n  ".join(silent)
    )


def test_the_quiet_list_has_no_dead_entries() -> None:
    routers = Path(deps.__file__).parent / "routers"
    existing = {path.stem for path in routers.glob("*.py")}
    dead = [name for name in QUIET_ROUTERS if name not in existing]
    assert dead == [], f"QUIET_ROUTERS names routers that no longer exist: {dead}"


def test_no_event_in_the_catalogue_is_dead() -> None:
    """Every event somebody can subscribe to has to be emitted from somewhere.

    ⚠️ Measured on 06.09.2026: three of the seven in the list had never been
    emitted from anywhere in the code. Subscribing to one of those was a
    promise nobody was keeping, and nothing said so.
    """
    from app.services.notify import EVENTS

    app_dir = Path(deps.__file__).parent
    sources = {
        path: path.read_text(encoding="utf-8")
        for path in app_dir.rglob("*.py")
        if "__pycache__" not in path.parts and path.name != "notify.py"
    }
    assert len(sources) >= 40, "the source tree moved; is this looking at the right folder?"

    dead: list[str] = []
    for event in EVENTS:
        if event == "test":
            continue  # sent by the button next to a channel, from the router
        if any(f'"{event}"' in text or f"'{event}'" in text for text in sources.values()):
            continue
        dead.append(event)
    assert dead == [], (
        "events somebody can subscribe to that nothing ever emits (emit them, "
        f"or take them out of EVENTS): {dead}"
    )


def test_every_renderer_has_a_floor_and_no_card_goes_below_it() -> None:
    """A card must not be draggable to a size its drawing cannot bear.

    ⚠️ Until 06.09.2026 the grid used a card's *default* size as its floor, so
    ``min_size`` did nothing and nobody noticed that 56 value cards claimed to
    work at one cell by one. The moment the floor became real, the weather
    card drew its sun on top of its own temperature.
    """
    from app.adapters.base import DEFAULT_MIN, RENDERER_MIN

    used: set[str] = set()
    too_small: list[str] = []
    checked = 0
    for adapter in all_adapters():
        for widget in adapter.widgets:
            checked += 1
            used.add(widget.renderer)
            floor = RENDERER_MIN.get(widget.renderer, DEFAULT_MIN)
            if widget.min_size[0] < floor[0] or widget.min_size[1] < floor[1]:
                too_small.append(f"{adapter.kind}.{widget.kind} ({widget.renderer}): {tuple(widget.min_size)} < {floor}")
            if widget.default_size[0] < widget.min_size[0] or widget.default_size[1] < widget.min_size[1]:
                too_small.append(f"{adapter.kind}.{widget.kind}: opens smaller than it may be dragged")
    assert checked >= 150, "the widget list shrank; is this looking at the right place?"
    assert too_small == [], "cards that may be dragged smaller than they can draw:\n  " + "\n  ".join(too_small)

    missing = sorted(used - set(RENDERER_MIN))
    assert missing == [], (
        "renderers with no floor of their own; they fall back to the default, "
        f"which is a guess: {missing}"
    )
