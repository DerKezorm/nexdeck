"""InfluxDB 2.x and 3.x: whether it is up, its buckets or databases, and one query as a number with its history.

Measured on 27.10.2026 against InfluxDB 2.7.12 (OSS) and InfluxDB 3 Core 3.12.1,
fresh containers with one bucket or database of six points each.

⚠️ The two are different servers behind one name, told apart by ``GET /ping``.
2.x answers 204 with the header ``X-Influxdb-Version: v2.7.12`` and asks for
no token there; 3.x answers a JSON ``{"product_name": "InfluxDB 3 Core",
"version": "3.12.1", ...}`` and, measured, **refuses it with 401 without a
token**, ``/health`` too (a plain ``OK`` with one). 2.x takes
``Authorization: Token <t>``, 3.x ``Authorization: Bearer <t>``.

⚠️ 2.x: ``/health`` is 200 ``{"status": "pass", "version": "v2.7.12"}``, and
503 with ``"status": "fail"`` when it is not ready. ``GET /api/v2/buckets``
lists the user buckets and the system ones (``_monitoring``, ``_tasks``) with
``retentionRules[].everySeconds``, 0 for forever; a wrong token is 401
``unauthorized access``. A query is ``POST /api/v2/query?org=<name>`` with a
Flux text as the body (``Content-Type: application/vnd.flux``) and
``Accept: application/csv``: annotated CSV with CRLF line ends, a header row
and one row per point (``_value`` is the number), an empty body for a query
that found nothing, 400 with the compiler's words for a Flux that does not
compile, and 400 "Please provide either orgID or org" without an org.

⚠️ 3.x: ``GET /api/v3/configure/database?format=json`` lists the databases
(``[{"iox::database": "telemetry"}]``, with ``_internal`` among them), a query
is ``POST /api/v3/query_sql`` with ``{"db", "q", "format": "json"}`` and
answers a list of rows. A column that does not exist is 500 with plain words
("Schema error: No field named nope"), a database that does not exist 404.

The query is the editor's text, run with the token's rights. A token that may
only read is the one to use; Flux can write with ``to()``.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from ..services.jsonpath import as_number
from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
)
from .jsonapi import threshold_status

FLAVOUR = "flavour"
SYSTEM_DATABASE = "_internal"
#: Columns of Flux's CSV that say where a row came from, not what it measured.
BOOKKEEPING = {"", "result", "table", "_start", "_stop", "_time"}


def _version(text: Any) -> str:
    return str(text or "").lstrip("v")


class InfluxdbAdapter(Adapter):
    kind = "influxdb"
    label = "InfluxDB"
    category = "monitoring"
    description = "Whether InfluxDB is up, its buckets or databases, and one query as a number with its history. Version 2 and 3."
    icon = "influxdb"
    #: Measured on 2026-10-27 against 2.7.12 and 3 Core 3.12.1, not yet an instance in use.
    beta = True
    docs_url = "https://docs.influxdata.com/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://influxdb:8086",
              help="Port 8086 for version 2, 8181 for version 3 Core."),
        Field("token", "Token", type="password", secret=True, required=True,
              help="An API token that may read; version 3 needs one for everything. The query cards run what you write with its rights, so a read-only token is the one to use."),
        Field("org", "Organization", help="Version 2 only: the name of the organization the queries run in. Empty takes the first one the token can see."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="status", label="InfluxDB",
                   description="Whether it is ready, its version and how many buckets or databases it holds.",
                   renderer="value", default_size=(2, 2), refresh_seconds=60, metrics=("buckets",)),
        WidgetType(kind="buckets", label="Buckets",
                   description="The buckets of version 2 with how long each keeps its data, or the databases of version 3.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("system", "System buckets", type="bool", default=False, help="Also the ones InfluxDB keeps for itself, such as _monitoring and _tasks."),
                            Field("limit", "Entries", type="number", default=10))),
        WidgetType(kind="query", label="Query value",
                   description="A Flux query (version 2) or an SQL query (version 3) that returns one number, drawn with its history.",
                   renderer="chart", default_size=(3, 2), refresh_seconds=60, metrics=("value",),
                   options=(
                       Field("query", "Query", type="textarea", required=True,
                             placeholder='from(bucket: "telemetry") |> range(start: -1h) |> filter(fn: (r) => r._field == "usage") |> last()',
                             help="Flux for version 2, SQL for version 3. The first number of the answer is the value."),
                       Field("database", "Database", help="Version 3 only: the database the query runs in."),
                       Field("label", "Label", placeholder="CPU"),
                       Field("unit", "Unit", placeholder="%"),
                       Field("decimals", "Decimals", type="number", default=1),
                       Field("warn_above", "Warn above", type="number"),
                       Field("bad_above", "Alarm above", type="number"),
                   )),
    )

    # -- talking to it -------------------------------------------------------

    @staticmethod
    def _headers(config: dict[str, Any], flavour: str) -> dict[str, str]:
        scheme = "Bearer" if flavour == "3" else "Token"
        return {"Authorization": f"{scheme} {config.get('token') or ''}"}

    async def _flavour(self, config: dict[str, Any], ctx: Context) -> tuple[str, str]:
        """``("2", "2.7.12")`` or ``("3", "3.12.1")``, found by ``/ping`` and kept."""
        kept = ctx.cache.get(FLAVOUR)
        if isinstance(kept, tuple):
            return kept
        response = await ctx.request("GET", f"{base_url(config)}/ping", headers=self._headers(config, "3"),
                                     verify=not config.get("insecure"), auth_errors=False, timeout=10.0)
        if response.status_code in (401, 403):
            raise AuthFailed("InfluxDB rejected the token.")
        found: tuple[str, str] | None = None
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        if isinstance(body, dict) and str(body.get("product_name") or "").startswith("InfluxDB 3"):
            found = ("3", _version(body.get("version")))
        elif response.headers.get("X-Influxdb-Version", "").startswith("v2"):
            found = ("2", _version(response.headers["X-Influxdb-Version"]))
        if found is None:
            raise AdapterError("This address answers, but not the way InfluxDB does.", code="not_influxdb",
                               hint="The URL is InfluxDB's own address: port 8086 for version 2, 8181 for version 3. Version 1 is not supported.")
        ctx.cache[FLAVOUR] = found
        return found

    async def _call(self, config: dict[str, Any], ctx: Context, flavour: str, method: str, path: str, **more: Any) -> Any:
        headers = {**self._headers(config, flavour), **(more.pop("headers", None) or {})}
        response = await ctx.request(method, f"{base_url(config)}{path}", headers=headers, verify=not config.get("insecure"),
                                     auth_errors=False, **more)
        if response.status_code in (401, 403):
            raise AuthFailed("InfluxDB rejected the token.")
        return response

    @staticmethod
    def _failure(response: Any, what: str) -> AdapterError:
        try:
            body = response.json()
            message = str(body.get("message") or body.get("error") or "") if isinstance(body, dict) else ""
        except ValueError:
            message = response.text
        message = " ".join(message.split())[:200]
        if response.status_code == 404 and what == "query":
            return AdapterError(f"InfluxDB: {message}" if message else "InfluxDB does not know that database.", code="query_error",
                                hint="The Database field of the card is the name of a database, as in the list.")
        if message and what == "query":
            return AdapterError(f"InfluxDB rejected the query: {message}", code="query_error")
        return AdapterError(f"InfluxDB answered with HTTP {response.status_code}.", code="http_error")

    async def _buckets(self, config: dict[str, Any], ctx: Context, flavour: str) -> list[dict[str, Any]]:
        """Version 2: ``{"name", "system", "keeps"}`` per bucket. Version 3: the databases, ``_internal`` as the system one."""
        if flavour == "3":
            response = await self._call(config, ctx, "3", "GET", "/api/v3/configure/database", params={"format": "json"})
            if response.status_code >= 400:
                raise self._failure(response, "list")
            names = [str(one.get("iox::database") or "") for one in response.json() if isinstance(one, dict)]
            return [{"name": name, "system": name == SYSTEM_DATABASE, "keeps": None} for name in names if name]
        response = await self._call(config, ctx, "2", "GET", "/api/v2/buckets", params={"limit": 100})
        if response.status_code >= 400:
            raise self._failure(response, "list")
        found = []
        for bucket in response.json().get("buckets") or []:
            rules = [rule for rule in bucket.get("retentionRules") or [] if isinstance(rule, dict)]
            seconds = rules[0].get("everySeconds") if rules else 0
            found.append({"name": str(bucket.get("name") or "?"), "system": bucket.get("type") == "system", "keeps": seconds or 0})
        return found

    async def _health(self, config: dict[str, Any], ctx: Context, flavour: str) -> tuple[bool, str]:
        response = await self._call(config, ctx, flavour, "GET", "/health", timeout=10.0)
        if flavour == "3":
            return response.status_code == 200, "" if response.status_code == 200 else f"HTTP {response.status_code}"
        try:
            body = response.json()
        except ValueError:
            body = {}
        ready = response.status_code == 200 and body.get("status") == "pass"
        return ready, "" if ready else " ".join(str(body.get("message") or f"HTTP {response.status_code}").split())[:120]

    async def _organization(self, config: dict[str, Any], ctx: Context) -> str:
        named = str(config.get("org") or "").strip()
        if named:
            return named
        kept = ctx.cache.get("org")
        if isinstance(kept, str):
            return kept
        response = await self._call(config, ctx, "2", "GET", "/api/v2/orgs")
        orgs = response.json().get("orgs") if response.status_code < 400 else None
        if not orgs:
            raise AdapterError("InfluxDB shows this token no organization.", code="missing_org",
                               hint="Enter the name of the organization in the connection, or use a token that may read it.")
        ctx.cache["org"] = str(orgs[0].get("name") or orgs[0].get("id"))
        return ctx.cache["org"]

    async def _number(self, config: dict[str, Any], ctx: Context, flavour: str, options: dict[str, Any]) -> float:
        query = str(options.get("query") or "").strip()
        if not query:
            raise AdapterError("No query is set.", code="missing_query")
        if flavour == "3":
            database = str(options.get("database") or "").strip()
            if not database:
                raise AdapterError("This card names no database.", code="missing_database", hint="Version 3 runs a query in one database; fill in the Database field.")
            response = await self._call(config, ctx, "3", "POST", "/api/v3/query_sql", json_body={"db": database, "q": query, "format": "json"})
            if response.status_code >= 400:
                raise self._failure(response, "query")
            number = first_sql_number(response.json())
        else:
            org = await self._organization(config, ctx)
            response = await self._call(config, ctx, "2", "POST", "/api/v2/query", params={"org": org}, content=query.encode("utf-8"),
                                        headers={"Content-Type": "application/vnd.flux", "Accept": "application/csv"})
            if response.status_code >= 400:
                raise self._failure(response, "query")
            number = first_csv_number(response.text)
        if number is None:
            raise AdapterError("The query returned no number.", code="empty_result",
                               hint="Try it in InfluxDB's own query page first: it has to end in one row with one number.")
        return number

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        flavour, version = await self._flavour(config, ctx)
        buckets = [one for one in await self._buckets(config, ctx, flavour) if not one["system"]]
        noun = "databases" if flavour == "3" else "buckets"
        return f"InfluxDB {version} answers, {len(buckets)} {noun}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        flavour, version = await self._flavour(config, ctx)
        if widget_kind == "query":
            value = await self._number(config, ctx, flavour, options)
            return self._value(value, options)
        buckets = await self._buckets(config, ctx, flavour)
        if widget_kind == "buckets":
            return self._listing(buckets, options, flavour)
        ready, why = await self._health(config, ctx, flavour)
        return self._status(ready, why, version, flavour, buckets)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _value(number: float, options: dict[str, Any]) -> WidgetData:
        return WidgetData(
            status=threshold_status(number, options),
            primary={"label": options.get("label") or "", "value": round(number, int(options.get("decimals") or 0)), "unit": options.get("unit") or ""},
            metrics={"value": number},
        )

    @staticmethod
    def _status(ready: bool, why: str, version: str, flavour: str, buckets: list[dict[str, Any]]) -> WidgetData:
        count = sum(1 for one in buckets if not one["system"])
        noun = "Databases" if flavour == "3" else "Buckets"
        return WidgetData(
            status="ok" if ready else "bad",
            primary={"label": noun, "value": count, "unit": ""},
            secondary=[{"label": "State", "value": "Ready" if ready else why or "Not ready"}, {"label": "Version", "value": version}],
            metrics={"buckets": float(count)},
        )

    @staticmethod
    def _listing(buckets: list[dict[str, Any]], options: dict[str, Any], flavour: str) -> WidgetData:
        shown = [one for one in buckets if options.get("system") or not one["system"]]
        rows = []
        for one in sorted(shown, key=lambda one: (one["system"], one["name"].lower())):
            keeps = one["keeps"]
            rows.append({
                "title": one["name"],
                "subtitle": " · ".join(part for part in ("System" if one["system"] else "", "" if keeps is None else "Keeps forever" if keeps == 0 else f"Keeps {duration_short(keeps)}") if part),
                "status": "ok",
            })
        noun = "databases" if flavour == "3" else "buckets"
        return WidgetData(items=rows[: max(1, int(options.get("limit") or 10))], meta={"empty": f"No {noun} yet."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "query":
            return self._value(fake.walk("influx-query", tick, 12, 48), {**options, "label": options.get("label") or "CPU", "unit": options.get("unit") or "%"})
        buckets = [{"name": "telemetry", "system": False, "keeps": 30 * 86400}, {"name": "homeassistant", "system": False, "keeps": 0},
                   {"name": "_monitoring", "system": True, "keeps": 7 * 86400}]
        if widget_kind == "buckets":
            return self._listing(buckets, options, "2")
        return self._status(True, "", "2.7.12", "2", buckets)


def first_csv_number(text: str) -> float | None:
    """The first ``_value`` of Flux's annotated CSV; the last column that is a number when the query renamed it. Rows are blank between tables."""
    header: list[str] | None = None
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(cell.strip() for cell in row) or row[0].startswith("#"):
            continue
        if header is None or ("_value" in row and "result" in row):
            header = row
            continue
        cells = dict(zip(header, row, strict=False))
        number = as_number(cells.get("_value"))
        if number is not None:
            return number
        # ⚠️ Not the table number: "result" and "table" are bookkeeping and read as 0.
        for name in reversed([name for name in header if name not in BOOKKEEPING]):
            number = as_number(cells.get(name))
            if number is not None:
                return number
    return None


def first_sql_number(rows: Any) -> float | None:
    """The first number of the first row, whatever the column is called."""
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    for key, value in rows[0].items():
        if key != "time" and not isinstance(value, bool):
            number = as_number(value)
            if number is not None:
                return number
    return None


ADAPTER = InfluxdbAdapter()
