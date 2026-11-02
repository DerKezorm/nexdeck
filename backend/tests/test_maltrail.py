"""Maltrail, against answers written from its server code: release 1.4 (the requester's) and the code after 3.5.

The sign-in is checked the way the server checks it, with the old digest and with the SCRAM proof of
``core/password.py``; the log lines are the form ``core/log.py`` writes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from datetime import datetime
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.maltrail import day_counts, parse_line, severity_of
from app.cards import source
from app.cards.schema import Request

MT = "http://maltrail.example.com:8338"
CONFIG = {"url": MT, "username": "nexdeck", "password": "made-up password"}
TODAY = datetime.now().astimezone().strftime("%Y-%m-%d")

#: The text form, as safe_value writes it: the time in quotes because of its space, an empty field a dash.
LINES = "\n".join((
    f'"{TODAY} 15:43:02.118342" pi 192.0.2.31 51512 198.51.100.77 53 UDP DNS x7f3k9q2.example "long domain (suspicious)" (heuristic)',
    f'"{TODAY} 16:04:11.502117" pi 192.0.2.24 40022 198.51.100.9 443 TCP IP 198.51.100.9 "malware (static)" abuse.ch',
    f'"{TODAY} 15:51:40.000901" pi 203.0.113.50 - 192.0.2.10 22 TCP IP 203.0.113.50 "mass scanner" (static)',
)) + "\n"


def _stored(password: str, salt: bytes, iterations: int) -> bytes:
    """``stored_key`` of Maltrail's core/password.py."""
    legacy = hashlib.sha256(password.encode()).hexdigest()
    salted = hashlib.pbkdf2_hmac("sha256", legacy.encode(), salt, iterations)
    return hashlib.sha256(hmac.new(salted, b"Client Key", hashlib.sha256).digest()).digest()


def _verify(stored: bytes, username: str, nonce: str, proof: str) -> bool:
    """``password.verify`` of Maltrail, line for line."""
    signature = hmac.new(stored, f"{username}:{nonce}".encode(), hashlib.sha256).digest()
    client_key = bytes(a ^ b for a, b in zip(bytes.fromhex(proof), signature, strict=True))
    return hmac.compare_digest(hashlib.sha256(client_key).digest(), stored)


def _form(request: httpx.Request) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(request.content.decode()).items()}


def _signed_in(request: httpx.Request) -> bool:
    return "maltrail_sessid=s3ss10n" in request.headers.get("cookie", "")


def _guarded(body: str | dict, *, json_body: bool = False):
    def answer(request: httpx.Request) -> httpx.Response:
        if not _signed_in(request):
            return httpx.Response(401)
        return httpx.Response(200, json=body) if json_body else httpx.Response(200, text=body)
    return answer


SESSION = {"Set-Cookie": "maltrail_sessid=s3ss10n; expires=Tue, 03 Nov 2026 16:00:00 GMT; path=/; HttpOnly; SameSite=strict"}


@pytest.fixture
def ctx() -> Context:
    # Without a cookie jar, like the shared client of the collector: the session has to travel in the adapter's own header.
    jar = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
    return Context(httpx.AsyncClient(cookies=jar), integration_id=1, widget_id=1, cache={})


def test_a_text_line_and_a_json_line() -> None:
    event = parse_line(LINES.splitlines()[2])
    assert event == {"time": f"{TODAY} 15:51:40.000901", "sensor": "pi", "src_ip": "203.0.113.50", "src_port": "", "dst_ip": "192.0.2.10",
                     "dst_port": "22", "proto": "TCP", "type": "IP", "trail": "203.0.113.50", "info": "mass scanner", "reference": "(static)"}
    quoted = parse_line('"2026-11-02 08:00:00.0" "pi ""north""" 192.0.2.1 1 192.0.2.2 2 TCP URL "a b" c d')
    assert quoted is not None and quoted["sensor"] == 'pi "north"' and quoted["trail"] == "a b"
    as_json = parse_line('{"timestamp": 1793606400, "time": "2026-11-02 08:00:00.000000", "sensor": "pi", "severity": "HIGH", "src_ip": "192.0.2.5",'
                         ' "src_port": 1, "dst_ip": "192.0.2.6", "dst_port": 53, "proto": "UDP", "type": "DNS", "trail": "bad.example",'
                         ' "info": "malware", "reference": "x"}')
    assert as_json is not None and as_json["severity"] == "high" and as_json["dst_port"] == "53" and as_json["trail"] == "bad.example"
    assert parse_line("") is None and parse_line("too few fields here") is None and parse_line("{not json") is None


