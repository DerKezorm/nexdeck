"""PatchMon: which hosts have updates and security updates waiting, which have stopped reporting, and what they run.

Measured on 27.09.2026 against PatchMon 2.1.3 (the Go server, image
patchmon-server) with PostgreSQL 17 and Redis 7, and four hosts: a Debian 12.0
agent with 45 updates, six of them security updates, a Debian 13 agent and an
Alpine 3.20 agent with none, both stopped later to see them go overdue and
offline, and a fourth host created in PatchMon that never reported. One host
group held two of them, and a reboot flagged on the Debian 12 host
(``/var/run/reboot-required``) came back as ``needs_reboot`` with its next
report. The update interval was set to one minute for the measurement. Keys
of each kind were made through PatchMon's own API and tried switched off,
expired, without a scope, with an address list that leaves nexdeck out, and
against an instance without any host. Every card was seen against it.

⚠️ PatchMon has two read APIs with keys that do not mix. The GetHomepage
endpoint ``/api/v1/gethomepage/stats`` wants a key of the type GetHomepage
and answers only totals; the scoped API under ``/api/v1/api`` wants a key of
the type API and answers every host. Each refuses the other kind with 401
``Invalid API key type``. The adapter takes one key of the type API with the
scope ``host: get`` and works out every card from ``/api/v1/api/hosts
?include=stats``, so nobody has to make two keys. What that gives up is
``total_repos`` and ``recent_updates_24h``, and the second is not what its
name says: it counts the agents' successful reports of the last day, not
updates installed.

⚠️ The totals of the GetHomepage endpoint count distinct packages across
the fleet, the per host numbers count per host. The same package outdated
on three hosts is one there and three here. The overview adds up the per
host numbers, which is how many updates are waiting to be installed.

⚠️ PatchMon answers only at the address named in its ``CORS_ORIGIN``, the
API as much as the web interface: any other Host header gets 403 with
``code: host_mismatch``, measured with the container's bridge address and
with a second name. A nexdeck that reaches PatchMon under a name of its own
needs that name added there.

⚠️ An address below ``/api/v1/api`` that does not exist answers 200 with the
web interface's HTML, not 404. The adapter takes an answer that is not JSON
as a wrong address.

⚠️ ``status`` is how far enrolment got and stays ``active`` for ever.
``effective_status`` (PatchMon 2.0.3 and later) is what the web interface
shows: ``pending`` for a host that never reported, ``inactive`` once it has
been silent for twice the update interval. ``reporting_state`` splits the
middle out as ``overdue`` after one interval, but it called the host that
never reported ``reporting`` for the first minutes, because ``last_update``
is set when the host is created. The cards therefore ask ``effective_status``
first and trust ``last_update`` only for a host that has reported.

⚠️ A host that has not reported yet has the operating system ``unknown`` and
no packages. PatchMon leaves such hosts out of its distribution of systems and
does not call them up to date; the cards do the same. Alpine 3.20 reported
its version as ``Unknown``, which is left out as well.

⚠️ A host group is asked for with ``hostgroup``, by name or id. A group that
does not exist, or no longer does, answers an empty list and no error.

⚠️ Refusals, each 401 unless said otherwise, with the text in ``error``:
``Invalid API key``, ``Invalid API secret``, ``API key is disabled``, ``API
key has expired``, ``Invalid API key type``; 403 ``IP address not allowed``
for an address outside the key's list and 403 ``Access denied`` for a key
without ``host: get``. PatchMon's interface asks for a scope; its API made a
key of the type API without one.
"""

from __future__ import annotations

import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    join_parts,
    ring_of,
)

URL_HINT = "Check the URL; it is the address of PatchMon itself, without /api, as written in its CORS_ORIGIN."
KEY_HINT = ("Make the key in PatchMon under Settings > Integrations > Auto-Enrollment & API > New token, "
            "usage type API, with the scope host: get.")
GROUP = Field("group", "Host group", type="choices", help="Empty for every host.")
#: Security updates first, then the hosts that went quiet, then the rest.
RANK = {"security": 0, "offline": 1, "overdue": 2, "updates": 3, "waiting": 4, "ok": 5}
STATUS = {"security": "bad", "offline": "warn", "overdue": "warn", "updates": "warn", "waiting": "unknown", "ok": "ok"}
#: How many systems the ring shows before the rest become one slice.
RING_SLICES = 6


