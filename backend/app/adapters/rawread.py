"""How a custom card signs in to a connection: the way the built-in cards of that connection do.

A custom card asks one path of a service. Every kind of connection has its own way to prove who is asking: a header,
a login name and password, a key in the address, a session that is opened first and renewed when it runs out. Nobody
writes that down a second time for the cards. Where a kind has the small helpers for headers and login
(``_headers``, ``_auth``) they are used as they are; everything else is **watched**: the kind's own connection test is
run once with a watcher on its requests, and what its first signed GET carried (headers, login, the parameters that
carry a key or a session) is what the card sends too. A kind that opens a session does so by its own sign-in, with its
own memory, and the card renews it the way the kind does: it forgets the session and signs in again.

⚠️ What is copied from the watched request is only what proves who asks. The parameters that merely ask (``cmd=``,
``limit=``) belong to the kind's own question and stay behind. The credentials are used for the address of the
connection and no other: the request goes through the same ``Context.request`` as every built-in card, which refuses a
redirect to another place when a card asks, and a card cannot set a header itself.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx

from ..credential_names import is_credential_name, words_of
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Unreachable,
    _refuse_a_giant_answer,
    guard_outbound,
    read_at_most,
)

#: How long what was watched is used before the kind is asked again. Cheap for a key (nothing leaves the server) and for
#: a session the kind keeps (its own memory answers), and it keeps a session id that ran out from living for ever.
SIGNED_FOR = 300.0
#: The memory keys, in the connection's own memory.
MEMORY = "card:signed"
#: One lock per connection around finding out how a card signs (see :func:`signed`) and around renewing the session.
LOCK = "card:lock"
#: ``(until, error, fingerprint)``: a connection test that failed is not run again for every card at every refresh.
FAILED = "card:failed"
FAIL_PAUSE = 45.0
#: When the session was last looked at after a card's request was refused. A refusal within this time is the card's own.
CHECKED = "card:checked"
CHECK_EVERY = 30.0
#: The most a card reads from one answer, in the connection's request already (not after it is in memory).
READ_AT_MOST = 2 * 1024 * 1024
#: Parameters that prove who asks are found by the words of their name (:mod:`..credential_names`, the list the log uses too);
#: a kind with a name that does not look like one lists it itself in ``raw_param_names``.
#: Headers every client sets, or that belong to a request body: not a proof of anything, and not copied.
NOT_COPIED = {"content-type", "content-length", "host", "connection", "accept-encoding", "transfer-encoding"}
#: Headers that prove nothing when they are the only ones there.
PLAIN = {"accept", "accept-language", "user-agent", "referer", "origin", "x-requested-with"}


#: Words that act, whatever the kind. Refused as a whole word in a path segment or the value of a parameter of a card's
#: request, never in an answer: ``lastUpdated``, ``/api/updates`` and a field called ``deletedAt`` are not touched.
ACTING_WORDS = frozenset({"reboot", "restart", "shutdown", "poweroff", "delete", "remove", "purge", "kill", "format", "reset", "factory"})


def _words_of(text: str) -> set[str]:
    """The whole words of a piece of an address: split at everything that is no letter or digit and at camel case."""
    text = unquote(unquote(text))
    return {word.lower() for word in re.split(r"[^A-Za-z0-9]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)) if word}


def refuse_a_command(adapter: Adapter, path: str) -> None:
    """Refuse a request of a card that is not a read, before it leaves.

    ⚠️ "Only GET" is not "only reading": ``GET /api.cgi?cmd=Reboot`` restarts a camera and ``GET /api?mode=queue&name=delete``
    empties the queue of SABnzbd, with the key of the connection. Two layers: the kinds whose address carries the command
    list what a card may ask (``raw_read_commands``), and for every kind the words that act are refused.
    """
    parts = urlsplit("http://x" + (path if path.startswith("/") else "/" + path))
    segments = [unquote(unquote(one)) for one in parts.path.split("/") if one]
    pairs = [(name.lower(), value) for name, value in parse_qsl(parts.query, keep_blank_values=True)]
    rules = adapter.raw_read_commands
    banned = ACTING_WORDS | (rules.words if rules else frozenset())

    def refuse(what: str) -> AdapterError:
        return AdapterError(
            f"A custom card only reads: the request asks for \"{what}\", which acts.",
            code="command_refused",
            hint="Ask for a command that only returns data. Commands that restart, delete, pause or change something "
                 "are not for a card, whoever wrote it.",
        )

    for segment in segments:
        hit = _words_of(segment) & banned
        if hit:
            raise refuse(sorted(hit)[0])
    for name, value in pairs:
        hit = (_words_of(value) | (_words_of(name) - {"format"})) & banned
        if hit:
            raise refuse(sorted(hit)[0])
    if rules is None:
        return
    for name, value in pairs:
        wanted = rules.params.get(name)
        if wanted is not None and value not in wanted:
            raise refuse(f"{name}={value}")
    lowered = [one.lower() for one in segments]
    for index, segment in enumerate(lowered):
        wanted = rules.after.get(segment)
        if wanted is not None and index + 1 < len(segments):
            command = segments[index + 1].removesuffix(".view")
            if command not in wanted:
                raise refuse(command)
    if rules.last is not None and segments and segments[-1].removesuffix(".view") not in rules.last:
        raise refuse(segments[-1])


@dataclass
class Sent:
    """What proves who asks, taken from a request of the kind itself."""

    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    auth: tuple[str, str] | None = None

    def signed(self) -> bool:
        return bool(self.auth or self.params or any(name.lower() not in PLAIN for name in self.headers))


class _Seen(BaseException):
    """Ends the connection test the moment its first signed request is known.

    ⚠️ Not an ``Exception``: a test that wraps whatever goes wrong into "could not be reached" must not swallow it.
    """

    def __init__(self, sent: Sent) -> None:
        super().__init__("signed request seen")
        self.sent = sent


def _origin(url: str) -> tuple[str, str, int]:
    parts = httpx.URL(url)
    return parts.scheme, (parts.host or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)


def _takes_the_parameter(adapter: Adapter, name: str) -> bool:
    return is_credential_name(name) or name in adapter.raw_param_names


def _is_static(adapter: Adapter) -> bool:
    """The kind has helpers that build its credentials from the connection alone."""
    cls = type(adapter)
    return callable(getattr(adapter, "_headers", None)) or callable(getattr(adapter, "_auth", None)) \
        or cls.raw_params is not Adapter.raw_params


#: A request that signs in, not one that asks: its credentials are the means to a session, never the template.
SIGN_IN_PATH = re.compile(r".*(log-?in|log-?on|sign-?in|authenticate|oauth2?|tokens?|sessions?|auth|anonymous)(\.php|\.cgi)?", re.I)
#: Words of a parameter name that belong to a sign-in; the words, not the letters: ``users`` and ``passes`` are not.
SIGN_IN_WORDS = frozenset({"pass", "passwd", "password", "passphrase", "pwd", "login", "account", "user", "username"})


def _asks_to_sign_in(url: str, params: dict[str, Any] | None, data: Any) -> bool:
    parts = httpx.URL(url)
    names = [*(params or {}), *(dict(data) if isinstance(data, dict) else {}), *parts.params.keys()]
    return bool(SIGN_IN_PATH.fullmatch(parts.path.rstrip('/').rsplit('/', 1)[-1])) or any(SIGN_IN_WORDS & set(words_of(str(name))) for name in names)


async def watch(adapter: Adapter, config: dict[str, Any], ctx: Context) -> Sent:
    """Run the kind's own connection test and keep what its first signed request to the connection's address carried.

    A GET is the best template. A kind that only speaks POST (a JSON-RPC, a GraphQL) is taken from its first signed POST
    when the test sees no signed GET: the headers and the login, never the body. A request that signs in (by its address
    or by a password in it) is passed over: what it carries is the way to a session, and the session is what the next
    request carries.
    """
    origin = _origin(adapter.raw_base(config))
    fallback: list[Sent] = []

    def tap(method: str, url: str, headers: dict[str, str] | None, params: dict[str, Any] | None, auth: Any, data: Any) -> None:
        if _origin(url) != origin or _asks_to_sign_in(url, params, data):
            return
        kept = {name: value for name, value in (headers or {}).items() if name.lower() not in NOT_COPIED}
        # ⚠️ The fields of a body are not copied into the address of a GET on a guess about their name: only those the kind lists
        # (``raw_param_names``), as Wallos does with ``api_key``.
        body = {name: value for name, value in (dict(data).items() if isinstance(data, dict) else []) if name in adapter.raw_param_names}
        found = {**dict(httpx.URL(url).params), **(params or {}), **body}
        carried = {name: value for name, value in found.items() if _takes_the_parameter(adapter, str(name))}
        sent = Sent(kept, carried, tuple(auth) if auth else None)  # type: ignore[arg-type]
        if not sent.signed():
            return
        if method.upper() == "GET":
            raise _Seen(sent)
        if not fallback:
            fallback.append(sent)

    try:
        await adapter.test(config, ctx.tapped(tap))
    except _Seen as seen:
        return seen.sent
    except (AuthFailed, Unreachable):
        # The service refuses the sign-in or does not answer: the card is told what the Test button would tell.
        raise
    except Exception:  # noqa: BLE001 - the test may fail for a reason of its own (an empty rule list); the card asks anyway
        pass
    # No signed GET was seen: take a signed POST, or none for a service that needs no sign-in.
    return fallback[0] if fallback else Sent()


def _lock(ctx: Context) -> asyncio.Lock:
    return ctx.cache.setdefault(LOCK, asyncio.Lock())  # type: ignore[no-any-return]


def _quiet(*_: Any) -> None:
    """A watcher that watches nothing: the kind's test runs, and what it asks is not noted as what a card reads."""


