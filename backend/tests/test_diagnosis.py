"""Why is this broken (roadmap M6, 25.10.2026): one page per service, put together from what nexdeck already knows."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import WidgetData
from app.db import db_session
from app.models import HealthCheck, Runbook, utcnow
from app.services import chronicle
from app.services.assistant import chat, providers, tools
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin
from .test_dependencies import _chain, _connection, _container, _match, _things


def _card(client: TestClient, kind: str, integration_id: int | None = None, **extra: object) -> dict:
    boards = client.get("/api/v1/boards").json()
    board = boards[0] if boards else client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    page = client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["id"]
    body: dict = {"kind": kind, **extra}
    if integration_id is not None:
        body["integration_id"] = integration_id
    made = client.post(f"/api/v1/pages/{page}/widgets", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    widget = made.json()["widget"]
    collector.unschedule(widget["id"])
    return widget


def _page(client: TestClient, ref: str, **query: object) -> dict:
    answer = client.get("/api/v1/diagnosis", params={"ref": ref, **query})
    assert answer.status_code == 200, answer.text
    return answer.json()


def _plex_down(client: TestClient) -> tuple[int, int, int, dict, dict]:
    """Plex in a container on docker-live, both red; Plex's check failing for 20 minutes."""
    pve, engine, plex = _chain(client)
    engine_card = _card(client, "docker.containers", engine)
    plex_card = _card(client, "plex.nowplaying", plex)
    for card in (engine_card, plex_card):
        live.set(card["id"], WidgetData(status="unknown", error="Connection refused"))
    with db_session() as db:
        db.add(HealthCheck(widget_id=plex_card["id"], target="http://10.0.0.65:32400", enabled=True, last_ok=False,
                           last_error="Connection refused", down_since=utcnow() - timedelta(minutes=20)))
    return pve, engine, plex, engine_card, plex_card


# -- since when, and what came before ---------------------------------------------------------------


