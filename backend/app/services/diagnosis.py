"""Why is this broken? (roadmap M6)

One page per service that puts together what the other parts already know:
since when it is in trouble, what happened in the two hours before (to it
and to everything it hangs on), what it hangs on and what hangs on it, its
cards and checks, its container's log when asked for, and the runbook an
administrator wrote for it. Nothing here repairs anything; the buttons are
the cards' own, with what they would hit.

A subject is a reference as in the inventory: ``integration:<id>``,
``tile:<widget id>``, ``container:<integration>:<name>`` or
``guest:<integration>:<vmid>``. Administrators only, all of it.

⚠️ Read only. Building the page asks no service anything; the log is read
when the person presses the button, never on opening.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models import (
    Board,
    Event,
    HealthCheck,
    Integration,
    Page,
    Runbook,
    Thing,
    User,
    Widget,
    utcnow,
)
from . import chronicle, dependencies
from .state import live

logger = logging.getLogger("nexdeck.diagnosis")

#: How far back "just before" reaches from the start of the trouble.
BEFORE = timedelta(hours=2)
#: How far back a past trouble is looked for when nothing is wrong now.
LOOK_BACK = timedelta(days=30)
#: Lines on the page at most; the chronicle has the rest.
MAX_LINES = 60
#: Kinds of line that say the subject went wrong or came back.
TROUBLE = ("card", "outage")
BACK = ("card", "recovery")
CONTAINER_KINDS = ("container_restarted", "container_recreated")
#: An ancestor whose trouble began this close around the subject's was its cause.
CAUSE_SLACK = timedelta(minutes=10)

RUNBOOK_TEXT = 4000
RUNBOOK_LINK = 600


def _aware(at: datetime | None) -> datetime | None:
    if at is None:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def parse(ref: str) -> tuple[str, int, str] | None:
    """``(kind, number, rest)`` of a reference, or None when it is no reference at all."""
    kind, _, rest = (ref or "").partition(":")
    if kind in ("integration", "tile"):
        return (kind, int(rest), "") if rest.isdigit() else None
    if kind in ("container", "guest"):
        number, _, name = rest.partition(":")
        return (kind, int(number), name) if number.isdigit() and name else None
    return None


def _icon(kind: str) -> str:
    from ..adapters import get_adapter

    try:
        return get_adapter(kind).icon
    except Exception:  # noqa: BLE001 - an adapter that is gone leaves the icon out
        return ""


def subject(db: Session, ref: str) -> dict[str, Any] | None:
    """What the reference names, or None when it names nothing that is there."""
    parsed = parse(ref)
    if parsed is None:
        return None
    kind, number, rest = parsed
    if kind == "integration":
        row = db.get(Integration, number)
        if row is None:
            return None
        host, port = dependencies.address_of(dependencies._service_address(row))
        return {"ref": ref, "kind": "integration", "service": row.kind, "name": row.name, "icon": _icon(row.kind),
                "detail": f"{host}:{port}" if host and port else host, "demo": row.demo}
    if kind == "tile":
        tile = db.get(Widget, number)
        if tile is None:
            return None
        host, port = dependencies.address_of(dependencies._service_address(tile=tile))
        return {"ref": ref, "kind": "tile", "service": "", "name": tile.title or tile.kind,
                "detail": f"{host}:{port}" if host and port else host, "icon": tile.icon, "demo": False}
    thing = db.scalar(select(Thing).where(Thing.ref == ref))
    if thing is None:
        return None
    engine = db.get(Integration, thing.integration_id)
    return {"ref": ref, "kind": thing.kind, "service": engine.kind if engine else "", "name": thing.name, "icon": _icon(engine.kind) if engine else "",
            "detail": thing.image, "engine": engine.name if engine else "", "state": thing.state,
            "demo": bool(engine and engine.demo)}


def widgets_of(db: Session, ref: str) -> list[Widget]:
    """The cards that show this subject: every card of a connection, or the tile itself."""
    parsed = parse(ref)
    if parsed is None:
        return []
    kind, number, _rest = parsed
    if kind == "integration":
        return list(db.scalars(select(Widget).where(Widget.integration_id == number).order_by(Widget.id)))
    if kind == "tile":
        tile = db.get(Widget, number)
        return [tile] if tile is not None else []
    return []


def _own_lines(ref: str):  # noqa: ANN202 - an SQL condition
    """The chronicle lines about this subject itself."""
    kind, number, rest = parse(ref) or ("", 0, "")
    if kind == "integration":
        # A container's restart is a line of its own subject, not of the engine it runs on.
        return and_(Event.integration_id == number, Event.kind.not_in(CONTAINER_KINDS))
    if kind == "tile":
        return Event.widget_id == number
    if kind == "container":
        return and_(Event.integration_id == number, Event.kind.in_(CONTAINER_KINDS), Event.name == rest)
    # A guest has no lines of its own yet: the hypervisor's cards say what they see.
    return Event.id == -1


# -- since when -----------------------------------------------------------------------------


def now_trouble(db: Session, ref: str) -> dict[str, Any] | None:
    """How the subject stands now, if badly: ``level``, ``since`` and ``reason``."""
    worst, since, reason = "", None, ""
    rank = {"warn": 1, "bad": 2}
    widgets = widgets_of(db, ref)
    checks = {check.widget_id: check for check in db.scalars(select(HealthCheck).where(
        HealthCheck.widget_id.in_([widget.id for widget in widgets] or [-1]), HealthCheck.enabled.is_(True)))}
    for widget in widgets:
        data = live.get(widget.id)
        check = checks.get(widget.id)
        level, said, began = "", "", None
        if check is not None and check.last_ok is False:
            level, said, began = "bad", check.last_error or "Not answering", _aware(check.down_since)
        elif data is not None and data.error:
            level, said = "bad", str(data.error)
        elif data is not None and data.status in ("warn", "bad"):
            level, said = data.status, str((data.meta or {}).get("status_reason") or "")
        if not level:
            continue
        if began is None:
            seconds = live.since(widget.id)
            began = datetime.fromtimestamp(seconds, UTC) if seconds else None
        if rank[level] > rank.get(worst, 0):
            worst, reason = level, said
        if began is not None and (since is None or began < since):
            since = began
    parsed = parse(ref)
    if parsed and parsed[0] in ("container", "guest"):
        thing = db.scalar(select(Thing).where(Thing.ref == ref))
        if thing is not None and thing.state and thing.state not in ("running", "online"):
            worst, reason = "bad", thing.state
        elif dependencies.is_down(db, ref):
            worst = "bad"
    if not worst:
        return None
    if since is None:
        # Nothing read since when: the chronicle's last line that turned it.
        row = db.scalar(select(Event).where(_own_lines(ref), Event.kind.in_(TROUBLE), Event.level.in_(("warn", "bad")))
                        .order_by(Event.at.desc(), Event.id.desc()).limit(1))
        since = _aware(row.at) if row is not None else None
    return {"level": worst, "since": since, "reason": reason}


def past_trouble(db: Session, ref: str, at: datetime | None) -> dict[str, Any] | None:
    """The last trouble that ended: at or before ``at`` when given, else within the last 30 days."""
    statement = select(Event).where(_own_lines(ref), Event.kind.in_(TROUBLE), Event.level.in_(("warn", "bad")))
    if at is not None:
        statement = statement.where(Event.at <= at + timedelta(minutes=1))
    else:
        statement = statement.where(Event.at >= utcnow() - LOOK_BACK)
    began = db.scalar(statement.order_by(Event.at.desc(), Event.id.desc()).limit(1))
    if began is None:
        return None
    # Walk back over lines that only made it worse or kept it bad: the trouble began at the first of them.
    start = began
    while True:
        before = db.scalar(select(Event).where(_own_lines(ref), Event.kind.in_(TROUBLE + BACK), Event.at < start.at)
                           .order_by(Event.at.desc(), Event.id.desc()).limit(1))
        # ⚠️ A line that turned it green again can be missing (nexdeck was down then):
        # a day of silence ends the trouble rather than joining it to an older one.
        if before is None or before.level not in ("warn", "bad") or _aware(start.at) - _aware(before.at) > timedelta(days=1):
            break
        start = before
    ended = db.scalar(select(Event).where(_own_lines(ref), Event.kind.in_(BACK), Event.level == "ok", Event.at >= began.at)
                      .order_by(Event.at, Event.id).limit(1))
    return {"level": "bad" if any(one.level == "bad" for one in (start, began)) else "warn",
            "since": _aware(start.at), "until": _aware(ended.at) if ended is not None else None,
            "reason": began.detail}


# -- the page -----------------------------------------------------------------------------


def _lines(db: Session, refs: list[str], start: datetime, end: datetime) -> list[tuple[str, Event]]:
    """Chronicle lines of these subjects between ``start`` and ``end``, oldest first, each with whose it is."""
    found: dict[int, tuple[str, Event]] = {}
    for one in refs:
        rows = db.scalars(select(Event).where(_own_lines(one), Event.at >= start, Event.at <= end)
                          .order_by(Event.at.desc(), Event.id.desc()).limit(MAX_LINES))
        for row in rows:
            found.setdefault(row.id, (one, row))
    ordered = sorted(found.values(), key=lambda pair: (_aware(pair[1].at), pair[1].id))
    return ordered[-MAX_LINES:]


def _node(db: Session, ref: str) -> dict[str, Any]:
    parsed = parse(ref)
    kind = parsed[0] if parsed else ""
    out = {"ref": ref, "kind": kind, "name": dependencies.name_of(db, ref), "down": dependencies.is_down(db, ref), "detail": ""}
    if kind in ("container", "guest"):
        thing = db.scalar(select(Thing).where(Thing.ref == ref))
        if thing is not None:
            engine = db.get(Integration, thing.integration_id)
            out.update(detail=" · ".join(one for one in (engine.name if engine else "", thing.image) if one), state=thing.state)
    elif kind == "integration":
        row = db.get(Integration, parsed[1])
        out["detail"] = row.kind if row else ""
    return out


def _cards(db: Session, ref: str) -> list[dict[str, Any]]:
    out = []
    for widget in widgets_of(db, ref):
        page = db.get(Page, widget.page_id)
        board = db.get(Board, page.board_id) if page is not None else None
        data = live.get(widget.id)
        status = "bad" if data is not None and data.error else (data.status if data is not None else "unknown")
        reason = str(data.error) if data is not None and data.error else str(((data.meta or {}).get("status_reason") if data is not None else "") or "")
        row: dict[str, Any] = {"id": widget.id, "title": widget.title or widget.kind, "kind": widget.kind, "status": status,
                               "reason": reason, "board": board.name if board else ""}
        if board is not None and page is not None:
            row["target"] = {"board": board.slug, "page": page.slug, "widget": widget.id}
        out.append(row)
    return out


def _checks(db: Session, ref: str) -> list[dict[str, Any]]:
    widgets = {widget.id: widget for widget in widgets_of(db, ref)}
    out = []
    for check in db.scalars(select(HealthCheck).where(HealthCheck.widget_id.in_(list(widgets) or [-1])).order_by(HealthCheck.id)):
        out.append({"id": check.id, "card": widgets[check.widget_id].title if check.widget_id in widgets else "",
                    "kind": check.kind, "target": check.target, "enabled": check.enabled, "ok": check.last_ok,
                    "error": check.last_error, "latency_ms": check.last_latency_ms,
                    "down_since": chronicle.since_of(check.down_since), "checked": chronicle.since_of(check.last_checked_at)})
    return out


def container_of(db: Session, ref: str) -> Thing | None:
    """The container or guest this subject is, or the nearest one it runs in."""
    parsed = parse(ref)
    if parsed and parsed[0] in ("container", "guest"):
        return db.scalar(select(Thing).where(Thing.ref == ref))
    for one in dependencies.ancestors(db, ref):
        if one.startswith(("container:", "guest:")):
            return db.scalar(select(Thing).where(Thing.ref == one))
    return None


def _gives_logs(kind: str) -> bool:
    from .assistant.tools import _gives_logs as gives

    return gives(kind)


def log_place(db: Session, ref: str) -> dict[str, Any]:
    """Whose log the button reads, or why there is none."""
    thing = container_of(db, ref)
    if thing is None or thing.kind != "container":
        return {"available": False, "why": "no_container"}
    engine = db.get(Integration, thing.integration_id)
    if engine is None or not _gives_logs(engine.kind):
        return {"available": False, "why": "no_logs", "container": thing.name, "engine": engine.name if engine else ""}
    if engine.demo:
        return {"available": False, "why": "demo", "container": thing.name, "engine": engine.name}
    return {"available": True, "container": thing.name, "engine": engine.name, "ref": thing.ref}


def _buttons(db: Session, ref: str) -> list[dict[str, Any]]:
    """The buttons of the container or guest, as the cards that list it offer them."""
    thing = container_of(db, ref)
    if thing is None:
        return []
    vmid = thing.ref.split(":", 2)[2] if thing.kind == "guest" else ""
    out: list[dict[str, Any]] = []
    for widget in db.scalars(select(Widget).where(Widget.integration_id == thing.integration_id).order_by(Widget.id)):
        data = live.get(widget.id)
        if data is None:
            continue
        for item in data.items:
            if not isinstance(item, dict) or not item.get("actions"):
                continue
            actions = [one for one in item["actions"] if isinstance(one, dict)]
            if thing.kind == "container":
                same = str(item.get("title") or "") == thing.name
            else:
                same = any(str((one.get("params") or {}).get("vmid", "")) == vmid for one in actions)
            if not same:
                continue
            for action in actions:
                out.append({"widget_id": widget.id, "card": widget.title or widget.kind, "item": str(item.get("title") or thing.name),
                            "id": str(action.get("id") or ""), "label": str(action.get("label") or ""),
                            "icon": str(action.get("icon") or ""), "params": action.get("params") or {},
                            "confirm": bool(action.get("confirm")), "danger": bool(action.get("danger"))})
        if out:
            # The first card that lists it is enough; another would offer the same buttons again.
            break
    return out


def runbook_of(db: Session, ref: str) -> dict[str, Any]:
    row = db.scalar(select(Runbook).where(Runbook.ref == ref))
    if row is None:
        return {"text": "", "link": "", "updated": None, "by": ""}
    by = db.get(User, row.updated_by) if row.updated_by else None
    return {"text": row.text, "link": row.link, "updated": chronicle.since_of(row.updated_at), "by": by.username if by else ""}


def write_runbook(db: Session, ref: str, text: str, link: str, user: User) -> dict[str, Any]:
    """Keep what to do; an empty text and link remove the runbook."""
    text = (text or "").strip()[:RUNBOOK_TEXT]
    link = (link or "").strip()
    if link and not link.lower().startswith(("http://", "https://")):
        raise ValueError("bad_link")
    if len(link) > RUNBOOK_LINK:
        raise ValueError("bad_link")
    row = db.scalar(select(Runbook).where(Runbook.ref == ref))
    if not text and not link:
        if row is not None:
            db.delete(row)
        db.commit()
        return runbook_of(db, ref)
    if row is None:
        row = Runbook(ref=ref)
        db.add(row)
    row.text, row.link, row.updated_at, row.updated_by = text, link, utcnow(), user.id
    db.commit()
    return runbook_of(db, ref)


def build(db: Session, ref: str, at: datetime | None = None) -> dict[str, Any] | None:
    """The whole page for one subject, or None when the reference names nothing."""
    about = subject(db, ref)
    if about is None:
        return None
    current = now_trouble(db, ref) if at is None else None
    trouble = current or past_trouble(db, ref, at)
    now = utcnow()
    if current is not None:
        state = "now"
    elif trouble is not None:
        state = "past"
    else:
        state = "ok"
    start = trouble["since"] if trouble and trouble.get("since") else None
    end = trouble.get("until") if trouble else None
    # Two hours before it began, up to now while it lasts or a little after it ended.
    window_end = now if state == "now" or end is None else min(now, end + timedelta(minutes=15))
    window_start = start - BEFORE if start else window_end - BEFORE

    above = dependencies.ancestors(db, ref)
    lines = _lines(db, [ref, *above], window_start, window_end)
    viewed = chronicle.view(db, [row for _whose, row in lines])
    for (whose, _row), line in zip(lines, viewed, strict=True):
        line["whose"] = "self" if whose == ref else whose
        line["via"] = "" if whose == ref else dependencies.name_of(db, whose)

    cause = ""
    if state == "now":
        cause = dependencies.cause_ref(db, ref)
    elif state == "past" and start is not None:
        # The furthest ancestor whose own trouble began around the same time.
        for one in reversed(above):
            began = db.scalar(select(Event.id).where(_own_lines(one), Event.kind.in_(TROUBLE), Event.level.in_(("warn", "bad")),
                                                     Event.at >= start - CAUSE_SLACK, Event.at <= start + timedelta(minutes=2)))
            if began is not None:
                cause = one
                break
    cause_view = None
    if cause:
        cause_view = {"ref": cause, "name": dependencies.name_of(db, cause), "down": dependencies.is_down(db, cause)}
        cause_trouble = now_trouble(db, cause) if state == "now" else None
        if cause_trouble and cause_trouble.get("since"):
            cause_view["since"] = cause_trouble["since"].timestamp()

    below = dependencies.descendants(db, ref)
    return {
        "subject": about,
        "state": state,
        "level": trouble["level"] if trouble else "ok",
        "since": start.timestamp() if start else None,
        "until": end.timestamp() if end else None,
        "reason": trouble.get("reason", "") if trouble else "",
        "window": {"from": window_start.timestamp(), "to": window_end.timestamp()},
        "cause": cause_view,
        "lines": viewed,
        "above": [_node(db, one) for one in reversed(above)],
        "below": [_node(db, one) for one in below[:30]],
        "cards": _cards(db, ref),
        "checks": _checks(db, ref),
        "log": log_place(db, ref),
        "buttons": _buttons(db, ref),
        "runbook": runbook_of(db, ref),
    }


def summary(page: dict[str, Any]) -> dict[str, Any]:
    """The page as the assistant gets it: everything but the buttons' parameters."""
    return {
        "subject": page["subject"], "state": page["state"], "level": page["level"],
        "since": page["since"], "until": page["until"], "reason": page["reason"], "cause": page["cause"],
        "lines": [{key: line.get(key) for key in ("at", "kind", "level", "name", "before", "after", "detail", "via")} for line in page["lines"]],
        "hangs_on": [{"name": one["name"], "kind": one["kind"], "down": one["down"]} for one in page["above"]],
        "carries": [{"name": one["name"], "kind": one["kind"], "down": one["down"]} for one in page["below"]],
        "cards": [{key: card.get(key) for key in ("id", "title", "status", "reason", "board")} for card in page["cards"]],
        "checks": [{key: check.get(key) for key in ("kind", "target", "ok", "error", "down_since")} for check in page["checks"]],
        "log": {key: page["log"].get(key) for key in ("available", "container", "engine", "why")},
        "buttons": [{key: one[key] for key in ("card", "item", "label", "danger")} for one in page["buttons"]],
        "runbook": {"text": page["runbook"]["text"], "link": page["runbook"]["link"]},
    }
