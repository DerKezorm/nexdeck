"""Ombi: the requests people made, and approve or decline them.

Measured on 27.10.2026 against lscr.io/linuxserver/ombi (Ombi 4.53.10,
.NET 8, SQLite) with an administrator, a user who may request movies and
shows, and five movie requests and one show request in different states.
Albums were read from Ombi's own OpenAPI file; there was no Lidarr to ask for
one, so that part is unmeasured.

⚠️ **Two of the cards' own addresses answer without any key.**
``/api/v1/Request/count`` and ``/api/v1/Status`` return 200 to a request
with no key and to one with a wrong key. A test that stopped at them would
call every key good. The request lists (``/api/v2/Requests/...``) answer
**401** with ``Invalid API Key`` (or nothing at all, without the header), and
the connection test asks one of them.

⚠️ A refusal is **HTTP 200** with ``"isError": true`` and the reason in
``errorMessage``: approving a request that does not exist came back
``{"result": false, "isError": true, "errorMessage": "Request does not exist"}``.
Reading the status code alone reports an approval that never happened.

⚠️ The request lists carry the person who asked, whole, and that object
holds their e-mail address and an ``userAccessToken``. Nothing of it is read
but the display name (``requestedUser.alias``, else ``userName``).

⚠️ For a show, the row of the pending list is one **child request** (one
ask by one person for some seasons), and its ``id`` is what approve and deny
take; ``parentRequestId`` is the show. Approving the show's own id answers
``Child Request does not exist``.

⚠️ Denying a movie answered "Request successfully deleted" and the count
went from denied 0 to 1: the words are Ombi's, the request is still there,
denied.

The API key is made in Ombi under Settings, Ombi Configuration, and goes in
the header ``ApiKey``. It acts as the administrator who owns it.
"""

from __future__ import annotations

from typing import Any

