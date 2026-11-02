"""Maltrail: what its sensors saw on the network today, the latest findings, and the days before.

Read from the addresses Maltrail's own page reads, after a sign-in like the page's: ``/events?date=`` hands out a
day's log as it lies on disk, ``/counts`` the number of events per day. Maltrail has no API key; the session cookie
lives 24 hours and holds only for the address that signed in, which for nexdeck is always the same one.

⚠️ Two sign-ins. Up to release 3.5 the page sends ``hash = sha256(sha256(password) + nonce)`` with a nonce of its
own, and a server answers a wrong one only after five seconds. The code after 3.5 keeps a user entry in that old
form working the same way, but an entry written by ``--hash-password`` (``pbkdf2-sha256$…``) wants a proof made
with the salt and a nonce from ``/login/params`` (SCRAM, see Maltrail's ``core/password.py``). The old way is tried
first, because every release understands it, and the way that worked is remembered.

⚠️ Two answers of ``/counts``. Up to 2.1 a day is keyed by the Unix time of its midnight on the Maltrail server, and
a day larger than 8 KB is an estimate rounded to hundreds; from 3.0 on a day is keyed by its date and counted
exactly. The list marks an estimate with ≈.

⚠️ A log line is eleven fields separated by spaces, a field with a space or a quote in quotes, and an empty field a
``-``. With ``LOCAL_LOG_FORMAT json`` the same day may hold JSON lines; those carry a ``severity`` of their own.

The severity of a text line is what Maltrail's regex makes of its info and reference; the regex is the one
Maltrail ships, so an operator's own ``REMOTE_SEVERITY_REGEX`` is not followed here.

"Today" is the day on nexdeck's clock, and a log file is named by the Maltrail server's: both want the same
time zone.

Measured on 02.11.2026 against release 1.4 and the code after 3.5 (``a30caa2``) in a throwaway container, with a
made-up custom trail and DNS queries over loopback: both sign-ins, an old entry on the new code, the shipped password
(403), a wrong password (1.4 answers it after 5 s, twice), all three cards. Not against a sensor on a real network.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timedelta
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
    base_url,
)

COOKIE = "maltrail_sessid"
FIELDS = ("time", "sensor", "src_ip", "src_port", "dst_ip", "dst_port", "proto", "type", "trail", "info", "reference")
#: ``REMOTE_SEVERITY_REGEX`` as maltrail.conf ships it, matched against the info and the reference like Maltrail does.
SEVERITY = re.compile(
    r"(?P<high>(remote )?custom\)|malwaredomainlist|malware(?! (distribution|site))|adversary|ransomware)"
    r"|(?P<medium>potential malware site|malware distribution|c2 cert|iot-malware|potential infection)"
    r"|(?P<low>mass scanner|reputation|attacker|spammer|compromised|crawler|scanning|\(suspicious\) \(heuristic\))"
)
RANK = {"low": 1, "medium": 2, "high": 3}
STATUS = {"high": "bad", "medium": "warn", "low": "unknown"}
#: A wrong password is not tried again on every refresh: a server after 3.5 refuses an address after five failures.
REFUSED_SECONDS = 60.0
#: A day's log is read whole; this is some 150,000 events.
DAY_BYTES = 32 * 1024 * 1024


def _value(text: Any) -> str:
    text = str(text if text is not None else "").strip()
    return "" if text == "-" else text


def parse_line(line: str) -> dict[str, str] | None:
    """One event of a day's log, or None for a line that is not one."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            one = json.loads(line)
        except ValueError:
            return None
        if not isinstance(one, dict):
            return None
        event = {name: _value(one.get(name)) for name in FIELDS}
        if not event["time"] and isinstance(one.get("timestamp"), (int, float)):
            event["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(one["timestamp"]))
        event["severity"] = _value(one.get("severity")).lower()
        return event
    try:
        row = next(csv.reader([line], delimiter=" ", quotechar='"', doublequote=True))
    except (csv.Error, StopIteration):
        return None
    if len(row) < len(FIELDS):
        return None
    return {name: _value(value) for name, value in zip(FIELDS, row[: len(FIELDS)], strict=True)}


def severity_of(event: dict[str, str]) -> str:
    if event.get("severity") in RANK:
        return event["severity"]
    match = SEVERITY.search(f"{event.get('info', '')} {event.get('reference', '')}")
    if match:
        for name in ("low", "medium", "high"):
            if match.group(name):
                return name
    return "medium"


def _clock(event: dict[str, str]) -> str:
    """``16:04`` of ``2026-11-02 16:04:01.123456``."""
    return event.get("time", "")[11:16]


def day_counts(answer: Any) -> list[tuple[str, int, bool]]:
    """``(date, events, estimated)`` per day, oldest first, from either form of ``/counts``."""
    days: dict[str, tuple[int, bool]] = {}
    for key, number in (answer or {}).items() if isinstance(answer, dict) else ():
        try:
            count = int(number)
        except (TypeError, ValueError):
            continue
        key = str(key)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
            days[key] = (count, False)
        elif key.isdigit():
            # The midnight of the Maltrail server; half a day later is the same date in any time zone nexdeck may have.
            day = time.strftime("%Y-%m-%d", time.localtime(int(key) + 43200))
            # Rounded to hundreds once the day's file is past 8 KB: a number that ends in two zeros may be one.
            days[day] = (count, count >= 100 and count % 100 == 0)
    return [(day, *days[day]) for day in sorted(days)]


def _short_day(day: str) -> str:
    try:
        return datetime.strptime(day, "%Y-%m-%d").strftime("%a %d.%m.")
    except ValueError:
        return day


def _proof(password: str, username: str, nonce: str, salt_hex: str, iterations: int) -> str:
    """The proof of Maltrail's ``core/password.py``, keyed on ``sha256(password)`` in hex like the page's."""
    legacy = hashlib.sha256(password.encode()).hexdigest()
    salted = hashlib.pbkdf2_hmac("sha256", legacy.encode(), bytes.fromhex(salt_hex), iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    signature = hmac.new(hashlib.sha256(client_key).digest(), f"{username}:{nonce}".encode(), hashlib.sha256).digest()
    return bytes(a ^ b for a, b in zip(client_key, signature, strict=True)).hex()


class MaltrailAdapter(Adapter):
    kind = "maltrail"
    label = "Maltrail"
    category = "network"
    description = "What Maltrail's sensors found on the network today, the latest findings, and the days before."
    #: Neither dashboard-icons nor selfh.st has a logo for it.
    icon = "lucide:shield"
    docs_url = "https://github.com/stamparm/maltrail#readme"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://maltrail:8338",
              help="The address of the Maltrail server, port 8338 by default."),
        Field("username", "User name", default="admin"),
        Field("password", "Password", type="password", secret=True,
              help="A user from USERS in maltrail.conf. Not needed when USERS is empty."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "A user of its own for nexdeck is best: add a line to USERS in maltrail.conf and restart the server.",
        "The password admin is shipped with is accepted only from the Maltrail server itself.",
    )
    widgets = (
        WidgetType(kind="summary", label="Today", description="How many events today, how many of them serious, and when the last one came.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("events", "high")),
        WidgetType(kind="findings", label="Latest findings", description="The newest events of the day: what, from where, and when.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("severity", "At least", type="select", default="low",
                                  options=(("low", "Everything"), ("medium", "Medium and high"), ("high", "High only"))))),
        WidgetType(kind="history", label="Days", description="Events per day.", bars=True,
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("days", "Days", type="select", default="7", options=(("7", "7 days"), ("14", "14 days"), ("30", "30 days"))),)),
    )

    # -- signing in ----------------------------------------------------------

    def _cookie_of(self, response: Any) -> str:
        for line in response.headers.get_list("set-cookie"):
            match = re.search(rf"{COOKIE}=([^;]+)", line)
            if match:
                return match.group(1)
        return ""

    async def _post_login(self, config: dict[str, Any], ctx: Context, form: dict[str, str]) -> Any:
        # 20 s: an older server answers a wrong password after five seconds, and this may be the second try.
        return await ctx.request("POST", f"{base_url(config)}/login", data=form, verify=not config.get("insecure"),
                                 auth_errors=False, timeout=20)

    async def _sign_in(self, config: dict[str, Any], ctx: Context, stale: str) -> str:
        """A fresh session, or the one a card next to this one opened meanwhile."""
        lock = ctx.cache.setdefault("maltrail_lock", asyncio.Lock())
        async with lock:
            current = ctx.cache.get("maltrail_cookie", "")
            if current and current != stale:
                return current
            refused = ctx.cache.get("maltrail_refused", 0.0)
            if refused and time.monotonic() - refused < REFUSED_SECONDS:
                raise AuthFailed("Maltrail rejected the user name or password.")
            username = str(config.get("username") or "admin")
            password = str(config.get("password") or "")
            response = None
            if ctx.cache.get("maltrail_scheme") != "proof":
                nonce = secrets.token_hex(16)
                digest = hashlib.sha256((hashlib.sha256(password.encode()).hexdigest() + nonce).encode()).hexdigest()
                response = await self._post_login(config, ctx, {"username": username, "hash": digest, "nonce": nonce})
            if response is None or response.status_code == 401:
                # The server after 3.5 with an entry in the new form; any older one answers 401 here too.
                params = await ctx.request("GET", f"{base_url(config)}/login/params", params={"username": username},
                                           verify=not config.get("insecure"), auth_errors=False, timeout=20)
                try:
                    given = params.json() if params.status_code == 200 else None
                except ValueError:
                    given = None
                if isinstance(given, dict) and given.get("nonce") and given.get("salt"):
                    nonce = str(given["nonce"])
                    if given.get("legacy"):
                        form = {"username": username, "nonce": nonce,
                                "hash": hashlib.sha256((hashlib.sha256(password.encode()).hexdigest() + nonce).encode()).hexdigest()}
                    else:
                        proof = await asyncio.to_thread(_proof, password, username, nonce, str(given["salt"]), int(given.get("iterations") or 50000))
                        form = {"username": username, "nonce": nonce, "proof": proof}
                    response = await self._post_login(config, ctx, form)
                    if response.status_code == 200:
                        ctx.cache["maltrail_scheme"] = "proof"
            if response.status_code == 403:
                # The password the server is shipped with, from anywhere but the server itself.
                raise AdapterError("Maltrail accepts its shipped password only from the server itself.", code="default_password",
                                   hint="Give the user a password of its own in USERS in maltrail.conf.")
            cookie = self._cookie_of(response) if response.status_code == 200 else ""
            if not cookie:
                ctx.cache["maltrail_refused"] = time.monotonic()
                raise AuthFailed("Maltrail rejected the user name or password.")
            ctx.cache.pop("maltrail_refused", None)
            ctx.cache["maltrail_cookie"] = cookie
            return cookie

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any], cache: float = 10) -> Any:
        cookie = ctx.cache.get("maltrail_cookie", "")
        for attempt in (1, 2):
            response = await ctx.request(
                "GET", f"{base_url(config)}{path}", params=params, headers={"Cookie": f"{COOKIE}={cookie}"} if cookie else None,
                verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False, max_bytes=DAY_BYTES,
            )
            # Without a user in USERS, Maltrail asks nobody to sign in.
            if response.status_code == 401 and attempt == 1:
                cookie = await self._sign_in(config, ctx, cookie)
                continue
            break
        if response.status_code == 401:
            raise AuthFailed("Maltrail did not accept the session.")
        if response.status_code >= 400:
            raise AdapterError(f"Maltrail answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the Maltrail server, port 8338 by default.")
        return response

    async def _events(self, config: dict[str, Any], ctx: Context) -> list[dict[str, str]]:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        response = await self._get(config, ctx, "/events", {"date": today})
        events = [event for event in (parse_line(line) for line in response.text.splitlines()) if event]
        for event in events:
            event["severity"] = severity_of(event)
        # Written as they came; the newest first.
        return sorted(events, key=lambda event: event["time"], reverse=True)

    async def _days(self, config: dict[str, Any], ctx: Context, days: int, cache: float = 60) -> list[tuple[str, int, bool]]:
        today = datetime.now().astimezone().date()
        response = await self._get(config, ctx, "/counts", {"from": (today - timedelta(days=days - 1)).isoformat(), "to": today.isoformat()}, cache)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("This address answers, but not the way Maltrail does.", code="not_maltrail",
                               hint="Check the URL; it is the address of the Maltrail server, port 8338 by default.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Maltrail does.", code="not_maltrail")
        return day_counts(answer)

    # -- the cards -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        days = await self._days(config, ctx, 1, cache=0)
        count = days[-1][1] if days else 0
        return f"Maltrail answers: {count} events today."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "history":
            return self._history(await self._days(config, ctx, int(options.get("days") or 7)))
        events = await self._events(config, ctx)
        if widget_kind == "findings":
            return self._findings(events, options)
        return self._summary(events)

    @staticmethod
    def _summary(events: list[dict[str, str]]) -> WidgetData:
        counted = {name: sum(1 for event in events if event["severity"] == name) for name in ("high", "medium", "low")}
        secondary: list[dict[str, Any]] = [{"label": "High", "value": counted["high"]}, {"label": "Medium", "value": counted["medium"]},
                                           {"label": "Low", "value": counted["low"]}]
        if events:
            secondary.append({"label": "Last event", "value": _clock(events[0])})
        return WidgetData(
            status="warn" if counted["high"] else "ok",
            primary={"label": "Events today", "value": len(events)},
            secondary=secondary,
            metrics={"events": float(len(events)), "high": float(counted["high"])},
        )

    @staticmethod
    def _findings(events: list[dict[str, str]], options: dict[str, Any]) -> WidgetData:
        floor = RANK.get(str(options.get("severity") or "low"), 1)
        shown = [event for event in events if RANK[event["severity"]] >= floor]
        items = []
        for event in shown[: int(options.get("limit") or 8)]:
            route = " → ".join(part for part in (event["src_ip"], event["dst_ip"]) if part)
            items.append({
                # Maltrail puts the part of a name that matched in brackets: ``(www).example.com``.
                "title": event["trail"].replace("(", "").replace(")", "")[:80] or event["info"] or "?",
                "subtitle": " · ".join(part for part in (event["info"], route) if part),
                "status": STATUS[event["severity"]],
                "value": _clock(event),
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Today", "value": len(events)}],
            meta={"empty": "Nothing found today."},
        )

    @staticmethod
    def _history(days: list[tuple[str, int, bool]]) -> WidgetData:
        items = [{"title": _short_day(day), "value": count, "display": f"≈ {count}" if estimated else str(count)}
                 for day, count, estimated in reversed(days)]
        return WidgetData(status="ok", items=items, meta={"empty": "No events in these days."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        today = datetime.now().astimezone()
        rows = [
            ("16:04:11", "192.0.2.24", "198.51.100.9", "malware-c2.example", "malware (static)", "high"),
            ("15:51:40", "203.0.113.50", "192.0.2.10", "203.0.113.50", "mass scanner", "low"),
            ("15:43:02", "192.0.2.31", "198.51.100.77", "x7f3k9q2.example", "long domain (suspicious)", "medium"),
            ("14:12:55", "203.0.113.8", "192.0.2.10", "203.0.113.8", "known attacker", "low"),
        ]
        if fake.flicker("maltrail-new", tick, 0.5):
            rows.insert(0, ("16:20:37", "192.0.2.24", "198.51.100.9", "malware-c2.example", "malware (static)", "high"))
        events = [{"time": f"{today:%Y-%m-%d} {clock}.000000", "sensor": "pi", "src_ip": source, "src_port": "", "dst_ip": target,
                   "dst_port": "", "proto": "UDP", "type": "DNS", "trail": trail, "info": info, "reference": "", "severity": severity}
                  for clock, source, target, trail, info, severity in rows]
        if widget_kind == "history":
            counts = [31, 44, 28, 52, 37, 40, 30 + tick % 9]
            return self._history([((today - timedelta(days=6 - index)).strftime("%Y-%m-%d"), count, False) for index, count in enumerate(counts)])
        if widget_kind == "findings":
            return self._findings(events, options)
        return self._summary(events)


ADAPTER = MaltrailAdapter()