def test_the_severity_follows_the_regex_maltrail_ships() -> None:
    def of(info: str, reference: str = "") -> str:
        return severity_of({"info": info, "reference": reference})
    assert of("malware (static)") == "high" and of("ransomware") == "high"
    assert of("malware distribution") == "medium" and of("potential malware site") == "medium"
    assert of("mass scanner") == "low" and of("known attacker") == "low"
    # Matched against the info and the reference together, as Maltrail does since its info alone said medium.
    assert of("long domain (suspicious)", "(heuristic)") == "low" and of("long domain (suspicious)") == "medium"
    assert of("something new") == "medium"
    assert severity_of({"info": "mass scanner", "severity": "high"}) == "high"


def test_both_forms_of_the_counts() -> None:
    """Up to 2.1 the Unix time of the server's midnight and an estimate in hundreds; from 3.0 the date, counted."""
    assert day_counts({"2026-11-01": 37, "2026-10-31": 412}) == [("2026-10-31", 412, False), ("2026-11-01", 37, False)]
    midnight = int(time.mktime(datetime(2026, 11, 1).timetuple()))
    assert day_counts({str(midnight): 37, str(midnight - 86400): 1200}) == [("2026-10-31", 1200, True), ("2026-11-01", 37, False)]
    assert day_counts({"2026-11-01": "x"}) == [] and day_counts([]) == []


@respx.mock
async def test_the_old_sign_in_of_every_release(ctx: Context) -> None:
    """1.4: ``hash = sha256(sha256(password) + nonce)`` with a nonce of the client's, then the cookie."""
    def login(request: httpx.Request) -> httpx.Response:
        form = _form(request)
        stored = hashlib.sha256(CONFIG["password"].encode()).hexdigest()
        if form.get("username") == "nexdeck" and form["hash"] == hashlib.sha256((stored + form["nonce"]).encode()).hexdigest():
            return httpx.Response(200, text="Login success", headers=SESSION)
        return httpx.Response(401, text="Login failed")
    signin = respx.post(f"{MT}/login").mock(side_effect=login)
    params = respx.get(f"{MT}/login/params").mock(return_value=httpx.Response(401))
    respx.get(f"{MT}/counts").mock(side_effect=_guarded({"2026-11-02": 3}, json_body=True))
    assert await get_adapter("maltrail").test(CONFIG, ctx) == "Maltrail answers: 3 events today."
    assert signin.call_count == 1 and params.call_count == 0 and len(_form(signin.calls.last.request)["nonce"]) == 32


@respx.mock
async def test_the_proof_of_the_code_after_3_5(ctx: Context) -> None:
    """An entry made by --hash-password takes no digest; the proof needs the salt and a nonce of the server's."""
    salt, iterations = bytes(range(16)), 1000
    stored = _stored(CONFIG["password"], salt, iterations)
    issued: list[str] = []

    def login_params(request: httpx.Request) -> httpx.Response:
        issued.append(f"n{len(issued)}" * 4)
        return httpx.Response(200, json={"iterations": iterations, "salt": salt.hex(), "nonce": issued[-1]})

    def login(request: httpx.Request) -> httpx.Response:
        form = _form(request)
        if "proof" in form and form["nonce"] in issued and _verify(stored, "nexdeck", form["nonce"], form["proof"]):
            return httpx.Response(200, text="Login success", headers=SESSION)
        return httpx.Response(401, text="Login failed")

    signin = respx.post(f"{MT}/login").mock(side_effect=login)
    respx.get(f"{MT}/login/params").mock(side_effect=login_params)
    respx.get(f"{MT}/counts").mock(side_effect=_guarded({"2026-11-02": 5}, json_body=True))
    assert await get_adapter("maltrail").test(CONFIG, ctx) == "Maltrail answers: 5 events today."
    assert [sorted(_form(call.request)) for call in signin.calls] == [["hash", "nonce", "username"], ["nonce", "proof", "username"]]
    # The way that worked is remembered: once the session runs out, no digest first.
    ctx.cache.pop("maltrail_cookie")
    ctx.cache = {key: value for key, value in ctx.cache.items() if not key.startswith("cache:")}
    await get_adapter("maltrail").test(CONFIG, ctx)
    assert sorted(_form(signin.calls.last.request)) == ["nonce", "proof", "username"] and signin.call_count == 3


