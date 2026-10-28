"""llama.cpp server: the model it serves, how many slots are busy and how many tokens a second it generates.

Measured against llama-server build b11913 on 27.10.2026 with SmolLM2-135M-Instruct (Q4_K_M) on a
machine with no graphics card, two slots, started with ``--metrics --slots``, once without and once
with ``--api-key``.

⚠️ ``GET /health`` is open even with an API key (``{"status": "ok"}``, 503 with ``loading model``
while the model loads). ``/props``, ``/slots`` and ``/metrics`` answer 401
``{"error": {"message": "Invalid API Key", ...}}`` without ``Authorization: Bearer <key>``.

⚠️ ``/props`` names ``model_alias`` (what the server was started with, in this test the Hugging
Face name), ``total_slots``, ``model_ftype`` (the quantisation), ``build_info`` ("b11913-7aca0d2ea")
and ``default_generation_settings.n_ctx``, which is the context **of one slot**. ``/slots`` is a
list of ``{"id", "n_ctx", "is_processing", ...}``; with an API key it carried nothing but those
and without one it also carried the sampling parameters and, for a busy slot, ``next_token``
(``n_decoded``, ``n_remain``). ``/metrics`` is the Prometheus text of the server.

⚠️ The gauge ``llamacpp:predicted_tokens_seconds`` read 0 during a generation and after it (measured
while a 1500 token completion ran: the busy slot was seen in ``/slots``, the gauge stayed 0), so
it is not used. The counters ``tokens_predicted_total`` and ``tokens_predicted_seconds_total`` are
what the speed is worked out from: between two looks, the tokens made divided by the seconds spent
making them, and the average since the start where nothing was made in between. 2092 tokens in
8.87 seconds measured on the test machine is 236 tokens a second.

⚠️ ``/slots`` is switched off by ``--no-slots`` and ``/metrics`` is off without ``--metrics``: both
then answer an error (501 or 404) and the cards say which switch is missing.
"""

from __future__ import annotations

import re
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
    measured,
)

SAMPLE = re.compile(r"^(llamacpp:[a-z_]+)(?:\{[^}]*\})?\s+(-?[0-9.eE+-]+|NaN|[+-]Inf)\s*$")
PREVIOUS = "llamacpp-tokens"