async def signed(adapter: Adapter, config: dict[str, Any], ctx: Context, *, again: bool = False) -> Sent:
    """How a request of a card is signed, for at most one run of the kind's connection test every five minutes.

    ⚠️ One at a time per connection. Ten cards that start together found no memory, ten ran the test, and a kind that signs in
    in its test (Pi-hole) was signed in ten times. A test that failed is remembered for a short while, so a card that refreshes
    every ten seconds does not repeat it every ten seconds against a service that refuses.
    """
    own = await adapter.raw_signed(config, ctx)
    if own is not None:
        return Sent(dict(own[0]), dict(own[1]), own[2])
    fetched = await adapter.raw_signed_headers(config, ctx)
    if fetched is not None:
        return Sent(dict(fetched))
    if _is_static(adapter):
        return Sent(adapter.raw_headers(config), dict(adapter.raw_params(config)), adapter.raw_auth(config))
    fingerprint = json.dumps(config, sort_keys=True, default=str)

    def held_still() -> Sent | None:
        held = ctx.cache.get(MEMORY)
        if held and not again and held[0] == fingerprint and held[1] > time.monotonic():
            return held[2]  # type: ignore[no-any-return]
        return None

    if (found := held_still()) is not None:
        return found
    async with _lock(ctx):
        if (found := held_still()) is not None:
            return found
        failed = ctx.cache.get(FAILED)
        if failed and failed[0] > time.monotonic() and failed[2] == fingerprint:
            raise copy.copy(failed[1])
        try:
            sent = await watch(adapter, config, ctx)
        except AdapterError as error:
            ctx.cache[FAILED] = (time.monotonic() + FAIL_PAUSE, error, fingerprint)
            raise
        ctx.cache.pop(FAILED, None)
        ctx.cache[MEMORY] = (fingerprint, time.monotonic() + SIGNED_FOR, sent)
        return sent


