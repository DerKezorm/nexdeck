"""Grafana, Coolify, Syncthing, Proxmox Backup Server and evcc.

Each parser against a recorded answer. Four shapes bite here: Grafana hides
its rules two levels deep, Coolify writes state and health into one string,
PBS leaves out the numbers a token may not see, and evcc used to wrap its
whole state in a "result" object.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- grafana -------------------------------------------------------------------

# The pending rule comes first, as Grafana hands it out: the card has to sort.
# "file" is the folder's title, "folderUid" the random string beside it.
RULES = {"data": {"groups": [
    {"name": "Backups", "file": "Infrastructure", "folderUid": "cfxd7vj7k5m9sd", "rules": [
        {"name": "Backup older than a day", "state": "pending", "type": "alerting"},
        {"name": "Restore test", "state": "inactive", "type": "alerting"},
    ]},
    {"name": "Storage", "file": "Infrastructure", "folderUid": "cfxd7vj7k5m9sd", "rules": [
        {"name": "Disk almost full", "state": "firing", "type": "alerting"},
        {"name": "Bytes written", "state": "inactive", "type": "recording"},
    ]},
]}}


@respx.mock
async def test_grafana_digs_the_rules_out_of_the_groups(ctx: Context) -> None:
    config = {"url": "http://grafana:3000", "token": "sat"}
    respx.get("http://grafana:3000/api/prometheus/grafana/api/v1/rules").mock(return_value=httpx.Response(200, json=RULES))
    data = await get_adapter("grafana").fetch("alerts", config, {}, ctx)
    assert [item["title"] for item in data.items] == ["Disk almost full", "Backup older than a day"]
    # The folder is named, not identified: the uid must not reach the card.
    assert data.items[0]["subtitle"] == "Infrastructure / Storage"
    assert "cfxd7vj7k5m9sd" not in str(data.items)
    assert data.status == "bad"
    assert data.metrics == {"firing": 1.0, "pending": 1.0}
    assert respx.calls.last.request.headers["Authorization"] == "Bearer sat"


@respx.mock
async def test_grafana_leaves_recording_rules_out(ctx: Context) -> None:
    """A recording rule has a state too, and it is not an alert."""
    config = {"url": "http://grafana:3000", "token": "sat"}
    respx.get("http://grafana:3000/api/prometheus/grafana/api/v1/rules").mock(return_value=httpx.Response(200, json=RULES))
    respx.get("http://grafana:3000/api/health").mock(return_value=httpx.Response(200, json={"database": "ok", "version": "11.6.0"}))
    respx.get("http://grafana:3000/api/search").mock(return_value=httpx.Response(200, json=[{"uid": "a"}, {"uid": "b"}]))
    data = await get_adapter("grafana").fetch("status", config, {}, ctx)
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {
        "Pending": 1, "Rules": 3, "Dashboards": 2, "Version": "11.6.0",
    }
    assert dict(respx.calls.last.request.url.params)["type"] == "dash-db"


@respx.mock
async def test_grafana_can_be_asked_for_the_firing_ones_only(ctx: Context) -> None:
    config = {"url": "http://grafana:3000", "token": "sat"}
    respx.get("http://grafana:3000/api/prometheus/grafana/api/v1/rules").mock(return_value=httpx.Response(200, json=RULES))
    data = await get_adapter("grafana").fetch("alerts", config, {"only_firing": True}, ctx)
    assert [item["title"] for item in data.items] == ["Disk almost full"]
    # The counts stay whole even when the list is filtered.
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Firing": 1, "Pending": 1}


# -- coolify -------------------------------------------------------------------


@respx.mock
async def test_coolify_splits_state_and_health_out_of_one_string(ctx: Context) -> None:
    """Coolify writes "running:unhealthy" into one field. Read as a whole it
    is neither good nor bad; read in halves it is a warning."""
    config = {"url": "https://coolify.example.com", "token": "tok"}
    respx.get("https://coolify.example.com/api/v1/applications").mock(return_value=httpx.Response(200, json=[
        {"name": "shop", "fqdn": "https://shop.example.com", "status": "running:healthy"},
        {"name": "worker", "fqdn": "", "status": "running:unhealthy"},
        {"name": "staging", "fqdn": "https://staging.example.com", "status": "exited:unhealthy"},
        {"name": "odd", "fqdn": "", "status": "something-new"},
    ]))
    data = await get_adapter("coolify").fetch("applications", config, {}, ctx)
    states = {item["title"]: item["status"] for item in data.items}
    assert states == {"shop": "ok", "worker": "warn", "staging": "bad", "odd": "unknown"}
    assert data.items[0]["title"] == "staging"
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Running": 1, "Applications": 4}
    assert respx.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_coolify_reads_a_version_that_is_not_json(ctx: Context) -> None:
    config = {"url": "https://coolify.example.com", "token": "tok"}
    respx.get("https://coolify.example.com/api/v1/applications").mock(return_value=httpx.Response(200, json=[
        {"name": "shop", "status": "running:healthy"},
    ]))
    respx.get("https://coolify.example.com/api/v1/servers").mock(return_value=httpx.Response(200, json=[
        {"name": "hetzner", "settings": {"is_reachable": True}},
        {"name": "attic", "settings": {"is_reachable": False}},
    ]))
    respx.get("https://coolify.example.com/api/v1/version").mock(return_value=httpx.Response(200, text="v4.0.0"))
    data = await get_adapter("coolify").fetch("status", config, {}, ctx)
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Version"] == "v4.0.0" and values["Servers"] == "1/2"
    assert data.primary == {"label": "Running", "value": 1}


@respx.mock
async def test_coolify_shows_what_is_deploying(ctx: Context) -> None:
    config = {"url": "https://coolify.example.com", "token": "tok"}
    respx.get("https://coolify.example.com/api/v1/deployments").mock(return_value=httpx.Response(200, json=[
        {"application_name": "api", "commit_message": "Bump the parser", "status": "in_progress"},
        {"application_name": "shop", "commit_message": "Add the banner", "status": "queued"},
    ]))
    data = await get_adapter("coolify").fetch("deployments", config, {}, ctx)
    assert [(item["title"], item["status"]) for item in data.items] == [("api", "warn"), ("shop", "unknown")]
    assert data.metrics == {"deployments": 2.0}


# -- syncthing -----------------------------------------------------------------


@respx.mock
async def test_syncthing_does_not_count_itself_as_a_connected_device(ctx: Context) -> None:
    """The connection list holds the own device as well. Counted along, a
    lone Syncthing would report one connection it does not have."""
    config = {"url": "http://syncthing:8384", "api_key": "key"}
    respx.get("http://syncthing:8384/rest/config/folders").mock(return_value=httpx.Response(200, json=[{"id": "abc", "label": "Documents"}]))
    respx.get("http://syncthing:8384/rest/system/status").mock(return_value=httpx.Response(200, json={"myID": "SELF-ID", "uptime": 1058400}))
    respx.get("http://syncthing:8384/rest/system/connections").mock(return_value=httpx.Response(200, json={"connections": {
        "SELF-ID": {"connected": True}, "NAS-ID": {"connected": True}, "PHONE-ID": {"connected": False},
    }}))
    respx.get("http://syncthing:8384/rest/system/version").mock(return_value=httpx.Response(200, json={"version": "v2.1.0", "os": "linux"}))
    data = await get_adapter("syncthing").fetch("status", config, {}, ctx)
    assert data.primary == {"label": "Connected", "value": 1}
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Devices"] == 2 and values["Uptime"] == "12d 6h"
    assert data.status == "warn"


@respx.mock
async def test_syncthing_reads_pull_errors_and_an_unknown_state(ctx: Context) -> None:
    config = {"url": "http://syncthing:8384", "api_key": "key"}
    respx.get("http://syncthing:8384/rest/config/folders").mock(return_value=httpx.Response(200, json=[
        {"id": "docs", "label": "Documents"}, {"id": "pics", "label": "Photos"},
    ]))

    def answer(request: httpx.Request) -> httpx.Response:
        folder = dict(request.url.params)["folder"]
        if folder == "docs":
            return httpx.Response(200, json={"state": "idle", "globalBytes": 1000, "localBytes": 1000, "pullErrors": 0})
        return httpx.Response(200, json={"state": "sync-waiting", "globalBytes": 1000, "localBytes": 250, "pullErrors": 3})

    respx.get("http://syncthing:8384/rest/db/status").mock(side_effect=answer)
    data = await get_adapter("syncthing").fetch("folders", config, {}, ctx)
    assert [item["status"] for item in data.items] == ["ok", "bad"]
    # A state the documentation does not name is passed on, not swallowed.
    assert data.items[1]["subtitle"] == "sync-waiting"
    assert data.items[1]["progress"] == 25.0
    assert data.metrics == {"folders": 2.0, "errors": 1.0}
    assert respx.calls.last.request.headers["X-API-Key"] == "key"


# -- proxmox backup server -----------------------------------------------------


@respx.mock
async def test_pbs_signs_with_a_colon_not_an_equals_sign(ctx: Context) -> None:
    """Proxmox VE wants PVEAPIToken=id=secret, PBS wants PBSAPIToken=id:secret.
    The wrong one gives a 401 that explains nothing."""
    config = {"url": "https://pbs.example.com:8007", "token_id": "monitor@pbs!nexdeck", "secret": "s3cret"}
    respx.get("https://pbs.example.com:8007/api2/json/status/datastore-usage").mock(return_value=httpx.Response(200, json={"data": [
        {"store": "main", "total": 24_000_000_000_000, "used": 18_000_000_000_000},
    ]}))
    await get_adapter("pbs").fetch("datastores", config, {}, ctx)
    assert respx.calls.last.request.headers["Authorization"] == "PBSAPIToken=monitor@pbs!nexdeck:s3cret"


@respx.mock
async def test_pbs_keeps_a_datastore_it_may_not_measure(ctx: Context) -> None:
    """Without Datastore.Audit the name arrives and the numbers do not. That
    is a row without a bar, not a datastore that is empty."""
    config = {"url": "https://pbs.example.com:8007", "token_id": "id", "secret": "s"}
    respx.get("https://pbs.example.com:8007/api2/json/status/datastore-usage").mock(return_value=httpx.Response(200, json={"data": [
        {"store": "offsite", "mount-status": "mounted"},
        {"store": "main", "total": 24_000_000_000_000, "used": 18_000_000_000_000},
        {"store": "archive", "total": 10_000_000_000_000, "used": 9_700_000_000_000},
    ]}))
    data = await get_adapter("pbs").fetch("datastores", config, {}, ctx)
    assert [item["title"] for item in data.items] == ["archive", "main", "offsite"]
    assert data.items[0]["value"] == "97.0 %" and data.items[0]["status"] == "bad"
    assert data.items[1]["value"] == "75.0 %" and data.items[1]["status"] == "ok"
    # The store without numbers keeps its name and gets no bar.
    assert "progress" not in data.items[2]
    assert data.metrics["fullest"] == 97.0 and data.status == "bad"


@respx.mock
async def test_pbs_tells_a_finished_job_from_a_failed_one(ctx: Context) -> None:
    config = {"url": "https://pbs.example.com:8007", "token_id": "id", "secret": "s"}
    respx.get("https://pbs.example.com:8007/api2/json/nodes/localhost/tasks").mock(return_value=httpx.Response(200, json={"data": [
        {"worker_id": "vm/104", "worker_type": "backup", "status": "OK", "endtime": 1},
        {"worker_id": "vm/117", "worker_type": "backup", "status": "connection error", "endtime": 2},
        {"worker_id": "store-main", "worker_type": "verify"},
    ]}))
    data = await get_adapter("pbs").fetch("tasks", config, {}, ctx)
    assert [item["status"] for item in data.items] == ["ok", "bad", "unknown"]
    assert data.items[1]["value"] == "connection error"
    assert data.metrics == {"failed": 1.0}


@respx.mock
async def test_pbs_asks_only_for_the_failures_when_told_to(ctx: Context) -> None:
    config = {"url": "https://pbs.example.com:8007", "token_id": "id", "secret": "s"}
    respx.get("https://pbs.example.com:8007/api2/json/nodes/localhost/tasks").mock(return_value=httpx.Response(200, json={"data": []}))
    await get_adapter("pbs").fetch("tasks", config, {"only_errors": True}, ctx)
    assert dict(respx.calls.last.request.url.params)["errors"] == "1"


@respx.mock
async def test_pbs_turns_the_cpu_fraction_into_a_percentage(ctx: Context) -> None:
    """PBS reports 0.07, not 7."""
    config = {"url": "https://pbs.example.com:8007", "token_id": "id", "secret": "s", "node": "backup1"}
    respx.get("https://pbs.example.com:8007/api2/json/nodes/backup1/status").mock(return_value=httpx.Response(200, json={"data": {
        "cpu": 0.07, "uptime": 2944800,
        "memory": {"total": 16_000_000_000, "used": 8_000_000_000},
        "root": {"total": 100_000_000_000, "used": 41_000_000_000},
    }}))
    data = await get_adapter("pbs").fetch("system", config, {}, ctx)
    assert data.primary == {"label": "CPU", "value": 7.0, "unit": "%"}
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Memory"] == 50.0 and values["Root"] == 41.0 and values["Uptime"] == "34d 2h"


# -- evcc ----------------------------------------------------------------------

STATE = {
    "siteTitle": "Home", "version": "0.315.0", "homePower": 640, "pvPower": 3400,
    "grid": {"power": -1800}, "battery": {"soc": 78.5, "power": -400},
    "loadpoints": [
        {"title": "Garage", "charging": True, "connected": True, "chargePower": 7400, "chargedEnergy": 12400, "vehicleSoc": 64, "mode": "pv", "vehicleTitle": "Kombi"},
        {"title": "Carport", "charging": False, "connected": False, "chargePower": 0, "mode": "off"},
    ],
}


@respx.mock
async def test_evcc_reads_grid_and_battery_out_of_their_own_objects(ctx: Context) -> None:
    """There is no gridPower and no batterySoc at the top level; both sit one
    level down, and a reader that looks for the flat name finds zero."""
    config = {"url": "http://evcc:7070"}
    respx.get("http://evcc:7070/api/state").mock(return_value=httpx.Response(200, json=STATE))
    data = await get_adapter("evcc").fetch("energy", config, {}, ctx)
    assert data.primary == {"label": "House", "value": 0.64, "unit": "kW"}
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Solar"] == 3.4 and values["Grid"] == -1.8 and values["Battery"] == 78.5


@respx.mock
async def test_evcc_still_understands_the_older_wrapped_answer(ctx: Context) -> None:
    config = {"url": "http://evcc:7070"}
    respx.get("http://evcc:7070/api/state").mock(return_value=httpx.Response(200, json={"result": STATE}))
    data = await get_adapter("evcc").fetch("energy", config, {}, ctx)
    assert data.primary == {"label": "House", "value": 0.64, "unit": "kW"}


@respx.mock
async def test_evcc_puts_the_car_beside_the_charging_point(ctx: Context) -> None:
    config = {"url": "http://evcc:7070"}
    respx.get("http://evcc:7070/api/state").mock(return_value=httpx.Response(200, json=STATE))
    data = await get_adapter("evcc").fetch("charging", config, {}, ctx)
    assert data.items[0]["title"] == "Garage · Kombi"
    # The mode stands alone in the subtitle so the interface can translate it.
    assert data.items[0]["subtitle"] == "Solar only"
    assert data.items[0]["value"] == "7.4 kW" and data.items[0]["progress"] == 64.0
    assert data.items[1]["title"] == "Carport" and data.items[1]["status"] == "unknown"
    assert data.metrics == {"charging": 1.0, "charge_power": 7400.0}


# -- every one of them ---------------------------------------------------------


@pytest.mark.parametrize("kind", ["grafana", "coolify", "syncthing", "pbs", "evcc"])
def test_every_platform_adapter_has_demo_data_for_every_widget(kind: str) -> None:
    adapter = get_adapter(kind)
    assert adapter.widgets, kind
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        for tick in (0, 7, 41):
            data = adapter.demo(widget.kind, options, tick)
            assert data.items or data.primary or data.secondary, f"{kind}/{widget.kind} at tick {tick} is empty"