@respx.mock
async def test_an_old_entry_on_the_new_code_gets_the_old_digest_with_the_server_s_nonce(ctx: Context) -> None:
    respx.post(f"{MT}/login").mock(side_effect=[
        httpx.Response(401, text="Login failed"),
        httpx.Response(200, text="Login success", headers=SESSION),
    ])
    respx.get(f"{MT}/login/params").mock(return_value=httpx.Response(200, json={"iterations": 50000, "salt": "ab" * 16, "nonce": "f" * 32, "legacy": True}))
    respx.get(f"{MT}/counts").mock(side_effect=_guarded({}, json_body=True))
    await get_adapter("maltrail").test(CONFIG, ctx)
    posted = [_form(call.request) for call in respx.calls if call.request.method == "POST"]
    stored = hashlib.sha256(CONFIG["password"].encode()).hexdigest()
    assert len(posted) == 2 and posted[1] == {"username": "nexdeck", "nonce": "f" * 32, "hash": hashlib.sha256((stored + "f" * 32).encode()).hexdigest()}


@respx.mock
async def test_a_wrong_password_is_not_tried_again_on_every_refresh(ctx: Context) -> None:
    """⚠️ A server after 3.5 refuses an address after five failures in a row."""
    signin = respx.post(f"{MT}/login").mock(return_value=httpx.Response(401, text="Login failed"))
    respx.get(f"{MT}/login/params").mock(return_value=httpx.Response(401))
    respx.get(f"{MT}/counts").mock(return_value=httpx.Response(401))
    for _ in range(3):
        with pytest.raises(AuthFailed):
            await get_adapter("maltrail").fetch("history", CONFIG, {"days": "7"}, ctx)
    assert signin.call_count == 1


@respx.mock
async def test_a_custom_card_reads_with_the_session_of_the_connection(ctx: Context) -> None:
    """A card's path goes out with the cookie the kind's own sign-in opened, after the server first said 401."""
    respx.post(f"{MT}/login").mock(return_value=httpx.Response(200, text="Login success", headers=SESSION))
    respx.get(f"{MT}/counts").mock(side_effect=_guarded({}, json_body=True))
    sensors = respx.get(f"{MT}/sensors").mock(side_effect=_guarded({"probe": {}}, json_body=True))
    await source.fetch_source(get_adapter("maltrail"), CONFIG, ctx, Request(id="probe", path="/sensors"))
    assert sensors.calls.last.response.status_code == 200 and _signed_in(sensors.calls.last.request)


@respx.mock
async def test_the_shipped_password_from_another_machine(ctx: Context) -> None:
    respx.post(f"{MT}/login").mock(return_value=httpx.Response(403, text="The default password is accepted only from the server itself."))
    respx.get(f"{MT}/counts").mock(return_value=httpx.Response(401))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("maltrail").test(CONFIG, ctx)
    assert refused.value.code == "default_password"


@respx.mock
async def test_without_users_nobody_signs_in(ctx: Context) -> None:
    signin = respx.post(f"{MT}/login").mock(return_value=httpx.Response(500))
    respx.get(f"{MT}/counts").mock(return_value=httpx.Response(200, json={}))
    assert await get_adapter("maltrail").test({"url": MT}, ctx) == "Maltrail answers: 0 events today."
    assert signin.call_count == 0