async def renew(adapter: Adapter, config: dict[str, Any], ctx: Context, before: Sent | None) -> Sent | None:
    """A card's request was refused with 401 or 403. Renew the session the way the kind does it for its own cards.

    The kind's own connection test runs, which is the kind's own function: it signs in again when its session is gone, with
    its logout, its lock against signing in twice and its pause after a failure. The card never signs in on its own and
    never throws away what the kind remembers. ``None`` when there was nothing to renew: the session is fine, the path is
    one the account may not read or the service does not have (a refusal that is the card's own), or the session was looked
    at a moment ago. Otherwise what signs the card's request now (``before`` is what signed it a moment ago).
    """
    async with _lock(ctx):
        last = ctx.cache.get(CHECKED)
        if last is not None and last + CHECK_EVERY > time.monotonic():
            return None
        ctx.cache[CHECKED] = time.monotonic()
        try:
            await adapter.test(config, ctx.tapped(_quiet))
        except (AuthFailed, Unreachable):
            raise
        except AdapterError:
            return None  # the test failed for a reason of its own: the refusal stays the card's
    if before is None:
        return Sent()  # a kind with a client of its own: ask again, the client carries its cookie
    ctx.cache.pop(MEMORY, None)
    after = await signed(adapter, config, ctx)
    return None if after == before else after