def _numbers(text: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for line in text.splitlines():
        match = SAMPLE.match(line.strip())
        if match:
            try:
                found[match.group(1).removeprefix("llamacpp:")] = float(match.group(2))
            except ValueError:
                continue
    return found


class LlamaCppAdapter(Adapter):
    kind = "llamacpp"
    label = "llama.cpp"
    category = "monitoring"
    description = "The model a llama.cpp server serves, how many of its slots are busy and how many tokens a second it makes."
    icon = "llama-cpp"
    #: Measured on 2026-10-27 against build b11913 with a 135M model, not yet an instance in use.
    beta = True
    docs_url = "https://github.com/ggml-org/llama.cpp/tree/master/tools/server"
    keywords = ("llama-server", "ggml", "llm", "gguf")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://llama:8080"),
        Field("api_key", "API key", type="password", secret=True, help="Only when the server was started with --api-key. /health works without it, everything else needs it."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="server", label="Server", description="The model, busy slots and tokens a second, yellow while every slot is busy. Needs --metrics for the speed.",
                   renderer="value", default_size=(3, 2), refresh_seconds=15, metrics=("busy", "tokens_per_second")),
        WidgetType(kind="slots", label="Slots", description="Every slot, whether it is working and how far its answer has got. Needs the server's slots endpoint (on unless --no-slots).",
                   renderer="list", default_size=(3, 2), refresh_seconds=15, metrics=("busy",)),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str] | None:
        key = str(config.get("api_key") or "").strip()
        return {"Authorization": f"Bearer {key}"} if key else None

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, optional: str = "") -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", headers=self._headers(config), verify=not config.get("insecure"),
                                     auth_errors=False, cache_seconds=5)
        if response.status_code in (401, 403):
            raise AuthFailed("llama.cpp rejected the API key." if config.get("api_key") else "llama.cpp asks for an API key.")
        if optional and response.status_code in (404, 501):
            raise AdapterError(optional, code="not_enabled", hint="Start llama-server with the switch named, or leave this card out.")
        if response.status_code >= 400:
            raise AdapterError(f"llama.cpp answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of llama-server, port 8080 by default.")
        return response

    async def _props(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        response = await self._get(config, ctx, "/props")
        try:
            props = response.json()
        except ValueError as error:
            raise AdapterError("llama.cpp did not answer with JSON.", code="not_json", hint="The URL probably points at something else than llama-server.") from error
        if not isinstance(props, dict) or "total_slots" not in props:
            raise AdapterError("This address answers, but not the way llama-server does.", code="not_llamacpp")
        return props

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        props = await self._props(config, ctx)
        build = str(props.get("build_info") or "")
        return f"llama.cpp {build} answers, {props.get('total_slots')} slots." if build else f"llama.cpp answers, {props.get('total_slots')} slots."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        # Its builds are numbers (b11913), not versions the upstream list compares.
        return None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        props = await self._props(config, ctx)
        try:
            slots = (await self._get(config, ctx, "/slots", optional="The slots endpoint is switched off (--no-slots).")).json()
        except AdapterError as error:
            if error.code != "not_enabled" or widget_kind == "slots":
                raise
            slots = None
        if widget_kind == "slots":
            return self._slots(slots)
        speed: dict[str, float] = {}
        try:
            speed = _numbers((await self._get(config, ctx, "/metrics", optional="The metrics endpoint is switched off (--metrics).")).text)
        except AdapterError as error:
            if error.code != "not_enabled":
                raise
        return self._server(props, slots, self._rate(speed, ctx.cache))

    @staticmethod
    def _rate(counters: dict[str, float], memory: dict[str, Any]) -> float | None:
        """Tokens a second since the last look; the speed it had when nothing was made in between; the average since the start at the first look."""
        made, spent = counters.get("tokens_predicted_total"), counters.get("tokens_predicted_seconds_total")
        if made is None or spent is None:
            return None
        before = memory.get(PREVIOUS)
        if isinstance(before, tuple) and spent > before[1] and made >= before[0]:
            rate: float | None = round((made - before[0]) / (spent - before[1]), 1)
        elif isinstance(before, tuple) and before[2] is not None:
            rate = before[2]
        else:
            rate = round(made / spent, 1) if spent > 0 else None
        memory[PREVIOUS] = (made, spent, rate)
        return rate

    @staticmethod
    def _server(props: dict[str, Any], slots: Any, rate: float | None) -> WidgetData:
        total = int(props.get("total_slots") or 0)
        rows = [one for one in slots if isinstance(one, dict)] if isinstance(slots, list) else None
        busy = sum(1 for one in rows if one.get("is_processing")) if rows is not None else None
        every_slot_busy = busy is not None and total > 0 and busy >= total
        secondary: list[dict[str, Any]] = []
        if busy is not None:
            secondary.append({"label": "Slots busy", "value": f"{busy} / {total}"})
        if rate is not None:
            secondary.append({"label": "Tokens a second", "value": rate})
        context = ((props.get("default_generation_settings") or {}).get("n_ctx"))
        if context:
            secondary.append({"label": "Context per slot", "value": int(context)})
        if props.get("model_ftype"):
            secondary.append({"label": "Quantisation", "value": str(props["model_ftype"])})
        name = str(props.get("model_alias") or "").rsplit("/", 1)[-1] or "?"
        return WidgetData(
            status="warn" if every_slot_busy else "ok",
            primary={"label": "Model", "value": name, "unit": ""},
            secondary=secondary,
            metrics=measured({"busy": None if busy is None else float(busy), "tokens_per_second": rate}),
        )

    @staticmethod
    def _slots(slots: Any) -> WidgetData:
        rows = []
        for one in slots if isinstance(slots, list) else []:
            if not isinstance(one, dict):
                continue
            working = bool(one.get("is_processing"))
            decoded = one.get("next_token")
            if isinstance(decoded, list) and decoded:
                decoded = decoded[0]
            made = decoded.get("n_decoded") if isinstance(decoded, dict) else None
            rows.append({"title": f"Slot {one.get('id')}", "subtitle": " · ".join(part for part in ("Working" if working else "Idle", f"{made} tokens made" if working and made else "") if part),
                         "status": "ok" if working else "unknown", "value": f"{one.get('n_ctx')} tokens" if one.get("n_ctx") else ""})
        busy = sum(1 for one in slots if isinstance(one, dict) and one.get("is_processing")) if isinstance(slots, list) else 0
        return WidgetData(status="warn" if rows and busy == len(rows) else "ok", items=rows, secondary=[{"label": "Slots busy", "value": f"{busy} / {len(rows)}"}],
                          meta={"empty": "No slots."}, metrics={"busy": float(busy)})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        working = [fake.flicker(f"llama-slot{number}", tick, 0.5) for number in range(4)]
        slots = [{"id": number, "n_ctx": 4096, "is_processing": on, "next_token": [{"n_decoded": int(fake.walk(f"ld{number}", tick, 20, 400))}]} for number, on in enumerate(working)]
        if widget_kind == "slots":
            return self._slots(slots)
        props = {"total_slots": 4, "model_alias": "example/Llama-3.2-3B-Instruct-GGUF", "model_ftype": "Q4_K - Medium", "default_generation_settings": {"n_ctx": 4096}}
        return self._server(props, slots, fake.walk("llama-tps", tick, 18, 42))


ADAPTER = LlamaCppAdapter()
