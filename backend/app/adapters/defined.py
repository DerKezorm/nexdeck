"""An own kind of connection, made from its definition (KARTEN-3).

The definition (``cards/integration_schema``) says what is asked when a connection is set up, how a request proves who
asks and which path tells that the service is there. This is the adapter that does it. It has no widgets: what is
read from the service is read by custom cards, through the same ``Adapter.raw_request`` as every built-in kind, with
every guard of it (a GET, underneath the address, no redirect to another place, 2 MB, no word that acts).

⚠️ Nothing here makes a request on its own. The sign-in of a session is the one POST an own connection may make, to
the sign-in path under the address of the connection, through ``Context.request`` like everything else. The key never
leaves the connection's address and never reaches a log, a message or the chronicle: messages are written here, not
taken from the service.

The module has no ``ADAPTER``: the registry does not load it as a built-in kind. ``cards/integration_store`` puts one
:class:`DefinedAdapter` per saved definition into the registry as ``custom:<short>``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jmespath

from ..cards import integration_schema as sch
from ..services.versions import version_in
from .base import Adapter, AdapterError, AuthFailed, Context, Field, WidgetType, base_url
from .jsonapi import join_path

#: Three failed sign-ins in a row stop the next ones for this long (EC-4).
FAILURES_BEFORE_PAUSE = 3
PAUSE = timedelta(minutes=15)
#: A ticket that was issued a moment ago and is refused at once is not one that ran out: no second sign-in for it.
FRESH = timedelta(seconds=5)
#: The most a sign-in answer is read.
SIGN_IN_AT_MOST = 256 * 1024
#: The longest ticket taken, and the memory key of a connection's session.
MAX_TICKET = 4096
STATE = "defined:state"

Parts = tuple[dict[str, str], dict[str, Any], tuple[str, str] | None]


def clock() -> datetime:
    """The time of day, the one place tests move."""
    return datetime.now(UTC)


class SignInFailed(AuthFailed):
    """The service did not accept the sign-in, or did not accept the ticket it gave."""

    def __init__(self, message: str = "The sign-in failed.") -> None:
        super().__init__(message)
        self.code = "sign_in_failed"
        self.hint = "Check the user name and the password, or the key, of the connection."


class SignInPaused(AdapterError):
    def __init__(self, until: datetime) -> None:
        shown = until.astimezone().strftime("%H:%M")
        super().__init__(
            f"Signing in is paused until {shown} after three failed attempts.",
            code="sign_in_paused",
            hint="nexdeck waits so that the service does not lock the account. Fix the settings of the connection; "
                 "the Test button signs in anyway.",
        )
        self.until = until


@dataclass
class Held:
    """The ticket of a connection, and what it was made for."""

    fingerprint: str
    parts: Parts
    issued: datetime


@dataclass
class State:
    """What a connection remembers of its session: in the memory of the connection, never in the database."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    held: Held | None = None
    failures: int = 0
    paused_until: datetime | None = None


def _state(ctx: Context) -> State:
    return ctx.cache.setdefault(STATE, State())  # type: ignore[no-any-return]