def _number(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _effective(host: dict[str, Any]) -> str:
    """``pending``, ``active`` or ``inactive``, the way the web interface says it."""
    effective = str(host.get("effective_status") or "")
    if effective:
        return effective
    # Before 2.0.3 only ``status`` came back, and it never says inactive.
    return "inactive" if host.get("reporting_state") == "stale" and host.get("status") == "active" else str(host.get("status") or "")


def _state(host: dict[str, Any]) -> str:
    """Where a host stands, worst first; see the top of the file."""
    effective = _effective(host)
    if effective == "pending" or not _number(host.get("total_packages")):
        return "waiting"
    if _number(host.get("security_updates_count")):
        return "security"
    if effective == "inactive":
        return "offline"
    if host.get("reporting_state") == "overdue":
        return "overdue"
    if _number(host.get("updates_count")):
        return "updates"
    return "ok"


def _known(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("", "unknown", "none") else text


def _system(host: dict[str, Any], versions: bool = True) -> str:
    name = _known(host.get("os_type"))
    if not name:
        return ""
    version = _known(host.get("os_version")) if versions else ""
    return f"{name} {version}" if version else name


class PatchMonAdapter(Adapter):
    kind = "patchmon"
    label = "PatchMon"
    category = "hosts"
    description = "Which hosts PatchMon sees with updates and security updates waiting, which have stopped reporting, and what they run."
    icon = "patchmon"
    beta = False
    docs_url = "https://github.com/PatchMon/PatchMon/blob/main/docs/patchmon-api-integrations-guide.md"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://patchmon:3000",
              help="PatchMon answers only at an address named in its CORS_ORIGIN."),
        Field("token_key", "Token key", type="password", secret=True, required=True, help=KEY_HINT + " A GetHomepage key does not work here."),
        Field("token_secret", "Token secret", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="PatchMon overview",
                   description="How many hosts need updates, with the security updates and updates waiting, the hosts up to date and those offline.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, ring=True,
                   metrics=("hosts_need_updates", "security_updates"),
                   parts=(("security", "Security updates"), ("updates", "Updates"), ("up_to_date", "Up to date"),
                          ("offline", "Offline"), ("reboot", "Reboot needed"), ("waiting", "No report yet")),
                   options=(GROUP,)),
        WidgetType(kind="hosts", label="Hosts",
                   description="Every host with its updates, security updates, operating system and last report, those with security updates and those offline first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, bars=True,
                   parts=(("value", "Updates"), ("os", "Operating system"), ("seen", "Last report")),
                   options=(Field("limit", "Entries", type="number", default=10),
                            Field("attention", "Only hosts that need attention", type="bool", default=False),
                            GROUP)),
        WidgetType(kind="systems", label="Operating systems",
                   description="How many hosts run which operating system, as rows, bars or a ring.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900, bars=True, ring=True,
                   options=(Field("versions", "Each version on its own", type="bool", default=True),
                            GROUP)),
    )

    # -- talking to PatchMon -------------------------------------------------

    async def _hosts(self, config: dict[str, Any], ctx: Context, group: str = "", cache: float = 10) -> list[dict[str, Any]]:
        params = {"include": "stats"}
        if group:
            params["hostgroup"] = group
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1/api/hosts", params=params,
            auth=(str(config.get("token_key") or "").strip(), str(config.get("token_secret") or "").strip()),
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        try:
            answer = response.json()
        except ValueError:
            answer = None
        said = str(answer.get("error") or "") if isinstance(answer, dict) else ""
        if response.status_code == 401:
            self._refused(said)
        if response.status_code == 403:
            if isinstance(answer, dict) and answer.get("code") == "host_mismatch":
                raise AdapterError("PatchMon answers only at the address set in its CORS_ORIGIN.", code="host_mismatch",
                                   hint="Add this URL to CORS_ORIGIN in PatchMon's .env or settings, or use the address written there.")
            if said == "IP address not allowed":
                raise AdapterError("PatchMon does not accept this key from nexdeck's address.", code="address_refused",
                                   hint="Add nexdeck's address to the key's allowed IP addresses in PatchMon, or empty the list.")
            raise AdapterError("The key may not read the hosts.", code="forbidden", hint=KEY_HINT)
        if response.status_code >= 400:
            raise AdapterError(f"PatchMon answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        # ⚠️ A wrong path answers 200 with the web interface.
        if not isinstance(answer, dict) or not isinstance(answer.get("hosts"), list):
            raise AdapterError("This address answers, but not the way PatchMon does.", code="not_patchmon", hint=URL_HINT)
        return [host for host in answer["hosts"] if isinstance(host, dict)]

    @staticmethod
    def _refused(said: str) -> None:
        if said == "API key is disabled":
            raise AuthFailed("The key is switched off in PatchMon.")
        if said == "API key has expired":
            raise AuthFailed("The key has expired in PatchMon.")
        if said == "Invalid API key type":
            refused = AuthFailed("This key is not of the type API.")
            refused.hint = KEY_HINT + " A GetHomepage key does not work here."
            raise refused
        refused = AuthFailed("PatchMon rejected the token key or its secret.")
        refused.hint = KEY_HINT
        raise refused

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        hosts = await self._hosts(config, ctx, cache=0)
        return f"PatchMon answers; it knows {len(hosts)} host(s)."

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "group":
            return await super().choices(field, config, ctx)
        return self._groups(await self._hosts(config, ctx, cache=60))

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return self._groups(self._demo_hosts(0)) if field == "group" else []

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        group = str(options.get("group") or "").strip()
        hosts = await self._hosts(config, ctx, group)
        return self._card(widget_kind, hosts, options, bool(group), time.time())

    # -- the cards -----------------------------------------------------------

    def _card(self, widget_kind: str, hosts: list[dict[str, Any]], options: dict[str, Any], grouped: bool, now: float) -> WidgetData:
        if widget_kind == "hosts":
            return self._host_rows(hosts, options, grouped, now)
        if widget_kind == "systems":
            return self._systems(hosts, options.get("versions") is not False, grouped)
        return self._summary(hosts)

    @staticmethod
    def _groups(hosts: list[dict[str, Any]]) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for host in hosts:
            for group in host.get("host_groups") or []:
                if isinstance(group, dict) and group.get("id"):
                    seen[str(group["id"])] = str(group.get("name") or group["id"])
        return sorted(seen.items(), key=lambda pair: pair[1].lower())

    @staticmethod
    def _summary(hosts: list[dict[str, Any]]) -> WidgetData:
        reported = [host for host in hosts if _state(host) != "waiting"]
        waiting = len(hosts) - len(reported)
        need = sum(1 for host in reported if _number(host.get("updates_count")))
        security_hosts = sum(1 for host in reported if _number(host.get("security_updates_count")))
        plain = sum(1 for host in reported if _number(host.get("updates_count")) and not _number(host.get("security_updates_count")))
        up_to_date = len(reported) - need
        offline = sum(1 for host in hosts if _effective(host) == "inactive")
        security = sum(_number(host.get("security_updates_count")) for host in hosts)
        updates = sum(_number(host.get("updates_count")) for host in hosts)
        reboot = sum(1 for host in hosts if host.get("needs_reboot") is True)
        secondary: list[dict[str, Any]] = [
            {"label": "Security updates", "value": security, "part": "security"},
            {"label": "Updates", "value": updates, "part": "updates"},
            {"label": "Up to date", "value": up_to_date, "part": "up_to_date"},
            {"label": "Offline", "value": offline, "part": "offline"},
        ]
        # Only where the number says something; see cup.py.
        if reboot:
            secondary.append({"label": "Reboot needed", "value": reboot, "part": "reboot"})
        if waiting:
            secondary.append({"label": "No report yet", "value": waiting, "part": "waiting"})
        if not hosts:
            status = "unknown"
        elif security:
            status = "bad"
        else:
            status = "warn" if need or offline else "ok"
        return WidgetData(
            status=status,
            primary={"label": "Need updates", "value": need, "unit": f"/ {len(hosts)}"},
            secondary=secondary,
            meta={"ring": ring_of(("Up to date", up_to_date), ("Need updates", plain),
                                  ("With security updates", security_hosts), ("No report yet", waiting))},
            metrics={"hosts_need_updates": float(need), "security_updates": float(security)},
        )

    @staticmethod
    def _host_rows(hosts: list[dict[str, Any]], options: dict[str, Any], grouped: bool, now: float) -> WidgetData:
        ranked = []
        for host in hosts:
            state = _state(host)
            security = _number(host.get("security_updates_count"))
            reported = state != "waiting"
            seen = ago(host.get("last_update"), now) if reported else ""
            if reported and _effective(host) == "inactive":
                # Said even when security updates rank the host first.
                word = f"Offline, last seen {seen} ago" if seen else "Offline"
                seen = ""
            elif not reported:
                word = "No report yet"
            else:
                word = "Report overdue" if host.get("reporting_state") == "overdue" else ""
            row: dict[str, Any] = {
                "title": str(host.get("friendly_name") or host.get("hostname") or "?"),
                "subtitle": join_parts(
                    options,
                    ("state", word),
                    ("security", f"{security} security update{'' if security == 1 else 's'}" if security else ""),
                    ("reboot", "Reboot needed" if host.get("needs_reboot") is True else ""),
                    ("os", _system(host)),
                    ("seen", f"{seen} ago" if seen else ""),
                ),
                "status": STATUS[state],
            }
            if reported:
                row["value"] = _number(host.get("updates_count"))
            ranked.append((RANK[state], -_number(host.get("updates_count")), row["title"].lower(), row))
        ranked.sort(key=lambda entry: entry[:3])
        rows = [entry[3] for entry in ranked]
        if options.get("attention") is True:
            rows = [row for row in rows if row["status"] != "ok"]
        if not hosts:
            empty = "No host in this group." if grouped else "PatchMon knows no host yet."
        else:
            empty = "Every host is up to date."
        worst = min((RANK[_state(host)] for host in hosts), default=RANK["ok"])
        status = {0: "bad", 1: "warn", 2: "warn", 3: "warn"}.get(worst, "ok" if hosts else "unknown")
        return WidgetData(status=status, items=rows[:max(1, int(options.get("limit") or 10))], meta={"empty": empty})

    @staticmethod
    def _systems(hosts: list[dict[str, Any]], versions: bool, grouped: bool) -> WidgetData:
        counts: dict[str, int] = {}
        kinds: dict[str, set[str]] = {}
        for host in hosts:
            # ⚠️ PatchMon counts only hosts that have reported.
            if _state(host) == "waiting":
                continue
            name = _system(host, versions)
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            version = _known(host.get("os_version"))
            if not versions and version:
                kinds.setdefault(name, set()).add(version)
        ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].lower()))
        rows = []
        for name, count in ordered:
            row: dict[str, Any] = {"title": name, "value": count, "status": "ok"}
            if kinds.get(name):
                row["subtitle"] = ", ".join(sorted(kinds[name]))
            rows.append(row)
        slices = [(name, count) for name, count in ordered[:RING_SLICES - 1]]
        rest = sum(count for _name, count in ordered[RING_SLICES - 1:])
        if len(ordered) == RING_SLICES:
            slices.append(ordered[-1])
        elif rest:
            slices.append(("Other", rest))
        return WidgetData(
            status="ok" if rows else "unknown",
            items=rows,
            meta={"ring": ring_of(*slices),
                  "empty": "No host in this group." if grouped and not hosts else "No host has reported its operating system yet."},
        )

    # -- demo ----------------------------------------------------------------

    @staticmethod
    def _demo_hosts(tick: int) -> list[dict[str, Any]]:
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        patched = fake.flicker("patchmon-patched", tick, 0.3)
        web = [{"id": "group-web", "name": "Web"}]
        infra = [{"id": "group-infra", "name": "Infrastructure"}]

        def host(name: str, os_type: str, version: str, updates: int, security: int, seen: float, *,
                 groups: list[dict[str, str]], state: str = "active", reporting: str = "reporting",
                 packages: int = 400, reboot: bool = False) -> dict[str, Any]:
            return {"friendly_name": name, "hostname": name, "host_groups": groups, "os_type": os_type, "os_version": version,
                    "last_update": stamp(seen), "status": "pending" if state == "pending" else "active", "effective_status": state,
                    "reporting_state": reporting, "needs_reboot": reboot, "updates_count": updates, "security_updates_count": security,
                    "total_packages": packages}

        return [
            host("web-01", "Ubuntu", "24.04 LTS", 0 if patched else 23, 0 if patched else 4, 300, groups=web, reboot=patched),
            host("web-02", "Ubuntu", "24.04 LTS", 11, 0, 420, groups=web),
            host("db-01", "Debian GNU/Linux", "12 (bookworm)", 6, 2, 600, groups=infra),
            host("backup", "Debian GNU/Linux", "13 (trixie)", 0, 0, 900, groups=infra),
            host("proxy", "Alpine Linux", "3.22.1", 0, 0, 240, groups=infra),
            host("nas", "Rocky Linux", "9.6", 3, 0, 86400 * 2, groups=infra, state="inactive", reporting="stale"),
            host("lab-vm", "unknown", "unknown", 0, 0, 1800, groups=[], state="pending", reporting="stale", packages=0),
        ]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        hosts = self._demo_hosts(tick)
        group = str(options.get("group") or "")
        if group:
            hosts = [host for host in hosts if any(one["id"] == group for one in host["host_groups"])]
        return self._card(widget_kind, hosts, options, bool(group), time.time())


ADAPTER = PatchMonAdapter()
