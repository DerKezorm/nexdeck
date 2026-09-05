"""The adapter contract.

An adapter knows one service: which connection fields it needs, which widgets
it offers, how to fetch their data, which actions it can run and what fake
data it produces in demo mode. Everything an adapter returns is a
``WidgetData``: a small, service-independent shape that the frontend renders
with a handful of renderers. That is what makes thirty integrations
maintainable by one person.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel
from pydantic import Field as PydanticField

logger = logging.getLogger("nexdeck.adapters")

FieldType = Literal["text", "password", "url", "number", "bool", "select", "textarea", "timezone"]
Status = Literal["ok", "warn", "bad", "unknown"]


@dataclass(frozen=True)
class Field:
    """One configuration field of an integration or a widget."""

    name: str
    label: str
    type: FieldType = "text"
    required: bool = False
    secret: bool = False
    default: Any = None
    help: str = ""
    placeholder: str = ""
    options: tuple[tuple[str, str], ...] = ()
    #: A frontend helper drawn under the field, such as ``plex-signin``.
    helper: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "secret": self.secret,
            "default": self.default,
            "help": self.help,
            "placeholder": self.placeholder,
            "options": [{"value": v, "label": lab} for v, lab in self.options],
            "helper": self.helper,
        }


@dataclass(frozen=True)
class WidgetType:
    """One widget an adapter offers."""

    kind: str
    label: str
    description: str
    #: Which frontend renderer draws the data.
    renderer: str
    default_size: tuple[int, int] = (3, 2)
    min_size: tuple[int, int] = (2, 1)
    options: tuple[Field, ...] = ()
    refresh_seconds: int = 30
    #: Metric names this widget records for sparklines.
    metrics: tuple[str, ...] = ()
    #: True for widgets that need no server refresh: clocks, notes, bookmarks,
    #: embedded pages and app tiles draw themselves from their options.
    client_only: bool = False

    def to_dict(self, adapter_kind: str) -> dict[str, Any]:
        return {
            "kind": f"{adapter_kind}.{self.kind}",
            "label": self.label,
            "description": self.description,
            "renderer": self.renderer,
            "default_size": list(self.default_size),
            "min_size": list(self.min_size),
            "options": [f.to_dict() for f in self.options],
            "refresh_seconds": self.refresh_seconds,
            "metrics": list(self.metrics),
            "client_only": self.client_only,
        }


class Action(BaseModel):
    id: str
    label: str
    icon: str = ""
    confirm: bool = False
    danger: bool = False
    params: dict[str, Any] = PydanticField(default_factory=dict)


class WidgetData(BaseModel):
    """What every widget fetch returns."""

    status: Status = "ok"
    #: ``{"label": str, "value": number|str, "unit": str, "format": str}``
    primary: dict[str, Any] | None = None
    secondary: list[dict[str, Any]] = PydanticField(default_factory=list)
    items: list[dict[str, Any]] = PydanticField(default_factory=list)
    actions: list[Action] = PydanticField(default_factory=list)
    #: Numeric samples recorded for history and sparklines.
    metrics: dict[str, float] = PydanticField(default_factory=dict)
    link: str | None = None
    meta: dict[str, Any] = PydanticField(default_factory=dict)
    error: str | None = None
    updated_at: float = PydanticField(default_factory=time.time)


class AdapterError(Exception):
    """A readable failure: what went wrong, and what the operator can do."""

    def __init__(self, message: str, *, code: str = "adapter_error", hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


class AuthFailed(AdapterError):
    def __init__(self, message: str = "The service rejected the credentials.") -> None:
        super().__init__(message, code="auth_failed", hint="Check the API key or the password.")


class Unreachable(AdapterError):
    def __init__(self, message: str = "The service could not be reached.") -> None:
        super().__init__(message, code="unreachable", hint="Check the URL and the network.")


class Context:
    """What an adapter gets besides its configuration.

    ``fetch_json`` caches GET responses for a few seconds per integration, so
    ten widgets on the same Radarr cause one request, not ten.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        integration_id: int | None = None,
        widget_id: int | None = None,
        cache: dict[str, Any] | None = None,
        resolve_integration: Any = None,
    ) -> None:
        self.client = client
        self.integration_id = integration_id
        self.widget_id = widget_id
        #: Per-integration memory for adapters (auth tickets, cookies, indexes).
        self.cache: dict[str, Any] = cache if cache is not None else {}
        #: ``async (integration_id) -> (adapter, config, Context)`` for widgets
        #: that combine several integrations, such as the calendar.
        self.resolve_integration = resolve_integration

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        content: bytes | None = None,
        timeout: float = 15.0,
        verify: bool = True,
        auth: tuple[str, str] | None = None,
        cache_seconds: float = 0,
    ) -> httpx.Response:
        key = ""
        if method.upper() == "GET" and cache_seconds > 0:
            key = "resp:" + hashlib.sha1(
                json.dumps([url, params, headers], sort_keys=True, default=str).encode()
            ).hexdigest()
            hit = self.cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        try:
            if verify:
                response = await self.client.request(
                    method, url, headers=headers, params=params, json=json_body,
                    data=data, content=content, timeout=timeout, auth=auth,
                )
            else:
                async with httpx.AsyncClient(verify=False, follow_redirects=True) as insecure:
                    response = await insecure.request(
                        method, url, headers=headers, params=params, json=json_body,
                        data=data, content=content, timeout=timeout, auth=auth,
                    )
        except httpx.TimeoutException as error:
            raise Unreachable("The service did not answer in time.") from error
        except httpx.HTTPError as error:
            raise Unreachable(f"The service could not be reached: {error.__class__.__name__}.") from error
        if response.status_code in (401, 403):
            raise AuthFailed()
        if key:
            self.cache[key] = (time.monotonic() + cache_seconds, response)
        return response

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
        verify: bool = True,
        auth: tuple[str, str] | None = None,
        cache_seconds: float = 5,
    ) -> Any:
        response = await self.request(
            "GET", url, headers=headers, params=params, timeout=timeout, verify=verify,
            auth=auth, cache_seconds=cache_seconds,
        )
        if response.status_code >= 400:
            raise AdapterError(
                f"The service answered with HTTP {response.status_code}.",
                code="http_error",
                hint="Check the URL; the address may point at the wrong service.",
            )
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError(
                "The service did not answer with JSON.",
                code="not_json",
                hint="The URL probably points at a login page or a reverse proxy.",
            ) from error