@respx.mock
async def test_two_cards_at_once_sign_in_once(ctx: Context) -> None:
    async def login(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, text="Login success", headers=SESSION)
    signin = respx.post(f"{MT}/login").mock(side_effect=login)
    respx.get(f"{MT}/events").mock(side_effect=_guarded(LINES))
    respx.get(f"{MT}/counts").mock(side_effect=_guarded({}, json_body=True))
    adapter = get_adapter("maltrail")
    await asyncio.gather(adapter.fetch("summary", CONFIG, {}, ctx), adapter.fetch("history", CONFIG, {"days": "7"}, ctx))
    assert signin.call_count == 1


@respx.mock
async def test_today_counted_by_severity(ctx: Context) -> None:
    respx.post(f"{MT}/login").mock(return_value=httpx.Response(200, text="Login success", headers=SESSION))
    events = respx.get(f"{MT}/events").mock(side_effect=_guarded(LINES))
    data = await get_adapter("maltrail").fetch("summary", CONFIG, {}, ctx)
    assert events.calls.last.request.url.params["date"] == TODAY
    assert data.primary == {"label": "Events today", "value": 3}
    assert data.secondary == [{"label": "High", "value": 1}, {"label": "Medium", "value": 0}, {"label": "Low", "value": 2},
                              {"label": "Last event", "value": "16:04"}]
    assert data.status == "warn" and data.metrics == {"events": 3.0, "high": 1.0}


@respx.mock
async def test_the_findings_newest_first_and_filtered(ctx: Context) -> None:
    respx.get(f"{MT}/events").mock(return_value=httpx.Response(200, text=LINES))
    adapter = get_adapter("maltrail")
    data = await adapter.fetch("findings", CONFIG, {"limit": 2}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("198.51.100.9", "malware (static) · 192.0.2.24 → 198.51.100.9", "bad", "16:04"),
        ("203.0.113.50", "mass scanner · 203.0.113.50 → 192.0.2.10", "unknown", "15:51"),
    ]
    assert data.secondary == [{"label": "Today", "value": 3}]
    high = await adapter.fetch("findings", CONFIG, {"severity": "high"}, ctx)
    assert [row["value"] for row in high.items] == ["16:04"]


@respx.mock
async def test_nothing_today(ctx: Context) -> None:
    """No log for the day is answered 200 with nothing, not 404."""
    respx.get(f"{MT}/events").mock(return_value=httpx.Response(200, text=""))
    adapter = get_adapter("maltrail")
    summary = await adapter.fetch("summary", CONFIG, {}, ctx)
    assert summary.primary == {"label": "Events today", "value": 0} and summary.status == "ok"
    assert (await adapter.fetch("findings", CONFIG, {}, ctx)).meta["empty"] == "Nothing found today."


@respx.mock
async def test_the_days_newest_first_and_an_estimate_marked(ctx: Context) -> None:
    midnight = int(time.mktime(datetime(2026, 11, 1).timetuple()))
    route = respx.get(f"{MT}/counts").mock(return_value=httpx.Response(200, json={str(midnight): 37, str(midnight - 86400): 1200}))
    data = await get_adapter("maltrail").fetch("history", CONFIG, {"days": "14"}, ctx)
    sent = route.calls.last.request.url.params
    assert sent["to"] == datetime.now().astimezone().date().isoformat() and sent["from"] < sent["to"]
    assert [(row["value"], row["display"]) for row in data.items] == [(37, "37"), (1200, "≈ 1200")]


@respx.mock
async def test_another_service_at_the_address(ctx: Context) -> None:
    respx.get(f"{MT}/counts").mock(return_value=httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("maltrail").test(CONFIG, ctx)
    assert wrong.value.code == "not_maltrail"


def test_the_demo_draws_every_card() -> None:
    adapter = get_adapter("maltrail")
    for kind in ("summary", "findings", "history"):
        data = adapter.demo(kind, {"limit": 8, "days": "7"}, 3)
        assert data.items or data.primary