def test_the_two_hours_before_hold_its_own_lines_and_those_of_what_it_runs_on(client: TestClient) -> None:
    _pve, engine, plex, _engine_card, plex_card = _plex_down(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    now = utcnow()
    with db_session() as db:
        chronicle.record("version", integration_id=engine, name="docker-live", before="27.1", after="27.2", at=now - timedelta(minutes=95), db=db)
        chronicle.record("connection_changed", integration_id=plex, name="Plex", at=now - timedelta(minutes=25), db=db)
        chronicle.record("outage", level="bad", widget_id=plex_card["id"], integration_id=plex, name="Plex", at=now - timedelta(minutes=19), db=db)
        chronicle.record("version", integration_id=engine, name="docker-live", before="27.0", after="27.1", at=now - timedelta(minutes=150), db=db)
        chronicle.record("version", integration_id=radarr, name="Radarr", before="5.1", after="5.2", at=now - timedelta(minutes=30), db=db)
        chronicle.record("container_restarted", integration_id=engine, name="nginx", at=now - timedelta(minutes=10), db=db)
        chronicle.record("container_recreated", integration_id=engine, name="plex", before="a", after="b", at=now - timedelta(minutes=21), db=db)

    page = _page(client, f"integration:{plex}")
    assert page["state"] == "now" and page["level"] == "bad"
    assert abs(page["since"] - (now - timedelta(minutes=20)).timestamp()) < 2, "the failing check says since when"
    assert abs(page["window"]["from"] - (now - timedelta(minutes=140)).timestamp()) < 2
    # The connections and cards this test made are lines of the window too.
    seen = [(line["kind"], line["name"], line["via"]) for line in page["lines"] if line["kind"] not in ("connection_added", "card_added")]
    assert seen == [
        ("version", "docker-live", "docker-live"),
        ("connection_changed", "Plex", ""),
        ("container_recreated", "plex", "plex"),
        ("outage", "Plex", ""),
    ], "not before the window, not another service, not another container of the same engine"
    assert page["cause"]["ref"] == f"integration:{engine}" and page["cause"]["name"] == "docker-live"
    assert [node["ref"] for node in page["above"]][-1] == f"container:{engine}:plex", "furthest first, the nearest above the service"
    assert page["checks"][0]["ok"] is False and page["checks"][0]["error"] == "Connection refused"
    assert page["cards"][0]["status"] == "bad" and page["cards"][0]["target"]["widget"] == plex_card["id"]


def test_a_trouble_that_ended_is_found_from_a_moment_in_it(client: TestClient) -> None:
    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    card = _card(client, "radarr.queue", radarr)
    live.set(card["id"], WidgetData(status="ok"))
    began = utcnow() - timedelta(hours=5)
    with db_session() as db:
        chronicle.record("card", level="warn", widget_id=card["id"], integration_id=radarr, name="Radarr", before="ok", after="warn", at=began, db=db)
        chronicle.record("card", level="bad", widget_id=card["id"], integration_id=radarr, name="Radarr", before="warn", after="bad",
                         detail="Disk full", at=began + timedelta(minutes=5), db=db)
        chronicle.record("card", level="ok", widget_id=card["id"], integration_id=radarr, name="Radarr", before="bad", after="ok", at=began + timedelta(minutes=40), db=db)
        chronicle.record("card", level="bad", widget_id=card["id"], integration_id=radarr, name="Radarr", before="ok", after="bad", at=began - timedelta(days=2), db=db)

    page = _page(client, f"integration:{radarr}", at=(began + timedelta(minutes=10)).timestamp())
    assert page["state"] == "past" and page["level"] == "bad" and page["reason"] == "Disk full"
    assert abs(page["since"] - began.timestamp()) < 2, "from the first line that turned it, not the worst"
    assert abs(page["until"] - (began + timedelta(minutes=40)).timestamp()) < 2
    assert [line["after"] for line in page["lines"]] == ["warn", "bad", "ok"]

    latest = _page(client, f"integration:{radarr}")
    assert latest["state"] == "past" and abs(latest["since"] - began.timestamp()) < 2, "without a moment: the last trouble"


def test_a_service_that_was_never_in_trouble_shows_the_last_two_hours(client: TestClient) -> None:
    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    page = _page(client, f"integration:{radarr}")
    assert page["state"] == "ok" and page["since"] is None and page["cause"] is None
    assert abs((page["window"]["to"] - page["window"]["from"]) - 7200) < 2
    assert page["subject"]["name"] == "Radarr" and page["subject"]["detail"] == "10.9.9.9:7878"


def test_a_cause_that_has_recovered_is_still_named_for_a_past_trouble(client: TestClient) -> None:
    _pve, engine, plex = _chain(client)
    began = utcnow() - timedelta(hours=3)
    with db_session() as db:
        chronicle.record("card", level="bad", integration_id=engine, name="docker-live", before="ok", after="bad", at=began - timedelta(minutes=2), db=db)
        chronicle.record("outage", level="bad", integration_id=plex, name="Plex", at=began, db=db)
        chronicle.record("recovery", level="ok", integration_id=plex, name="Plex", at=began + timedelta(minutes=30), db=db)
    page = _page(client, f"integration:{plex}")
    assert page["state"] == "past" and page["cause"]["name"] == "docker-live"


# -- what it can do about it -------------------------------------------------------------------------


def test_the_buttons_are_those_of_the_card_that_lists_its_container(client: TestClient) -> None:
    _pve, engine, plex = _chain(client)
    containers = _card(client, "docker.containers", engine)
    restart = {"id": "restart", "label": "Restart", "icon": "rotate-cw", "confirm": True, "params": {"id": "c1"}}
    live.set(containers["id"], WidgetData(status="ok", items=[
        {"title": "nginx", "actions": [{**restart, "params": {"id": "c0"}}]},
        {"title": "plex", "actions": [restart, {"id": "stop", "label": "Stop", "danger": True, "params": {"id": "c1"}}]},
    ]))
    buttons = _page(client, f"integration:{plex}")["buttons"]
    assert [(one["widget_id"], one["id"], one["params"], one["danger"]) for one in buttons] == [
        (containers["id"], "restart", {"id": "c1"}, False), (containers["id"], "stop", {"id": "c1"}, True)]
    alone = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    assert _page(client, f"integration:{alone}")["buttons"] == []


def test_the_log_is_read_on_asking_with_secrets_masked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.docker import DockerAdapter

    _pve, engine, plex = _chain(client)
    asked: list[tuple[str, int]] = []

    async def log(_self: object, _config: dict, _ctx: object, name: str, lines: int) -> list[str]:
        asked.append((name, lines))
        return ["started", "", "DB_PASSWORD=hunter2 token=abc123def456", "Authorization: Bearer abcdefghijklmnop"]

    monkeypatch.setattr(DockerAdapter, "container_log", log)
    page = _page(client, f"integration:{plex}")
    assert page["log"] == {"available": True, "container": "plex", "engine": "docker-live", "ref": f"container:{engine}:plex"}
    assert asked == [], "opening the page reads no log"
    read = client.post("/api/v1/diagnosis/log", json={"ref": f"integration:{plex}"}, headers=CSRF)
    assert read.status_code == 200, read.text
    assert asked == [("plex", 100)]
    text = json.dumps(read.json()["lines"])
    assert "hunter2" not in text and "abc123def456" not in text and "abcdefghijklmnop" not in text
    assert read.json()["lines"][0] == "started" and len(read.json()["lines"]) == 3


def test_no_log_without_a_container_or_in_the_demo(client: TestClient) -> None:
    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    assert _page(client, f"integration:{radarr}")["log"] == {"available": False, "why": "no_container"}
    refused = client.post("/api/v1/diagnosis/log", json={"ref": f"integration:{radarr}"}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "no_container"

    engine = _connection(client, "docker", "docker-live", "tcp://10.0.0.65:2375")
    plex = _connection(client, "plex", "Plex", "http://10.0.0.65:32400")
    _things(engine, _container("plex", 32400))
    _match({engine: ["10.0.0.65"]})
    with db_session() as db:
        from app.models import Integration

        db.get(Integration, engine).demo = True
    assert _page(client, f"integration:{plex}")["log"]["why"] == "demo"


# -- the runbook ----------------------------------------------------------------------------------------


def test_a_runbook_is_kept_shown_and_removed(client: TestClient) -> None:
    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    ref = f"integration:{radarr}"
    put = client.put("/api/v1/diagnosis/runbook", json={"ref": ref, "text": "1. Check the disk\n", "link": "https://notes.example.com/radarr"}, headers=CSRF)
    assert put.status_code == 200, put.text
    assert put.json()["text"] == "1. Check the disk" and put.json()["by"] == "admin"
    assert _page(client, ref)["runbook"]["link"] == "https://notes.example.com/radarr"
    bad = client.put("/api/v1/diagnosis/runbook", json={"ref": ref, "text": "x", "link": "javascript:alert(1)"}, headers=CSRF)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_link"
    gone = client.put("/api/v1/diagnosis/runbook", json={"ref": ref, "text": " ", "link": ""}, headers=CSRF)
    assert gone.json()["text"] == ""
    with db_session() as db:
        assert db.scalar(select(Runbook)) is None
    nowhere = client.put("/api/v1/diagnosis/runbook", json={"ref": "integration:999", "text": "x"}, headers=CSRF)
    assert nowhere.status_code == 404


# -- who and what --------------------------------------------------------------------------------------


def test_an_unknown_reference_is_not_found(client: TestClient) -> None:
    setup_admin(client)
    for ref in ("integration:999", "tile:999", "container:1:nothing", "guest:x:1", "plex"):
        assert client.get("/api/v1/diagnosis", params={"ref": ref}).status_code == 404, ref


def test_members_see_no_diagnosis(client: TestClient) -> None:
    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    create_user(client, "member")
    login(client, "member", "another-long-password")
    ref = f"integration:{radarr}"
    assert client.get("/api/v1/diagnosis", params={"ref": ref}).status_code == 403
    assert client.post("/api/v1/diagnosis/log", json={"ref": ref}, headers=CSRF).status_code == 403
    assert client.put("/api/v1/diagnosis/runbook", json={"ref": ref, "text": "x"}, headers=CSRF).status_code == 403


def test_a_chronicle_line_says_whom_why_asks_about(client: TestClient) -> None:
    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    card = _card(client, "radarr.queue", radarr)
    tile = _card(client, "core.app", title="Wiki")
    clock = _card(client, "core.clock", title="Clock")
    chronicle.record("outage", level="bad", widget_id=card["id"], integration_id=radarr, name="Radarr")
    chronicle.record("outage", level="bad", widget_id=tile["id"], name="Wiki")
    chronicle.record("card", level="bad", widget_id=clock["id"], name="Clock", before="ok", after="bad")
    chronicle.record("container_restarted", integration_id=radarr, name="nginx")
    chronicle.record("connection_added", integration_id=radarr, name="Radarr")
    lines = {line["kind"] + line["name"]: line.get("subject") for line in client.get("/api/v1/chronicle?days=1&group=all").json()["events"]
             if line["kind"] not in ("card_added", "signed_in")}
    assert lines == {"outageRadarr": f"integration:{radarr}", "outageWiki": f"tile:{tile['id']}",
                     "container_restartednginx": f"container:{radarr}:nginx", "connection_addedRadarr": None,
                     "cardClock": None}


async def test_an_attention_row_says_whom_why_asks_about(client: TestClient) -> None:
    import httpx

    from app.adapters import get_adapter
    from app.adapters.base import Context

    setup_admin(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    card = _card(client, "radarr.queue", radarr)
    tile = _card(client, "core.app", title="Wiki")
    calendar = _card(client, "core.clock", title="Upcoming")
    attention = _card(client, "core.problems")
    live.set(card["id"], WidgetData(status="bad"))
    live.set(tile["id"], WidgetData(status="warn"))
    live.set(calendar["id"], WidgetData(status="unknown", error="No sources are chosen."))
    ctx = Context(httpx.AsyncClient(), widget_id=attention["id"], cache={})
    read = await get_adapter("core").fetch("problems", {}, {"updates": False, "bell": False}, ctx)
    assert {row["title"]: row.get("subject") for row in read.items} == {card["title"] or "radarr.queue": f"integration:{radarr}", "Wiki": f"tile:{tile['id']}",
                                                                       "Upcoming": None}, "a card of nexdeck's own has no service to look into"


# -- the assistant -------------------------------------------------------------------------------------


async def test_the_assistant_reads_the_page(client: TestClient) -> None:
    _pve, _engine, plex, engine_card, plex_card = _plex_down(client)
    live.set(engine_card["id"], WidgetData(status="unknown", error="Connection refused", items=[
        {"title": "plex", "actions": [{"id": "restart", "label": "Restart", "params": {"id": "c1"}}]}]))
    with db_session() as db:
        db.add(Runbook(ref=f"integration:{plex}", text="Restart the NAS last."))
    with db_session() as db:
        from app.models import User

        bench = tools.Bench(db=db, user=db.scalar(select(User)), grants=[])
        content, failed = await tools.run(bench, "diagnosis", {"card_id": plex_card["id"]})
        assert not failed
        read = json.loads(content)
        assert read["subject"]["name"] == "Plex" and read["cause"]["name"] == "docker-live"
        assert read["runbook"]["text"] == "Restart the NAS last."
        assert read["buttons"] == [{"card": engine_card["title"] or "docker.containers", "item": "plex", "label": "Restart", "danger": False}], \
            "what the button is, not how to press it: the model proposes buttons through card_details"
        assert f"card:{plex_card['id']}" in bench.citations
        missing, _ = await tools.run(bench, "diagnosis", {"ref": "integration:999"})
        assert "error" in json.loads(missing)


def test_a_question_from_the_page_tells_the_model_where_it_was_asked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from .test_assistant import Script, _switch_on

    setup_admin(client)
    _switch_on(client)
    radarr = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    script = Script(providers.Turn(text="It is fine."))
    monkeypatch.setattr(providers, "turn", script)
    reply = client.post("/api/v1/assistant/chat", json={"text": "Explain it", "about": f"integration:{radarr}"}, headers=CSRF)
    assert reply.status_code == 200, reply.text
    sent = script.seen[0][-1]["text"]
    assert sent.startswith("Explain it") and f"diagnosis page of Radarr, ref integration:{radarr}" in sent
    shown = client.get(f"/api/v1/assistant/conversations/{reply.json()['conversation_id']}").json()["turns"][0]
    assert shown == {"me": True, "text": "Explain it"}, "the chat shows the question as it was typed"
    with db_session() as db:
        assert chat._from_page(db, "integration:999") == "", "a reference to nothing adds nothing"
