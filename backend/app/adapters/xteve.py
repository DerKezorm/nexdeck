"""xTeVe (and Threadfin, which kept its API): the IPTV proxy for Plex, Jellyfin and Emby.

Measured on 27.10.2026 against alturismo/xteve (xTeVe 2.2.0, API 1.1.0) as a
fresh container with no playlist: the status, the three update commands, an
unknown command and a request with the API switched off.

⚠️ **The API is off by default** (settings key ``api``, the API switch in the
web interface under Settings). With it off every call answers **HTTP 423**
with the plain text ``Locked``. It is switched on in the web interface, not
here.

⚠️ It is ``POST /api/`` with a JSON body ``{"cmd": "status"}``; a GET answers
404 ``Not Found``. An unknown command is HTTP 200 with ``{"err": "Invalid API
command", "status": false}``, and the body decides: ``status`` is false when
it did not work, whatever the HTTP code says. ``update.m3u``,
``update.xmltv`` and ``update.xepg`` answer ``{"status": true}`` at once and
work in the background.

⚠️ A fresh xTeVe answers the status with only the version, the EPG source and
its own addresses. The counts of streams and channels (``streams.active``,
``streams.all``, ``streams.xepg``) that xTeVe's source can add to it were
**not there** on an install without a playlist; they are read when present
and have not been seen with a playlist loaded. The same goes for the API
token xTeVe wants when authentication for the API is on: not spoken to here,
so that switch has to stay off.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

COMMANDS = {
    "playlists": ("update.m3u", "Playlists are updated."),
    "guide": ("update.xmltv", "The guide is updated."),
    "mapping": ("update.xepg", "The channels are mapped again."),
}


class XteveAdapter(Adapter):
    kind = "xteve"
    label = "xTeVe"
    category = "media"
    description = "Whether xTeVe or Threadfin runs, its version and guide source, and buttons to update the playlists, the guide and the channel mapping."
    icon = "xteve"
    docs_url = "https://github.com/xteve-project/xTeVe-Documentation/blob/master/en/configuration.md"
    keywords = ("threadfin", "iptv")
    #: Measured against xTeVe 2.2.0 in a container without a playlist; counts and the API token never seen.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://xteve:34400",
              help="The web interface of xTeVe, port 34400. Its API has to be switched on in the settings."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="xTeVe status",
            description="Whether xTeVe answers, its version, the guide source, the streams and channels it knows, and update buttons.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("streams",),
        ),
    )

    async def _call(self, config: dict[str, Any], ctx: Context, command: str) -> dict[str, Any]:
        response = await ctx.request("POST", f"{base_url(config)}/api/", json_body={"cmd": command},
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code == 423:
            raise AdapterError("xTeVe has its API switched off.", code="api_off",
                               hint="Switch the API on in the web interface of xTeVe under Settings. Leave the API token off: it is not supported.")
        if response.status_code in (401, 403):
            raise AuthFailed("xTeVe asked for a sign-in the adapter cannot give.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way xTeVe does.", code="not_xteve",
                               hint="Use the address of xTeVe's web interface, usually port 34400.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("xTeVe did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than xTeVe.") from error
        if not isinstance(answer, dict) or "status" not in answer:
            raise AdapterError("This address answers, but not the way xTeVe does.", code="not_xteve")
        if answer.get("status") is False:
            raise AdapterError(str(answer.get("err") or "xTeVe refused the command."), code="xteve_refused")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer = await self._call(config, ctx, "status")
        version = str(answer.get("version.xteve") or "")
        return f"xTeVe {version} answers." if version else "xTeVe answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self.status_card(await self._call(config, ctx, "status"), base_url(config))

    @staticmethod
    def status_card(answer: dict[str, Any], link: str | None = None) -> WidgetData:
        secondary: list[dict[str, Any]] = []
        if answer.get("version.xteve"):
            secondary.append({"label": "Version", "value": str(answer["version.xteve"])})
        if answer.get("epg.source"):
            secondary.append({"label": "Guide source", "value": str(answer["epg.source"])})
        metrics: dict[str, float] = {}
        for key, label in (("streams.active", "Active streams"), ("streams.all", "Streams"), ("streams.xepg", "Channels")):
            if isinstance(answer.get(key), int | float):
                secondary.append({"label": label, "value": int(answer[key])})
        if isinstance(answer.get("streams.active"), int | float):
            metrics["streams"] = float(answer["streams.active"])
        return WidgetData(
            primary={"label": "xTeVe", "value": "Running"},
            secondary=secondary,
            metrics=metrics,
            actions=[Action(id=key, label=label, icon="refresh-cw", confirm=True) for key, label in (
                ("playlists", "Update the playlists"), ("guide", "Update the guide"), ("mapping", "Map the channels again"))],
            link=link,
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in COMMANDS:
            raise AdapterError("Unknown action.", code="no_such_action")
        command, message = COMMANDS[action_id]
        await self._call(config, ctx, command)
        return message

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        return self.status_card({"status": True, "version.xteve": "2.2.0", "epg.source": "XEPG", "streams.active": round(fake.walk("xteve-active", tick, 0, 4)),
                                 "streams.all": 3120, "streams.xepg": 164})


ADAPTER: Adapter = XteveAdapter()
