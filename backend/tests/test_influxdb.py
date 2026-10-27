"""InfluxDB, against the answers of a live InfluxDB 2.7.12 and InfluxDB 3 Core 3.12.1 (27.10.2026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.influxdb import InfluxdbAdapter, first_csv_number, first_sql_number

FIXTURES = Path(__file__).parent / "fixtures"
V2 = "http://influx2.example.com:8086"
V3 = "http://influx3.example.com:8181"
TOKEN = "made-up-token"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


HEALTH2 = fixture("influxdb2_health.json")
BUCKETS2 = fixture("influxdb2_buckets.json")
PING3 = fixture("influxdb3_ping.json")
DATABASES3 = fixture("influxdb3_databases.json")
SQL3 = fixture("influxdb3_sql.json")
# ⚠️ Flux's CSV has CRLF line ends and a blank line after every table; git keeps the file with LF.
CSV2 = (FIXTURES / "influxdb2_query.csv").read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
CONFIG2 = {"url": V2, "token": TOKEN, "org": "homelab"}
CONFIG3 = {"url": V3, "token": TOKEN}
QUERY = 'from(bucket: "telemetry") |> range(start: -2h) |> last()'


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def version2() -> None:
    respx.get(f"{V2}/ping").mock(return_value=httpx.Response(204, headers={"X-Influxdb-Version": "v2.7.12", "X-Influxdb-Build": "OSS"}))


def version3() -> None:
    respx.get(f"{V3}/ping").mock(return_value=httpx.Response(200, json=PING3))


@respx.mock
async def test_version_2_status_names_buckets_and_version(ctx: Context) -> None:
    version2()
    respx.get(f"{V2}/health").mock(return_value=httpx.Response(200, json=HEALTH2))
    buckets = respx.get(f"{V2}/api/v2/buckets").mock(return_value=httpx.Response(200, json=BUCKETS2))
    data = await get_adapter("influxdb").fetch("status", CONFIG2, {}, ctx)
    # The two system buckets are not counted: they are InfluxDB's, not the homelab's.
    assert data.primary == {"label": "Buckets", "value": 1, "unit": ""} and data.status == "ok"
    assert data.secondary == [{"label": "State", "value": "Ready"}, {"label": "Version", "value": "2.7.12"}]
    assert data.metrics == {"buckets": 1.0}
    assert buckets.calls.last.request.headers["Authorization"] == f"Token {TOKEN}"


@respx.mock
async def test_version_2_that_is_not_ready_is_red_with_its_words(ctx: Context) -> None:
    version2()
    respx.get(f"{V2}/health").mock(return_value=httpx.Response(503, json={"name": "influxdb", "message": "compactions are starting", "status": "fail", "checks": []}))
    respx.get(f"{V2}/api/v2/buckets").mock(return_value=httpx.Response(200, json=BUCKETS2))
    data = await get_adapter("influxdb").fetch("status", CONFIG2, {}, ctx)
    assert data.status == "bad" and data.secondary[0] == {"label": "State", "value": "compactions are starting"}


@respx.mock
async def test_version_2_buckets_with_what_they_keep(ctx: Context) -> None:
    version2()
    respx.get(f"{V2}/api/v2/buckets").mock(return_value=httpx.Response(200, json=BUCKETS2))
    adapter = get_adapter("influxdb")
    data = await adapter.fetch("buckets", CONFIG2, {}, ctx)
    assert [(row["title"], row["subtitle"]) for row in data.items] == [("telemetry", "Keeps forever")]
    everything = await adapter.fetch("buckets", CONFIG2, {"system": True}, ctx)
    assert [(row["title"], row["subtitle"]) for row in everything.items] == [
        ("telemetry", "Keeps forever"), ("_monitoring", "System · Keeps 7d"), ("_tasks", "System · Keeps 3d")]


@respx.mock
async def test_version_2_query_reads_the_value_column_of_the_csv(ctx: Context) -> None:
    version2()
    query = respx.post(f"{V2}/api/v2/query").mock(return_value=httpx.Response(200, text=CSV2, headers={"content-type": "text/csv; charset=utf-8"}))
    data = await get_adapter("influxdb").fetch("query", CONFIG2, {"query": QUERY, "unit": "%", "label": "CPU", "decimals": 0, "warn_above": 30}, ctx)
    assert data.primary == {"label": "CPU", "value": 38, "unit": "%"} and data.metrics == {"value": 38.5} and data.status == "warn"
    sent = query.calls.last.request
    assert sent.url.params["org"] == "homelab" and sent.content == QUERY.encode()
    assert sent.headers["Content-Type"] == "application/vnd.flux" and sent.headers["Accept"] == "application/csv"
    assert sent.headers["Authorization"] == f"Token {TOKEN}"


@respx.mock
async def test_version_2_without_an_org_takes_the_first_the_token_sees(ctx: Context) -> None:
    version2()
    orgs = respx.get(f"{V2}/api/v2/orgs").mock(return_value=httpx.Response(200, json={"orgs": [{"id": "e23f1b66fd4335aa", "name": "homelab"}]}))
    query = respx.post(f"{V2}/api/v2/query").mock(return_value=httpx.Response(200, text=CSV2))
    await get_adapter("influxdb").fetch("query", {"url": V2, "token": TOKEN}, {"query": QUERY}, ctx)
    assert query.calls.last.request.url.params["org"] == "homelab" and orgs.call_count == 1
    orgs.mock(return_value=httpx.Response(200, json={"orgs": []}))
    with pytest.raises(AdapterError) as none:
        await get_adapter("influxdb").fetch("query", {"url": V2, "token": TOKEN}, {"query": QUERY}, Context(httpx.AsyncClient(), integration_id=2, widget_id=1, cache={}))
    assert none.value.code == "missing_org"


@respx.mock
async def test_version_2_query_that_does_not_compile_says_what_influxdb_said(ctx: Context) -> None:
    version2()
    respx.post(f"{V2}/api/v2/query").mock(return_value=httpx.Response(400, json={"code": "invalid", "message": "compilation failed: error @1:1-1:13: expected RPAREN, got EOF\n\nerror @1:6-1:12: missing property value"}))
    with pytest.raises(AdapterError) as bad:
        await get_adapter("influxdb").fetch("query", CONFIG2, {"query": "from(bucket:"}, ctx)
    assert bad.value.code == "query_error" and bad.value.message.startswith("InfluxDB rejected the query: compilation failed: error @1:1-1:13: expected RPAREN, got EOF")
    assert "\n" not in bad.value.message


@respx.mock
async def test_a_query_that_found_nothing_is_not_a_zero(ctx: Context) -> None:
    """⚠️ Measured: an empty body, status 200."""
    version2()
    respx.post(f"{V2}/api/v2/query").mock(return_value=httpx.Response(200, text=""))
    with pytest.raises(AdapterError) as empty:
        await get_adapter("influxdb").fetch("query", CONFIG2, {"query": QUERY}, ctx)
    assert empty.value.code == "empty_result"
    with pytest.raises(AdapterError) as unset:
        await get_adapter("influxdb").fetch("query", CONFIG2, {}, ctx)
    assert unset.value.code == "missing_query"


def test_the_csv_number() -> None:
    assert first_csv_number(CSV2) == 38.5
    two_tables = ",result,table,_time,_value,host\r\n,_result,0,t,1.5,a\r\n\r\n,result,table,_time,_value,host\r\n,_result,1,t,9,b\r\n\r\n"
    assert first_csv_number(two_tables) == 1.5
    # A query that renamed the column (map, a pivot): the last number of the row.
    assert first_csv_number(",result,table,usage\r\n,_result,0,12.25\r\n") == 12.25
    assert first_csv_number("#datatype,string,long\r\n,result,table,_value\r\n,_result,0,7\r\n") == 7.0
    assert first_csv_number(",result,table,_value\r\n,_result,0,not a number\r\n") is None
    assert first_csv_number("") is None


def test_the_sql_number() -> None:
    assert first_sql_number(SQL3) == 38.5
    assert first_sql_number([{"time": "2026-10-27T17:59:04", "mean": 31.0}]) == 31.0
    assert first_sql_number([{"name": "nas", "count": "4"}]) == 4.0
    assert first_sql_number([{"ok": True}]) is None
    assert first_sql_number([]) is None and first_sql_number({"a": 1}) is None


@respx.mock
async def test_version_3_is_found_by_its_ping_and_speaks_bearer(ctx: Context) -> None:
    ping = respx.get(f"{V3}/ping").mock(return_value=httpx.Response(200, json=PING3))
    respx.get(f"{V3}/health").mock(return_value=httpx.Response(200, text="OK"))
    databases = respx.get(f"{V3}/api/v3/configure/database").mock(return_value=httpx.Response(200, json=DATABASES3))
    data = await get_adapter("influxdb").fetch("status", CONFIG3, {}, ctx)
    assert data.primary == {"label": "Databases", "value": 1, "unit": ""} and data.status == "ok"
    assert data.secondary[1] == {"label": "Version", "value": "3.12.1"}
    assert ping.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert databases.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}" and databases.calls.last.request.url.params["format"] == "json"
    listed = await get_adapter("influxdb").fetch("buckets", CONFIG3, {"system": True}, ctx)
    assert [(row["title"], row["subtitle"]) for row in listed.items] == [("telemetry", ""), ("_internal", "System")]
    assert ping.call_count == 1, "the version is asked once and kept"


@respx.mock
async def test_version_3_query_runs_sql_in_the_named_database(ctx: Context) -> None:
    version3()
    query = respx.post(f"{V3}/api/v3/query_sql").mock(return_value=httpx.Response(200, json=SQL3))
    sql = "SELECT usage FROM cpu ORDER BY time DESC LIMIT 1"
    data = await get_adapter("influxdb").fetch("query", CONFIG3, {"query": sql, "database": "telemetry", "decimals": 1}, ctx)
    assert data.primary["value"] == 38.5 and data.metrics == {"value": 38.5}
    assert json.loads(query.calls.last.request.content) == {"db": "telemetry", "q": sql, "format": "json"}
    with pytest.raises(AdapterError) as nodb:
        await get_adapter("influxdb").fetch("query", CONFIG3, {"query": sql}, ctx)
    assert nodb.value.code == "missing_database"
    # ⚠️ Measured: an unknown column is 500 with plain words, an unknown database 404 with JSON.
    query.mock(return_value=httpx.Response(500, text="Schema error: No field named nope. Valid fields are cpu.host, cpu.time, cpu.usage."))
    with pytest.raises(AdapterError) as column:
        await get_adapter("influxdb").fetch("query", CONFIG3, {"query": "SELECT nope FROM cpu", "database": "telemetry"}, ctx)
    assert column.value.message.startswith("InfluxDB rejected the query: Schema error: No field named nope.")
    query.mock(return_value=httpx.Response(404, json={"error": "query error: database not found: nodb"}))
    with pytest.raises(AdapterError) as gone:
        await get_adapter("influxdb").fetch("query", CONFIG3, {"query": sql, "database": "nodb"}, ctx)
    assert "database not found: nodb" in gone.value.message and gone.value.code == "query_error" and "Database field" in gone.value.hint


@respx.mock
async def test_the_connection_test_names_version_and_count(ctx: Context) -> None:
    version2()
    respx.get(f"{V2}/api/v2/buckets").mock(return_value=httpx.Response(200, json=BUCKETS2))
    adapter = get_adapter("influxdb")
    assert await adapter.test(CONFIG2, ctx) == "InfluxDB 2.7.12 answers, 1 buckets."
    assert await adapter.running_version(CONFIG2, ctx) == "2.7.12"
    version3()
    respx.get(f"{V3}/api/v3/configure/database").mock(return_value=httpx.Response(200, json=DATABASES3))
    assert await adapter.test(CONFIG3, Context(httpx.AsyncClient(), integration_id=3, widget_id=1, cache={})) == "InfluxDB 3.12.1 answers, 1 databases."


@respx.mock
async def test_a_rejected_token(ctx: Context) -> None:
    """⚠️ Measured: 3.x refuses even /ping without a token; 2.x answers /ping and refuses the buckets."""
    respx.get(f"{V3}/ping").mock(return_value=httpx.Response(401, json={"error": "the request was not authenticated"}))
    with pytest.raises(AuthFailed):
        await get_adapter("influxdb").fetch("status", CONFIG3, {}, ctx)
    version2()
    respx.get(f"{V2}/api/v2/buckets").mock(return_value=httpx.Response(401, json={"code": "unauthorized", "message": "unauthorized access"}))
    with pytest.raises(AuthFailed):
        await get_adapter("influxdb").fetch("buckets", CONFIG2, {}, Context(httpx.AsyncClient(), integration_id=2, widget_id=1, cache={}))


@respx.mock
async def test_unreachable_and_not_influxdb(ctx: Context) -> None:
    respx.get(f"{V2}/ping").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(Unreachable):
        await get_adapter("influxdb").fetch("status", CONFIG2, {}, ctx)
    respx.get(f"{V3}/ping").mock(return_value=httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(AdapterError) as other:
        await get_adapter("influxdb").fetch("status", CONFIG3, {}, Context(httpx.AsyncClient(), integration_id=2, widget_id=1, cache={}))
    assert other.value.code == "not_influxdb" and "8181" in other.value.hint


def test_the_token_is_a_secret_and_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("influxdb")
    assert {field.name for field in adapter.fields if field.secret} == {"token"} and adapter.beta is True
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        assert adapter.demo(widget.kind, options, 0).error is None, widget.kind
    values = {adapter.demo("query", {}, tick).primary["value"] for tick in range(0, 300, 10)}
    assert len(values) > 1
    assert isinstance(adapter, InfluxdbAdapter)
