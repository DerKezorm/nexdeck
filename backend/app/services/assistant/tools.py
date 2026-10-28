"""What the assistant may look at, and the one thing it may ask for: a button.

Every tool reads. None presses anything: ``propose_action`` checks that the
card offers the button right now (the same rule as a press, see
``Collector._refuse_unless_offered``), works out what it would hit and puts
it in front of the person, who presses it or not.

``container_log`` reads a container's log only after the person allowed it
for that container in this conversation; until then it answers that it has
asked, and the chat shows the question. The lines go through the same
redaction as nexdeck's own log before they leave.

What the tools return is short on purpose: every token of it goes to the
provider, and on Claude it is paid for.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Board, HealthCheck, Notice, Page, User, Widget, utcnow
from .. import chronicle, history, impact
from ..state import level_of, live

logger = logging.getLogger("nexdeck.assistant")

#: Cards that repeat the others; looking at them tells the assistant nothing new.
REPEATING = ("core.problems", "core.chronicle", "core.report")
LOG_LINES = 100


def _said(label: Any) -> str:
    """The label of a button as one text, for the people and the model that have no language of their own to pick: a custom card gives one per language, English first."""
    from ...adapters.custom import plain

    return plain(label)


@dataclass
class Bench:
    """What one answer gathered along the way: where it looked, what it proposes, what it asks."""

    db: Session
    user: User
    grants: list[str]
    citations: dict[str, dict[str, Any]] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[dict[str, Any]] = field(default_factory=list)
    #: The cards drafted in this answer, as the chat shows them (a chip that opens the editor, a small preview).
    drafts: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: int | None = None


TOOLS: list[dict[str, Any]] = [
    {
        "name": "needs_attention",
        "description": "What needs a look right now on every board: cards that are yellow or red with their reason and since when, services whose reachability check fails, and unread warnings of the bell. Start here for questions like 'is anything wrong'.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "find_cards",
        "description": "Cards on the boards whose title, service, kind or board contains the words; without words, all of them (up to 60). Each with its id, board, colour, reason and headline number. Use the id with card_details.",
        "input_schema": {"type": "object", "properties": {"words": {"type": "string", "description": "Part of a name, e.g. 'plex' or 'nas'. Empty for all."}}, "additionalProperties": False},
    },
    {
        "name": "card_details",
        "description": "Everything one card shows: its colour and reason, its numbers, its rows (up to 25) and the buttons it offers right now with their action ids and parameters.",
        "input_schema": {"type": "object", "properties": {"card_id": {"type": "integer"}}, "required": ["card_id"], "additionalProperties": False},
    },
    {
        "name": "chronicle",
        "description": "What changed, newest first: cards that turned yellow, red or green, outages and recoveries, maintenance, new versions, containers that restarted or were created anew, and changes made in nexdeck. For 'what happened' and 'what changed before this broke'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "How far back, 1 to 720. Default 24."},
                "group": {"type": "string", "enum": ["all", "cards", "versions", "nexdeck"]},
                "words": {"type": "string", "description": "Only lines whose name or reason contains this."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "metric_history",
        "description": "How one number of a card moved over the last hours (at most 24): lowest, highest, average, latest and a few points. Metric names come from card_details.",
        "input_schema": {
            "type": "object",
            "properties": {"card_id": {"type": "integer"}, "metric": {"type": "string"}, "hours": {"type": "integer"}},
            "required": ["card_id", "metric"], "additionalProperties": False,
        },
    },
    {
        "name": "container_log",
        "description": "The last lines of one container's log, from a card of Docker, Portainer or a Synology that lists containers. Logs can hold addresses and names, so the person is asked first; if they have not allowed it yet, this answers that you asked, and you should say in one sentence that you need their permission.",
        "input_schema": {
            "type": "object",
            "properties": {"card_id": {"type": "integer", "description": "A card that lists the container."}, "container": {"type": "string"}, "lines": {"type": "integer", "description": "1 to 100. Default 50."}},
            "required": ["card_id", "container"], "additionalProperties": False,
        },
    },
    {
        "name": "diagnosis",
        "description": "Why one service is in trouble, as its diagnosis page shows it: since when, the chronicle lines of the two hours before (its own and those of what it runs on, marked with via), what it hangs on and what hangs on it, its cards and checks, whether its container's log can be read, the buttons of its container, and the runbook the administrator wrote for it. Name the service by ref (integration:<id>, tile:<id>, container:<connection>:<name>, guest:<connection>:<vmid>) or by a card_id. For 'why is X broken' and 'what happened to X'. The runbook is the administrator's own advice; follow it.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}, "card_id": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "draft_card",
        "description": "Draft a custom card for the card editor from one connection and one path of its service. The person opens the draft in the editor and saves it there; you never save or place it. Without integration_id, say which service the person means in 'service' (a name or kind): when more than one connection fits, this answers with the list and you ask the person which one. Without path it lists the paths nexdeck knows of that kind. The shape of the answer (field names and types) goes to the provider, never the values, unless the person allowed it and you pass with_values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What the card should show, in the person's words."},
                "service": {"type": "string", "description": "Part of the name or kind of the connection, such as 'sonarr'."},
                "integration_id": {"type": "integer"},
                "path": {"type": "string", "description": "The path to read underneath the connection, such as /api/v3/queue."},
                "with_values": {"type": "boolean", "description": "Use the real values of the answer too. Asks the person first."},
            },
            "required": ["description"], "additionalProperties": False,
        },
    },
    {
        "name": "propose_action",
        "description": "Put a button of a card in front of the person, with what it would hit (streams that end, downloads that stop). You never press it; the person does. Only actions card_details lists for that card right now, with exactly the parameters listed there.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer"}, "action": {"type": "string", "description": "The action id from card_details."},
                "params": {"type": "object", "description": "The parameters card_details lists for that button."},
            },
            "required": ["card_id", "action"], "additionalProperties": False,
        },
    },
]


# -- shared lookups ---------------------------------------------------------------------


def _places(db: Session) -> dict[int, tuple[Widget, Page, Board]]:
    """Every card with its page and board. The assistant is for administrators, who may see them all."""
    pages = {page.id: page for page in db.scalars(select(Page))}
    boards = {board.id: board for board in db.scalars(select(Board))}
    out = {}
    for widget in db.scalars(select(Widget)):
        page = pages.get(widget.page_id)
        board = boards.get(page.board_id) if page is not None else None
        if page is not None and board is not None:
            out[widget.id] = (widget, page, board)
    return out


def _cite(bench: Bench, widget: Widget, page: Page, board: Board) -> None:
    bench.citations[f"card:{widget.id}"] = {"label": widget.title or widget.kind, "target": {"board": board.slug, "page": page.slug, "widget": widget.id}}


def _reason(data: Any) -> str:
    if data is None:
        return ""
    if data.error:
        return str(data.error)
    meta = data.meta or {}
    return str(meta.get("status_reason") or "")


def _headline(data: Any) -> str:
    if data is None or not data.primary:
        return ""
    primary = data.primary
    if (data.meta or {}).get("custom"):
        # A custom card keeps its texts language by language, and says its value as the server worked it out.
        from ...adapters.custom import plain

        unit = "" if primary.get("format") == "percent" else plain(primary.get("unit"))  # the text of a percentage has its % already
        return f"{plain(primary.get('label'))}: {primary.get('text', '')} {unit}".strip(": ").strip()
    return f"{primary.get('label', '')}: {primary.get('value', '')} {primary.get('unit', '')}".strip(": ").strip()


def _when(seconds: float | None) -> str:
    if not seconds:
        return ""
    from datetime import UTC, datetime

    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="minutes")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# -- the tools ----------------------------------------------------------------------------


def needs_attention(bench: Bench, _input: dict[str, Any]) -> str:
    db = bench.db
    places = _places(db)
    failing = {check.widget_id: check for check in db.scalars(select(HealthCheck).where(HealthCheck.enabled.is_(True), HealthCheck.last_ok.is_(False)))}
    rows = []
    for widget_id, (widget, page, board) in places.items():
        if widget.kind in REPEATING:
            continue
        data = live.get(widget_id)
        check = failing.get(widget_id)
        if check is not None:
            rows.append({"card_id": widget_id, "card": widget.title or widget.kind, "board": board.name, "colour": "red",
                         "reason": check.last_error or "does not answer", "since": check.down_since})
        elif data is not None and level_of(data) != "ok":
            rows.append({"card_id": widget_id, "card": widget.title or widget.kind, "board": board.name,
                         "colour": "red" if level_of(data) == "bad" else "yellow", "reason": _reason(data), "since": _when(live.since(widget_id))})
        else:
            continue
        _cite(bench, widget, page, board)
    warnings = [{"title": notice.title, "body": notice.body[:200], "at": notice.created_at}
                for notice in db.scalars(select(Notice).where(Notice.user_id == bench.user.id, Notice.read_at.is_(None), Notice.level.in_(("warn", "error", "bad")))
                                         .order_by(Notice.created_at.desc()).limit(10))]
    return _json({"cards": rows, "unread_warnings": warnings, "nothing_wrong": not rows and not warnings})


def find_cards(bench: Bench, given: dict[str, Any]) -> str:
    words = str(given.get("words") or "").lower().strip()
    rows = []
    for widget_id, (widget, _page, board) in _places(bench.db).items():
        integration = widget.integration.name if widget.integration is not None else ""
        haystack = " ".join((widget.title, widget.kind, integration, board.name)).lower()
        if words and words not in haystack:
            continue
        data = live.get(widget_id)
        rows.append({"card_id": widget_id, "title": widget.title or widget.kind, "kind": widget.kind, "service": integration, "board": board.name,
                     "colour": {"bad": "red", "warn": "yellow"}.get(level_of(data), "green") if data is not None else "unknown",
                     "reason": _reason(data), "headline": _headline(data)})
        if len(rows) >= 60:
            break
    return _json({"cards": rows})


def _offered(data: Any) -> list[tuple[str, dict[str, Any], list[Any]]]:
    from ..collector import Collector

    return Collector._offered(data)


def card_details(bench: Bench, given: dict[str, Any]) -> str:
    place = _places(bench.db).get(int(given.get("card_id") or 0))
    if place is None:
        return _json({"error": "No such card."})
    widget, page, board = place
    _cite(bench, widget, page, board)
    data = live.get(widget.id)
    if data is None:
        return _json({"card": widget.title, "note": "The card has not been read yet."})
    labels = {action.id: (_said(action.label), action.danger) for action in data.actions}
    buttons = []
    for action_id, params, _asks in _offered(data):
        label, danger = labels.get(action_id, (action_id, False))
        buttons.append({"action": action_id, "label": label, "danger": danger, "params": params})
    for item in data.items:
        for entry in item.get("actions") or [] if isinstance(item, dict) else []:
            entry = entry if isinstance(entry, dict) else entry.model_dump()
            for button in buttons:
                if button["action"] == entry.get("id") and button["params"] == dict(entry.get("params") or {}):
                    button.update(label=_said(entry.get("label")) or button["label"], danger=bool(entry.get("danger")), row=item.get("title"))
    rows = [{key: item.get(key) for key in ("title", "subtitle", "status", "value", "state") if item.get(key) not in (None, "")}
            for item in data.items[:25] if isinstance(item, dict)]
    return _json({
        "card_id": widget.id, "title": widget.title, "kind": widget.kind, "board": board.name,
        "colour": {"bad": "red", "warn": "yellow"}.get(level_of(data), "green"), "reason": _reason(data),
        "since": _when(live.since(widget.id)), "headline": _headline(data),
        "numbers": data.secondary[:10], "metrics": sorted(data.metrics)[:15], "rows": rows,
        "more_rows": max(0, len(data.items) - 25), "buttons": buttons[:30],
    })


def read_chronicle(bench: Bench, given: dict[str, Any]) -> str:
    try:
        hours = max(1, min(720, int(given.get("hours") or 24)))
    except (TypeError, ValueError):
        hours = 24
    group = str(given.get("group") or "all")
    lines = chronicle.query(bench.db, user=bench.user, kinds=chronicle.GROUPS.get(group), since=utcnow() - timedelta(hours=hours),
                            words=str(given.get("words") or ""), limit=60)
    if lines:
        bench.citations["chronicle"] = {"label": "chronicle", "chronicle": True}
    return _json({"lines": [{"at": line.at.isoformat(timespec="minutes"), "kind": line.kind, "name": line.name, "before": line.before,
                             "after": line.after, "detail": line.detail} for line in lines]})


def metric_history(bench: Bench, given: dict[str, Any]) -> str:
    place = _places(bench.db).get(int(given.get("card_id") or 0))
    if place is None:
        return _json({"error": "No such card."})
    try:
        hours = max(1, min(24, int(given.get("hours") or 24)))
    except (TypeError, ValueError):
        hours = 24
    points = history.series(bench.db, place[0].id, str(given.get("metric") or ""), hours=hours)
    _cite(bench, *place)
    if not points:
        return _json({"note": "No history for this metric in that time."})
    values = [value for _ts, value in points]
    step = max(1, len(points) // 12)
    return _json({"lowest": min(values), "highest": max(values), "average": round(sum(values) / len(values), 3), "latest": values[-1],
                  "points": [{"at": _when(ts), "value": round(value, 3)} for ts, value in points[::step]]})


#: What a foreign log may carry besides a key in an address, which is all
#: nexdeck's own log needs to hide (``journal.redact``).
#: ⚠️ Not after \b: in DB_PASSWORD or POSTGRES_PASSWORD the underscore is a
#: word character, and the password went out (found 25.10.2026).
_SECRET_PAIR = re.compile(
    r"(?i)(?<![a-z0-9])((?:pass(?:word|wd)?|pwd|secret(?:[_-]?key)?|client[_-]?secret|token|access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|auth|authorization)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',&;]+)"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_USER_IN_ADDRESS = re.compile(r"(://[^:/\s@]+:)([^@\s/]+)@")
_JWT = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}")


def log_redact(line: str) -> str:
    """A foreign container's log line with the usual secrets masked before it goes to the provider.

    ⚠️ Best effort, which is why the person is asked first: a log can say
    anything in any form.
    """
    # The scheme first: "Authorization: Bearer x" would otherwise lose the word "Bearer" and keep x.
    line = _BEARER.sub(lambda hit: hit.group(1) + " ***", line)
    line = _SECRET_PAIR.sub(lambda hit: hit.group(1) + "***", line)
    line = _USER_IN_ADDRESS.sub(lambda hit: hit.group(1) + "***@", line)
    return _JWT.sub("***", line)


def _gives_logs(kind: str) -> bool:
    from ...adapters import get_adapter
    from ...adapters.base import Adapter

    try:
        return type(get_adapter(kind)).container_log is not Adapter.container_log
    except Exception:  # noqa: BLE001 - an unknown kind gives no logs
        return False


async def container_log(bench: Bench, given: dict[str, Any]) -> str:
    place = _places(bench.db).get(int(given.get("card_id") or 0))
    container = str(given.get("container") or "").strip()
    if place is None or place[0].integration is None or not container:
        return _json({"error": "Name a card that lists containers, and one of its containers."})
    widget = place[0]
    if not _gives_logs(widget.integration.kind):
        return _json({"error": f"A {widget.integration.kind} connection gives no container logs. Docker, Portainer and a Synology do."})
    grant = f"log:{widget.integration_id}:{container}"
    if grant not in bench.grants:
        bench.permissions.append({"kind": "log", "card_id": widget.id, "container": container, "grant": grant})
        return _json({"asked": True, "note": "The person has been asked whether you may read this log. Nothing was read."})
    from ...adapters.base import AdapterError
    from ..collector import collector
    from ..journal import redact

    # ⚠️ A connection in the demo points at no engine; asked anyway, it reached
    # the Docker socket of whatever machine nexdeck runs on.
    if collector._demo_active(widget.integration):
        return _json({"error": "This connection is in the demo and has no real log."})
    try:
        lines = max(1, min(LOG_LINES, int(given.get("lines") or 50)))
    except (TypeError, ValueError):
        lines = 50
    adapter, config, ctx = await collector.resolve_integration(widget.integration_id)
    try:
        found = await adapter.container_log(config, ctx, container, lines) or []
    except AdapterError as failure:
        return _json({"error": failure.message})
    kept = [log_redact(redact(line))[:400] for line in found if line.strip()][-lines:]
    _cite(bench, *place)
    return _json({"container": container, "lines": kept})


async def propose_action(bench: Bench, given: dict[str, Any]) -> str:
    place = _places(bench.db).get(int(given.get("card_id") or 0))
    action_id = str(given.get("action") or "")
    params = given.get("params") if isinstance(given.get("params"), dict) else {}
    if place is None:
        return _json({"error": "No such card."})
    widget, page, board = place
    data = live.get(widget.id)
    offered = [(one_id, fixed) for one_id, fixed, _asks in _offered(data) if one_id == action_id]
    if not any(fixed == params for _id, fixed in offered):
        return _json({"error": "The card does not offer that button with these parameters right now. Look at card_details again."})
    label, danger, row = action_id, False, ""
    for action in data.actions if data is not None else []:
        if action.id == action_id and dict(action.params) == params:
            label, danger = _said(action.label), action.danger
    for item in data.items if data is not None else []:
        for entry in item.get("actions") or [] if isinstance(item, dict) else []:
            entry = entry if isinstance(entry, dict) else entry.model_dump()
            if entry.get("id") == action_id and dict(entry.get("params") or {}) == params:
                label, danger, row = _said(entry.get("label")) or label, bool(entry.get("danger")), str(item.get("title") or "")
    facts = await impact.facts(widget.id, action_id, params)
    _cite(bench, widget, page, board)
    bench.proposals.append({"card_id": widget.id, "card": widget.title or widget.kind, "row": row, "action": action_id, "label": label,
                            "danger": danger, "params": params, "impact": facts})
    return _json({"proposed": True, "impact": facts, "note": "The button is in front of the person now. Say what it does in one sentence; do not claim it ran."})


def diagnose(bench: Bench, given: dict[str, Any]) -> str:
    from .. import dependencies, diagnosis

    ref = str(given.get("ref") or "").strip()
    if not ref and given.get("card_id"):
        place = _places(bench.db).get(int(given.get("card_id") or 0))
        ref = dependencies.subject_of(place[0]) or "" if place is not None else ""
    page = diagnosis.build(bench.db, ref) if ref else None
    if page is None:
        return _json({"error": "Name a service by its ref or one of its cards by card_id."})
    places = _places(bench.db)
    for card in page["cards"]:
        if card["id"] in places:
            _cite(bench, *places[card["id"]])
    return _json(diagnosis.summary(page))


def _readable(kind: str) -> bool:
    """Whether a card of its own can read through a connection of this kind."""
    from ...adapters import get_adapter

    try:
        return bool(get_adapter(kind).raw_access)
    except Exception:  # noqa: BLE001 - an own kind of connection reads like the JSON API
        return kind.startswith("custom:")


NO_OWN_CARDS = "cannot be read by a card of its own. Say so, and name the way out: a connection of the kind JSON API, or an own connection that describes the service."


def _listed(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"integration_id": row.id, "name": row.name, "kind": row.kind} for row in rows][:20]


async def draft_card(bench: Bench, given: dict[str, Any]) -> str:
    import hashlib

    from ...adapters.base import AdapterError
    from ...adapters.custom import plain
    from ...cards import ai, card_reads, credentials, demo, load, schema
    from ...models import Conversation, ConversationDraft, Integration
    from ...routers.cards import _ask, _connection
    from . import chat, settings

    description = str(given.get("description") or "").strip()[:2000]
    if bench.conversation_id is None or not description:
        return _json({"error": "Say what the card should show."})
    rows = list(bench.db.scalars(select(Integration).order_by(Integration.id)))
    chosen = next((row for row in rows if row.id == given.get("integration_id")), None)
    if chosen is None:
        words = str(given.get("service") or "").lower().strip()
        found = [row for row in rows if not words or words in f"{row.name} {row.kind}".lower()]
        usable = [row for row in found if _readable(row.kind)]
        if not rows:
            return _json({"error": "There is no connection yet. A card reads through one; add it under System first."})
        if found and not usable:
            return _json({"error": f"A {found[0].kind} connection {NO_OWN_CARDS}"})
        if not usable:
            return _json({"error": "No connection matches that. Ask the person which service they mean.", "connections": _listed([row for row in rows if _readable(row.kind)])})
        if len(usable) > 1:
            return _json({"ask": True, "note": "More than one connection fits. Ask the person which one, in one sentence, and do not guess.", "connections": _listed(usable)})
        chosen = usable[0]
    if not _readable(chosen.kind):
        return _json({"error": f"A {chosen.kind} connection {NO_OWN_CARDS}"})
    path = str(given.get("path") or "").strip()
    if not path:
        return _json({"error": "Name the path to read.", "known_paths": [read["path"] for read in card_reads.reads_of(chosen.kind)][:12]})
    try:
        request = schema.Request(id="probe", path=path)
    except ValueError:
        return _json({"error": "The path starts with a single / and names no host."})
    if next(credentials.find(path), None) is not None:
        return _json({"error": "The path holds something that looks like a key. A card holds no secrets."})
    values = bool(given.get("with_values"))
    grant = f"values:{chosen.id}:{hashlib.sha1(path.encode()).hexdigest()[:10]}"  # noqa: S324 - a name, not a secret
    if values and grant not in bench.grants:
        bench.permissions.append({"kind": "values", "integration_id": chosen.id, "integration": chosen.name, "path": path, "grant": grant})
        return _json({"asked": True, "note": "The person has been asked whether the real values may go to the provider. Nothing was sent."})
    if values:
        # ⚠️ The permission is for this one request (KARTEN-18 AC-4): it is used up here, whether the request works or not.
        bench.grants.remove(grant)
        held = bench.db.get(Conversation, bench.conversation_id)
        if held is not None:
            held.grants = [one for one in held.grants or [] if one != grant]
    config, key = settings.stored(bench.db), settings.key_of(bench.db)
    integration_id, conversation_id = chosen.id, bench.conversation_id
    bench.db.commit()
    try:
        adapter, connection, ctx = await _connection(integration_id)
        answer = await _ask(adapter, connection, ctx, request)
        outcome = await ai.generate(ai.Ask(mode="new", description=description, connection_kind=adapter.kind, path=path, answer=answer, include_values=values), config, key)
    except AdapterError as failure:
        return _json({"error": f"The service could not be read: {failure.message}"})
    except ai.AiError as failure:
        return _json({"error": failure.message})
    if not outcome.ok:
        return _json({"error": "The provider's card did not pass nexdeck's check, even after a second try.", "problems": [problem["message"] for problem in outcome.problems][:5]})
    text = outcome.yaml
    # The preview in the chat needs examples: the real answer, made up. They stay in nexdeck.
    matching = {one.id: answer for one in outcome.definition.requests if one.path == path}
    if matching and not outcome.definition.demo:
        try:
            made, _cut = demo.disguise(matching)
            with_examples = ai.with_demo(text, made)
            load.load_definition(with_examples)
            text = with_examples
        except (AdapterError, load.CardInvalid):
            pass
    name = plain(outcome.definition.name)
    draft = ConversationDraft(conversation_id=conversation_id, name=name[:200], yaml=text, summary=outcome.summary, sent=outcome.sent)
    bench.db.add(draft)
    bench.db.commit()
    bench.drafts.append({"id": draft.id, "name": name, "form": outcome.definition.form, "summary": outcome.summary, "sent": outcome.sent,
                         "keep_days": chat.KEEP_DAYS, "url": f"/system/custom-cards/new?draft={draft.id}"})
    return _json({"drafted": True, "draft_id": draft.id, "name": name, "form": outcome.definition.form,
                  "note": "The draft is in front of the person with an Open in editor button. Say in a sentence or two what the card shows; it is not saved, and never say that it is."})


HANDLERS = {
    "needs_attention": needs_attention, "find_cards": find_cards, "card_details": card_details, "chronicle": read_chronicle,
    "metric_history": metric_history, "container_log": container_log, "diagnosis": diagnose, "propose_action": propose_action, "draft_card": draft_card,
}


async def run(bench: Bench, name: str, given: dict[str, Any]) -> tuple[str, bool]:
    """``(result, is_error)``. A tool that fails says so to the model; it never ends the answer."""
    handler = HANDLERS.get(name)
    if handler is None:
        return _json({"error": f"No tool named {name}."}), True
    try:
        result = handler(bench, given or {})
        if hasattr(result, "__await__"):
            result = await result
        return result, '"error"' in result[:12]
    except Exception as failure:  # noqa: BLE001 - the model hears that it failed, the log hears why
        logger.exception("The assistant's tool %s failed.", name)
        return _json({"error": f"The tool failed ({failure.__class__.__name__})."}), True
