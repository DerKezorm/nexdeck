"""A card may only be asked to do what it last offered to do.

⚠️ Until 07.09.2026 the name of an action was checked against the adapter's own
list and its parameters against nothing at all, and several adapters put a
parameter straight into a path.

Two ways out of that, both found on 06.09.2026 and both reachable with a kiosk
token, which needs no account at all:

* ``POST /widgets/{id}/actions/start`` with ``{"id": "../volumes/prune?x="}``.
  Measured with the pinned httpx 0.28.1: ``/containers/../volumes/prune?x=/start``
  becomes ``/volumes/prune``, and the compose file in the README mounts the
  Docker socket. The same shape sits in ``portainer.py`` and ``proxmox.py``.
* ``POST /widgets/{id}/actions/lock.unlock`` on any Home Assistant card. No
  card ever offered it; the adapter simply split the name at the dot and called
  the service, with a token that may do anything in the house.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import CSRF, setup_admin


def _board(client: TestClient, name: str = "Wall") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _docker_card(client: TestClient) -> dict:
    """A container card on a demo connection, so nothing reaches a real engine."""
    integration = client.post(
        "/api/v1/integrations", json={"kind": "docker", "name": "Host", "config": {}, "demo": True}, headers=CSRF,
    ).json()
    board = _board(client)
    widget = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "docker.containers", "integration_id": integration["id"]}, headers=CSRF,
    )
    assert widget.status_code == 201, widget.text
    return widget.json()["widget"]


def _offered_action(client: TestClient, widget_id: int) -> tuple[str, dict]:
    """Refresh the card and take the first action it puts on a row."""
    refreshed = client.post(f"/api/v1/widgets/{widget_id}/refresh", headers=CSRF)
    assert refreshed.status_code == 200, refreshed.text
    for item in refreshed.json().get("items") or []:
        for action in item.get("actions") or []:
            return str(action["id"]), dict(action.get("params") or {})
    raise AssertionError("the demo card offered no action at all, so this test proves nothing")


def test_an_action_the_card_offered_still_runs(client: TestClient) -> None:
    setup_admin(client)
    widget = _docker_card(client)
    action_id, params = _offered_action(client, widget["id"])
    answer = client.post(f"/api/v1/widgets/{widget['id']}/actions/{action_id}", json={"params": params}, headers=CSRF)
    assert answer.status_code == 200, answer.text


def test_a_row_button_given_as_an_action_object_runs_too(client: TestClient) -> None:
    """⚠️ Found 11.09.2026 while pressing Kimai's new stop button in a browser.

    The check above looked for row buttons as dictionaries, and Docker hands
    them over like that. n8n and Synology put ``Action`` objects on
    their rows instead: drawn on the card like any other button, and refused
    with "This card is not offering any action right now." when pressed.
    """
    setup_admin(client)
    integration = client.post(
        "/api/v1/integrations", json={"kind": "n8n", "name": "Flows", "config": {}, "demo": True}, headers=CSRF,
    ).json()
    board = _board(client, "Automation")
    widget = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "n8n.workflows", "integration_id": integration["id"]}, headers=CSRF,
    ).json()["widget"]
    action_id, params = _offered_action(client, widget["id"])
    answer = client.post(f"/api/v1/widgets/{widget['id']}/actions/{action_id}", json={"params": params}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    other = client.post(f"/api/v1/widgets/{widget['id']}/actions/{action_id}", json={"params": {"id": "a workflow never shown"}}, headers=CSRF)
    assert other.status_code == 400 and other.json()["detail"]["code"] == "no_such_action"


def test_a_container_id_cannot_walk_out_of_its_path(client: TestClient) -> None:
    setup_admin(client)
    widget = _docker_card(client)
    action_id, _ = _offered_action(client, widget["id"])
    answer = client.post(
        f"/api/v1/widgets/{widget['id']}/actions/{action_id}",
        json={"params": {"id": "../volumes/prune?x="}}, headers=CSRF,
    )
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == "no_such_action"


def test_an_action_that_was_never_offered_is_refused(client: TestClient) -> None:
    setup_admin(client)
    widget = _docker_card(client)
    _offered_action(client, widget["id"])
    for name in ("lock.unlock", "homeassistant.restart", "script.turn_on"):
        answer = client.post(f"/api/v1/widgets/{widget['id']}/actions/{name}", json={"params": {}}, headers=CSRF)
        assert answer.status_code == 400, f"{name}: {answer.text}"
        assert answer.json()["detail"]["code"] == "no_such_action"


def test_a_card_that_has_never_been_read_offers_nothing(client: TestClient) -> None:
    """No live data, no actions. A card is not a way in before it has run once."""
    setup_admin(client)
    widget = _docker_card(client)
    answer = client.post(f"/api/v1/widgets/{widget['id']}/actions/start", json={"params": {"id": "abc"}}, headers=CSRF)
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == "no_such_action"


def test_the_adapters_refuse_a_name_that_is_not_a_single_path_segment() -> None:
    """The second lock, for the case the first one cannot see.

    The names of containers and guests come from the foreign service, not from
    us. A container called ``..`` would be offered by the card like any other
    and would pass the check above, so the adapters look at what they are about
    to put in an address.
    """
    import asyncio

    from app.adapters.base import AdapterError, Context
    from app.adapters.docker import DockerAdapter
    from app.adapters.portainer import PortainerAdapter
    from app.adapters.proxmox import ProxmoxAdapter

    bad = ["../volumes/prune?x=", "../../../../stacks/3", "a/b", "?x=1", "", "..", "-starts-with-a-dash"]
    checked = 0
    for value in bad:
        for adapter, action_id, params in (
            (DockerAdapter(), "start", {"id": value}),
            (PortainerAdapter(), "start", {"id": value}),
            (ProxmoxAdapter(), "start", {"node": value, "type": "qemu", "vmid": "100"}),
            (ProxmoxAdapter(), "start", {"node": "pve", "type": "qemu", "vmid": value}),
        ):
            checked += 1
            try:
                asyncio.run(adapter.action("containers", action_id, params, {"url": "http://x"}, {}, Context(None)))
            except AdapterError as refused:
                assert refused.code in ("bad_param", "missing_param"), f"{adapter.kind} {value!r}: {refused.code}"
            except Exception as other:  # noqa: BLE001
                raise AssertionError(f"{adapter.kind} let {value!r} through as far as {other.__class__.__name__}") from other
            else:
                raise AssertionError(f"{adapter.kind} accepted {value!r}")
    assert checked == len(bad) * 4, "not every adapter was asked, so this proves less than it says"