async def for_a_picture(adapter: Adapter, config: dict[str, Any], ctx: Context) -> tuple[dict[str, str], dict[str, Any]]:
    """Headers and parameters that sign a picture the server fetches on a card's behalf, the way the card's requests are."""
    import base64

    sent = await signed(adapter, config, ctx)
    headers = dict(sent.headers)
    if sent.auth is not None and not any(name.lower() == "authorization" for name in headers):
        headers["Authorization"] = "Basic " + base64.b64encode(f"{sent.auth[0]}:{sent.auth[1]}".encode()).decode()
    return headers, dict(sent.params)


async def ask(
    adapter: Adapter,
    method: str,
    path: str,
    config: dict[str, Any],
    ctx: Context,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    cache_seconds: float = 0,
) -> httpx.Response:
    """One request of a card, signed the way the kind signs its own."""
    from .jsonapi import join_path

    url = join_path(adapter.raw_base(config), path)
    held = adapter.raw_client(config, ctx)
    if held is not None:
        return await _through_the_clients_own_cookies(adapter, held, url, config, ctx, params)
    sent = await signed(adapter, config, ctx)
    for attempt in (0, 1):
        try:
            # ⚠️ Merged into the address here: httpx replaces the query of an address when ``params`` is given, and the
            # card's own question (``?api=...&method=...``) is the point of the request.
            more = {**sent.params, **(params or {})}
            response = await ctx.request(
                method.upper(),
                str(httpx.URL(url).copy_merge_params(more)) if more else url,
                headers=dict(sent.headers) or None,
                json_body=json_body,
                verify=adapter.raw_verify(config),
                auth=sent.auth,
                cache_seconds=cache_seconds,
                follow_redirects=False,
                max_bytes=READ_AT_MOST,
            )
            if adapter.raw_expired(response):
                raise AuthFailed()
            adapter.raw_accepted(ctx)
            if attempt == 1:
                ctx.cache.pop(CHECKED, None)  # the session really had run out: the next time may look again at once
            return response
        except AuthFailed as refusal:
            if adapter.raw_session:
                # ⚠️ An own connection with a session: only 401 means the ticket ran out. The adapter signs in again, once
                # per request of a card (attempt 0); a second 401 after that is the end of it (KARTEN-3 EC-3).
                if refusal.status == 401:
                    renewed = await adapter.raw_renew(config, ctx, (sent.headers, sent.params, sent.auth), again=attempt == 1)
                    if renewed is not None and attempt == 0:
                        sent = Sent(dict(renewed[0]), dict(renewed[1]), renewed[2])
                        continue
                raise
            # ⚠️ A refusal is not an expired session. Only a kind with a session of its own renews it, by its own function,
            # and a refusal on a path its built-in cards do not need stays the error of this card.
            if attempt == 1 or _is_static(adapter) or (renewed := await renew(adapter, config, ctx, sent)) is None:
                raise
            sent = renewed
    raise AdapterError("The service did not accept the sign-in.", code="auth_failed")  # pragma: no cover


async def _through_the_clients_own_cookies(
    adapter: Adapter, client: httpx.AsyncClient, url: str, config: dict[str, Any], ctx: Context, params: dict[str, Any] | None
) -> httpx.Response:
    """A kind that keeps the cookie of its sign-in in a client of its own (qBittorrent, UniFi): the card uses that client.

    ⚠️ The same client the kind's cards use, so the session is theirs. When the service says 401 or 403 the kind's own
    function looks at the session (:func:`renew`) and the card asks once more only if that was due.
    """
    guard_outbound(url)
    for attempt in (0, 1):
        try:
            response = await read_at_most(
                client, "GET", url, READ_AT_MOST, headers=adapter.raw_headers(config) or None, params=params, follow_redirects=False,
            )
        except httpx.TimeoutException as error:
            raise Unreachable("The service did not answer in time.") from error
        except httpx.HTTPError as error:
            raise Unreachable(f"The service could not be reached: {error.__class__.__name__}.") from error
        if response.status_code in (401, 403) and attempt == 0 and await renew(adapter, config, ctx, None) is not None:
            continue
        _refuse_a_giant_answer(url, response)
        if attempt == 1 and response.status_code not in (401, 403):
            ctx.cache.pop(CHECKED, None)
        return response
    raise AdapterError("The service did not accept the sign-in.", code="auth_failed")  # pragma: no cover