class MissingAdapter(Adapter):
    """The stand-in for a kind that is gone: connections of a deleted own kind stay in the database (KARTEN-3 EC-6)."""

    needs_integration = True
    beta = False

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.label = kind.removeprefix("custom:") or kind
        self.fields = ()
        self.widgets = ()

    @property
    def raw_access(self) -> bool:
        return False

    def _gone(self) -> AdapterError:
        return AdapterError(
            "integration missing",
            code="integration_missing",
            hint="The description of this kind of connection was deleted. Describe it again with the same short name and the connection works again.",
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        raise self._gone()

    async def raw_request(self, *args: Any, **keywords: Any) -> httpx.Response:
        raise self._gone()


class DefinedAdapter(Adapter):
    needs_integration = True
    optional_integration = False
    custom = True
    raw_session = False
    beta = False
    widgets: tuple[WidgetType, ...] = ()

    def __init__(self, definition: sch.IntegrationDefinition, source: str) -> None:
        self.definition = definition
        self.kind = f"custom:{definition.short}"
        self.label = definition.name
        self.category = definition.category
        self.description = definition.description
        self.icon = definition.logo
        self.raw_session = definition.auth.type == "session"
        self.fields = self._fields()
        self._digest = hashlib.sha256(source.encode()).hexdigest()

    # -- the form ----------------------------------------------------------------------------

    def _fields(self) -> tuple[Field, ...]:
        found: list[Field] = [Field("url", "URL", type="url", required=True, placeholder="https://example.com")]
        for one in self.definition.fields:
            kind: Any = {"text": "text", "secret": "password", "number": "number", "switch": "bool"}[one.type]
            found.append(
                Field(
                    one.name, one.label, type=kind, required=one.required, secret=one.type == "secret",
                    default=one.default if one.type != "switch" else bool(one.default),
                    help=one.help, placeholder=one.placeholder,
                )
            )
        found.append(Field("insecure", "Ignore TLS errors", type="bool", default=False))
        return tuple(found)

    # -- what a placeholder is -----------------------------------------------------------------

    def _value(self, name: str, config: dict[str, Any]) -> str:
        kind = next((one.type for one in self.definition.fields if one.name == name), "text")
        value = config.get(name)
        if value is None:
            return ""
        if kind == "switch":
            return "true" if value else "false"
        if kind == "number":
            try:
                number = float(value)
            except (TypeError, ValueError):
                return ""
            return str(int(number)) if number.is_integer() else str(number)
        return str(value)

    def _fill(self, template: str, config: dict[str, Any], ticket: str | None = None) -> str:
        def one(found: Any) -> str:
            name = found.group(1).strip()
            if ticket is not None and name == sch.TICKET:
                return ticket
            return self._value(name, config)

        return sch.PLACEHOLDER.sub(one, template)

    def _fingerprint(self, config: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps([self._digest, config], sort_keys=True, default=str).encode()).hexdigest()

    # -- how a request is signed ------------------------------------------------------------------

    async def raw_signed(self, config: dict[str, Any], ctx: Context) -> Parts | None:
        auth = self.definition.auth
        if auth.type == "none":
            return {}, {}, None
        if auth.type == "header":
            assert auth.header and auth.value
            return {auth.header: self._fill(auth.value, config)}, {}, None
        if auth.type == "basic":
            assert auth.user is not None and auth.password is not None
            return {}, {}, (self._fill(auth.user, config), self._fill(auth.password, config))
        if auth.type == "query":
            assert auth.param and auth.value
            return {}, {auth.param: self._fill(auth.value, config)}, None
        return (await self._session(config, ctx)).parts

    def raw_accepted(self, ctx: Context) -> None:
        state = ctx.cache.get(STATE)
        if state is not None and state.held is not None:
            state.failures = 0
            state.paused_until = None

    async def raw_renew(self, config: dict[str, Any], ctx: Context, refused: Parts, *, again: bool) -> Parts | None:
        """The service said 401 to a request signed with ``refused``.

        The first time in a request of a card: sign in again, once, and let the card ask again. A ticket made a moment
        ago, or a second 401 after the new sign-in, means the service takes the sign-in but not this path (a path the
        account may not read, one that is not there): the card says "sign-in failed" without trying a third time (EC-3).
        ⚠️ That is the error of this card and no failed sign-in: it is not counted and the ticket, which the service
        gave, stays for the other cards. Only :meth:`_sign_in` counts, so one card on a path that says 401 cannot pause the
        connection. Ten cards that all got the 401 sign in once (EC-8).
        """
        state = _state(ctx)
        fresh = state.held is not None and state.held.parts == refused and clock() - state.held.issued < FRESH
        if again or fresh:
            raise SignInFailed()
        return (await self._session(config, ctx, stale=refused)).parts

    def _count_failure(self, state: State) -> None:
        state.failures += 1
        if state.failures >= FAILURES_BEFORE_PAUSE:
            state.paused_until = clock() + PAUSE

    async def _session(self, config: dict[str, Any], ctx: Context, *, stale: Parts | None = None, force: bool = False) -> Held:
        """The ticket of this connection; signs in when there is none. One sign-in at a time (EC-8)."""
        state = _state(ctx)
        fingerprint = self._fingerprint(config)
        async with state.lock:
            held = state.held
            if held is not None and held.fingerprint == fingerprint and not force and (stale is None or held.parts != stale):
                return held
            if not force and state.paused_until is not None and clock() < state.paused_until:
                raise SignInPaused(state.paused_until)
            state.held = None
            ticket = await self._sign_in(config, ctx, state)
            state.held = Held(fingerprint, self._passed(ticket, config), clock())
            if force:
                state.failures = 0
                state.paused_until = None
            return state.held

    def _passed(self, ticket: str, config: dict[str, Any]) -> Parts:
        auth = self.definition.auth
        assert auth.pass_ is not None and auth.ticket is not None
        how = auth.pass_
        if how.as_ == "header":
            assert how.header and how.value
            return {how.header: self._fill(how.value, config, ticket)}, {}, None
        if how.as_ == "cookie":
            name = how.name or auth.ticket.name or "session"
            return {"Cookie": f"{name}={ticket}"}, {}, None
        assert how.param
        return {}, {how.param: ticket}, None

    async def _sign_in(self, config: dict[str, Any], ctx: Context, state: State) -> str:
        """The POST to the sign-in path, and the ticket in the answer.

        What counts as a failed sign-in (three in a row pause it): the service refuses with a 4xx, or answers without a
        ticket or with a web page. A service that cannot be reached or fails with a 5xx is not refusing anybody.
        """
        session = self.definition.auth.session()
        url = join_path(self.raw_base(config), session.login)
        body = {name: self._fill(text, config) for name, text in session.body.items()}
        response = await ctx.request(
            "POST", url,
            json_body=body if session.send == "json" else None,
            data=body if session.send == "form" else None,
            verify=self.raw_verify(config), auth_errors=False, follow_redirects=False, max_bytes=SIGN_IN_AT_MOST,
        )
        code = response.status_code
        if code >= 500:
            raise AdapterError("The service failed while signing in.", code="sign_in_error", hint="Try again in a moment.")
        if code >= 400:
            self._count_failure(state)
            raise SignInFailed()
        ticket = self._ticket_of(response, session.ticket)
        if ticket is None:
            self._count_failure(state)
            kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if 300 <= code < 400 or kind in ("text/html", "application/xhtml+xml"):
                raise AdapterError(
                    "sign-in redirects to a web page",
                    code="sign_in_web_page",
                    hint="The address answers with a page for a browser, as a proxy with its own login does. Use a key, or an address "
                         "that does not go through that proxy.",
                )
            raise AdapterError(
                "sign-in answer without a ticket",
                code="sign_in_no_ticket",
                hint="The sign-in worked but the answer does not hold the ticket where the description says it is.",
            )
        return ticket

    @staticmethod
    def _ticket_of(response: httpx.Response, where: sch.TicketAt) -> str | None:
        found: Any = None
        if where.from_ == "cookie":
            for line in response.headers.get_list("set-cookie"):
                name, _, rest = line.partition("=")
                if name.strip() == where.name:
                    found = rest.split(";", 1)[0].strip()
                    break
        else:
            try:
                found = jmespath.search(where.at or "", response.json())
            except Exception:  # noqa: BLE001 - not JSON, or an expression that fits nothing: no ticket
                found = None
        if isinstance(found, bool) or not isinstance(found, str | int) or str(found) == "":
            return None
        text = str(found)
        if len(text) > MAX_TICKET or any(ord(char) < 32 or ord(char) == 127 for char in text):
            return None
        return text

    # -- the connection test ------------------------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """GET the test path. Green on 2xx; red with the reason a person can act on (AC-9)."""
        definition = self.definition
        if self.raw_session:
            # The Test button signs in whatever a pause says (EC-4), and tells what the sign-in answer was (EC-2, EC-9).
            await self._session(config, ctx, force=True)
        response = await self.raw_request("GET", definition.test, config, ctx)
        if not 200 <= response.status_code < 300:
            raise AdapterError(
                f"The service answered the test path with HTTP {response.status_code}.",
                code="unexpected_answer",
                hint="Check the test path in the description of this connection and the address of the connection.",
            )
        if definition.test_expects == "json":
            try:
                response.json()
            except ValueError:
                raise AdapterError(
                    "The service answered with something that is no JSON.",
                    code="unexpected_answer",
                    hint="A web page instead of data usually means the address is not the one of the service's API.",
                ) from None
        return f"{self.label} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> Any:
        raise AdapterError("An own connection has no cards of its own: build a custom card on it.", code="no_widgets")

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    # -- the extras (KARTEN-4) -----------------------------------------------------------------------

    @property
    def upstream(self) -> str:
        """The GitHub project whose releases name the versions, ``owner/name``, or an empty text."""
        return sch.github_project(self.definition.github) if self.definition.github else ""

    def check_address(self, config: dict[str, Any]) -> str:
        """Where the reachability check asks: the check path, else the test path (EC-4), underneath the address."""
        base = self.raw_base(config)
        return join_path(base, self.definition.check or self.definition.test) if base else ""

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        """The version the description says where to find, or None: no place named, no JSON, nothing there (EC-1)."""
        where = self.definition.version
        if where is None:
            return None
        response = await self.raw_request("GET", where.path, config, ctx)
        try:
            found = jmespath.search(where.at, response.json())
        except Exception:  # noqa: BLE001 - not JSON, or an expression that fits nothing: the version is not said
            return None
        if isinstance(found, bool) or not isinstance(found, str | int | float):
            return None
        return version_in(str(found)[:100])