from .base import (
    Adapter,
    AdapterError,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

#: The three kinds of request, the address each is listed and decided under, and what a row says it is.
KINDS = {
    "movie": ("movie", "movie", "Movie"),
    "tv": ("tv", "tv", "Show"),
    "album": ("album", "music", "Album"),
}


def _who(request: dict[str, Any]) -> str:
    user = request.get("requestedUser")
    user = user if isinstance(user, dict) else {}
    return str(request.get("requestedByAlias") or user.get("alias") or user.get("userName") or "?")


def _title(kind: str, request: dict[str, Any]) -> str:
    title = str(request.get("title") or "?")
    if kind == "album" and request.get("artistName"):
        return f"{request['artistName']}: {title}"
    year = str(request.get("releaseDate") or "")[:4]
    if kind == "movie" and year.isdigit() and year != "0001":
        return f"{title} ({year})"
    return title


class OmbiAdapter(Adapter):
    kind = "ombi"
    label = "Ombi"
    category = "media"
    description = "Pending requests for movies, shows and albums with approve and decline, and the counts."
    icon = "ombi"
    docs_url = "https://docs.ombi.app/"
    #: Measured against Ombi 4.53.10 in a container; albums only from the OpenAPI file.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://ombi:3579"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Settings > Ombi Configuration > API key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="requests",
            label="Requests",
            description="Pending requests with who asked, and approve or decline.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("pending",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="counts",
            label="Request counts",
            description="Pending, approved, available and declined, in one number.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("pending",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"ApiKey": str(config.get("api_key") or "")}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", headers=self._headers(config),
                                     verify=not config.get("insecure"), cache_seconds=cache)
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Ombi does.", code="not_ombi",
                               hint="Use the address of Ombi itself, usually port 3579.")
        if response.status_code >= 400:
            raise AdapterError(f"Ombi answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Ombi did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Ombi.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/api/v1/Status/info", cache=0)
        # The count and the status answer anybody; a list is the first thing that asks for the key.
        await self._get(config, ctx, "/api/v2/Requests/movie/pending/1/0/requestedDate/desc", cache=0)
        return f"Ombi {version} answers." if isinstance(version, str) and version else "Ombi answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        counts = await self._get(config, ctx, "/api/v1/Request/count", cache=30)
        if not isinstance(counts, dict):
            raise AdapterError("This address answers, but not the way Ombi does.", code="not_ombi")
        if widget_kind == "counts":
            return self.counts_card(counts, base_url(config))
        limit = max(1, min(50, int(options.get("limit") or 8)))
        found: list[tuple[str, dict[str, Any]]] = []
        for kind in KINDS:
            answer = await self._get(config, ctx, f"/api/v2/Requests/{kind}/pending/{limit}/0/requestedDate/desc", cache=30)
            found += [(kind, one) for one in (answer or {}).get("collection") or [] if isinstance(one, dict)]
        return self.requests_card(counts, found, limit, base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def counts_card(counts: dict[str, Any], link: str | None = None) -> WidgetData:
        pending = int(counts.get("pending") or 0)
        return WidgetData(
            status="warn" if pending else "ok",
            primary={"label": "Pending", "value": pending},
            secondary=[
                {"label": "Approved", "value": int(counts.get("approved") or 0)},
                {"label": "Available", "value": int(counts.get("available") or 0)},
                {"label": "Declined", "value": int(counts.get("denied") or 0)},
            ],
            metrics={"pending": float(pending)},
            link=link,
        )

    @staticmethod
    def requests_card(counts: dict[str, Any], found: list[tuple[str, dict[str, Any]]], limit: int, link: str | None = None) -> WidgetData:
        pending = int(counts.get("pending") or 0)
        # Newest first, across the three lists; ISO times sort as text.
        found = sorted(found, key=lambda one: str(one[1].get("requestedDate") or ""), reverse=True)
        items = []
        for kind, request in found[:limit]:
            identifier = request.get("id")
            if identifier is None:
                continue
            params = {"kind": kind, "id": identifier}
            items.append({
                "id": f"{kind}:{identifier}",
                "title": _title(kind, request),
                "subtitle": f"{_who(request)} · {KINDS[kind][2]}",
                "status": "warn",
                "actions": [
                    {"id": "approve", "label": "Approve", "icon": "check", "params": params},
                    {"id": "decline", "label": "Decline", "icon": "x", "confirm": True, "danger": True, "params": params},
                ],
            })
        return WidgetData(
            status="warn" if pending else "ok",
            items=items,
            secondary=[{"label": "Pending", "value": pending}],
            metrics={"pending": float(pending)},
            link=link,
            meta={"empty": "No request waits."},
        )

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A request that was not in the list a minute ago is a new one.

        ⚠️ By its kind and number, not by the count, and only when the list was
        read both times, for the reasons Seerr's card has: somebody approving
        one while somebody asks for another leaves the count as it was, and a
        card that was broken must not announce every waiting request as new.
        """
        if widget_kind != "requests" or before is None or before.error:
            return []
        seen = {str(item.get("id")) for item in before.items if item.get("id") is not None}
        if not seen:
            return []
        found = []
        for item in after.items:
            key = str(item.get("id"))
            if key in seen or item.get("id") is None:
                continue
            who = str(item.get("subtitle") or "").split(" · ")[0]
            found.append(Detected(
                event="request_new",
                title=f"{item.get('title') or 'Something'} was requested",
                body=f"Asked for by {who}." if who and who != "?" else "",
                key=f"request_new:{key}",
            ))
        return found[:5]

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("approve", "decline"):
            raise AdapterError("Unknown action.", code="no_such_action")
        kind = str(params.get("kind") or "")
        if kind not in KINDS:
            raise AdapterError("No kind of request was named.", code="missing_param")
        try:
            identifier = int(params.get("id"))
        except (TypeError, ValueError):
            raise AdapterError("No request was named.", code="missing_param") from None
        path = KINDS[kind][1]
        body: dict[str, Any] = {"id": identifier}
        if kind == "movie":
            body["is4K"] = False
        if action_id == "decline":
            body["reason"] = ""
        response = await ctx.request(
            "POST" if action_id == "approve" else "PUT", f"{base_url(config)}/api/v1/Request/{path}/{'approve' if action_id == 'approve' else 'deny'}",
            headers=self._headers(config), json_body=body, verify=not config.get("insecure"),
        )
        ctx.forget_answers()
        if response.status_code >= 400:
            raise AdapterError(f"Ombi answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
        except ValueError:
            answer = {}
        # ⚠️ A refusal is a 200 with isError set.
        if isinstance(answer, dict) and (answer.get("isError") or answer.get("result") is False):
            raise AdapterError(str(answer.get("errorMessage") or answer.get("message") or "Ombi refused the request."),
                               code="ombi_refused")
        return "Request approved." if action_id == "approve" else "Request declined."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        pending = 2 + (tick // 90) % 3
        counts = {"pending": pending, "approved": 118, "available": 104, "denied": 6}
        if widget_kind == "counts":
            return self.counts_card(counts)
        titles = [("movie", "The Quiet Harbour", "1999-03-31T00:00:00Z"), ("tv", "Northern Shore", ""), ("album", "Copper Sky", ""), ("movie", "Signal Lost", "2026-02-01T00:00:00Z")]
        found = [(kind, {"id": index + 1, "title": title, "releaseDate": released, "requestedDate": f"2026-10-2{index}T10:00:00Z",
                         "requestedByAlias": ["Alex", "Sam", "Kim", "Robin"][index],
                         **({"artistName": "Orbital Tide"} if kind == "album" else {})})
                 for index, (kind, title, released) in enumerate(titles[:pending])]
        return self.requests_card(counts, found, int(options.get("limit") or 8))


ADAPTER: Adapter = OmbiAdapter()