def base_url(config: dict[str, Any], key: str = "url") -> str:
    """The configured URL without a trailing slash."""
    return str(config.get(key, "")).strip().rstrip("/")


@dataclass
class MediaSource:
    """An image or a live stream the server fetches from a service on a widget's behalf."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    #: How long the server may keep an image; 0 means every request goes to the service.
    cache_seconds: float = 3600
    media_type: str = ""


class Adapter:
    """Base class. Subclasses set the class attributes and override the hooks."""

    kind: str = ""
    label: str = ""
    category: str = "other"
    description: str = ""
    #: Icon name in dashboard-icons, e.g. ``radarr``.
    icon: str = ""
    #: True until someone confirms the adapter against a live instance.
    beta: bool = True
    docs_url: str = ""
    fields: tuple[Field, ...] = ()
    widgets: tuple[WidgetType, ...] = ()
    #: Adapters without a connection (clock, notes) set this to False.
    needs_integration: bool = True

    def widget(self, kind: str) -> WidgetType:
        for w in self.widgets:
            if w.kind == kind:
                return w
        raise KeyError(kind)

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    def image_headers(self, config: dict[str, Any]) -> dict[str, str]:
        """Headers for fetching a service's images (posters, thumbnails) through the server.

        Adapters put an image behind ``proxy:/path`` instead of a full address,
        so a token never travels into an image URL in the browser.
        """
        return {}

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """Where an image behind ``proxy:/path`` really comes from.

        The default fetches the path from the service with ``image_headers`` and
        lets the server keep it for an hour. Adapters whose images need a
        session token or must stay fresh (camera snapshots) override this.
        """
        return MediaSource(url=f"{base_url(config)}{path}", headers=self.image_headers(config))

    async def stream_source(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> MediaSource:
        """Where a widget's live video comes from; only camera adapters have one."""
        raise AdapterError("This widget has no live stream.", code="no_stream")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "beta": self.beta,
            "docs_url": self.docs_url,
            "needs_integration": self.needs_integration,
            "fields": [f.to_dict() for f in self.fields],
            "widgets": [w.to_dict(self.kind) for w in self.widgets],
        }

    # -- hooks ---------------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """Check the connection; return a short human-readable result."""
        raise NotImplementedError

    async def fetch(
        self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context
    ) -> WidgetData:
        raise NotImplementedError

    async def action(
        self,
        widget_kind: str,
        action_id: str,
        params: dict[str, Any],
        config: dict[str, Any],
        options: dict[str, Any],
        ctx: Context,
    ) -> str:
        raise AdapterError("This widget has no actions.", code="no_such_action")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        raise NotImplementedError

    async def close(self, config: dict[str, Any], ctx: Context) -> None:
        """Hand back a session the adapter holds at the service; called when the server stops.

        Devices that count sessions (Reolink) fill up otherwise, one restart at a time.
        """
        return None

    def secret_field_names(self) -> set[str]:
        return {f.name for f in self.fields if f.secret}


# ---------------------------------------------------------------------------
# Small helpers shared by adapters
# ---------------------------------------------------------------------------


def human_bytes(value: float | int | None) -> str:
    if value is None:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def human_rate(bytes_per_second: float | None) -> str:
    if bytes_per_second is None:
        return "?"
    return human_bytes(bytes_per_second) + "/s"


def percent(part: float | None, whole: float | None) -> float:
    if not whole or part is None:
        return 0.0
    return round(100.0 * float(part) / float(whole), 1)


def status_from_percent(value: float, warn: float = 80, bad: float = 95) -> Status:
    if value >= bad:
        return "bad"
    if value >= warn:
        return "warn"
    return "ok"


def duration_short(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


@dataclass
class Series:
    """A tiny helper for adapters that build several list items."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, **item: Any) -> None:
        self.items.append(item)
