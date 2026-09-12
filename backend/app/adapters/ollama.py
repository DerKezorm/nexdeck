"""Ollama: which models sit in memory right now, how much they take, and which are installed.

Measured against Ollama 0.34.0 on 11.09.2026, in a container without a GPU,
with one small model pulled, loaded and unloaded again.

⚠️ Ollama has no sign-in. A made-up bearer token got 200 like no token at
all, so its port belongs inside the network, and the adapter sends nothing
but the request. A 401 or 403 can only come from something in front of it.

⚠️ ``/api/ps`` names what is loaded, and its ``size`` is the memory in use,
not the file: a model of 258 MB on disk took 364 MB loaded, with a context
of 4096. ``size_vram`` was 0, all of it in main memory; only that case was
seen, the GPU words follow what ``ollama ps`` prints.

⚠️ There is no unload call of its own. A generate request without a prompt
and with ``keep_alive: 0`` unloads, and answers ``done_reason: "unload"``. It
answers the same for a model that was not loaded at all (200, nothing
changes). A model Ollama does not know gets 404 ``{"error": "model '...' not
found"}``.

⚠️ ``GET /`` answers the plain text "Ollama is running", not JSON; the
version is at ``/api/version``.
"""

from __future__ import annotations

from typing import Any

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
    human_bytes,
)

PROXY_REFUSED = "Something in front of Ollama refused the request. Ollama itself has no sign-in."


def _size(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _details(model: dict[str, Any]) -> dict[str, Any]:
    details = model.get("details")
    return details if isinstance(details, dict) else {}


def _name(model: dict[str, Any]) -> str:
    return str(model.get("name") or model.get("model") or "?")


def _processor(model: dict[str, Any]) -> str:
    """Where a loaded model sits, in the words ``ollama ps`` uses."""
    size = _size(model.get("size")) or 0.0
    vram = _size(model.get("size_vram")) or 0.0
    if vram <= 0:
        return "CPU"
    if vram >= size:
        return "GPU"
    return "CPU and GPU"


def _models(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise AdapterError("This address answers, but not the way Ollama does.", code="not_ollama",
                           hint="Check the URL; Ollama listens on port 11434 unless told otherwise.")
    return [one for one in payload["models"] if isinstance(one, dict)]


def _memory(loaded: list[dict[str, Any]]) -> float:
    return sum(_size(one.get("size")) or 0.0 for one in loaded)


class OllamaAdapter(Adapter):
    kind = "ollama"
    label = "Ollama"
    category = "other"
    description = "Which models are loaded and how much memory they take, and which models are installed."
    icon = "ollama"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://docs.ollama.com/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://ollama:11434"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="loaded", label="Loaded models", description="The models in memory right now, with the memory each one takes.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("memory_mb",)),
        WidgetType(kind="installed", label="Installed models",
                   description="Every model on the server with its size on disk; the loaded ones are marked.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Models", description="How many models are loaded and installed, and the memory the loaded ones take.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("loaded", "memory_mb")),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 10) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", verify=not config.get("insecure"),
                                     cache_seconds=cache, auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed(PROXY_REFUSED)
        if response.status_code >= 400:
            raise AdapterError(f"Ollama answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Ollama itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Ollama did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Ollama.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/api/version", cache=0)
        if not isinstance(version, dict) or "version" not in version:
            raise AdapterError("This address answers, but not the way Ollama does.", code="not_ollama")
        installed = _models(await self._get(config, ctx, "/api/tags", cache=0))
        return f"Ollama {version['version']} answers with {len(installed)} installed models."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        loaded = _models(await self._get(config, ctx, "/api/ps"))
        if widget_kind == "loaded":
            return self._loaded(loaded)
        installed = _models(await self._get(config, ctx, "/api/tags", cache=60))
        if widget_kind == "installed":
            return self._installed(installed, loaded, options)
        return self._summary(installed, loaded)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "unload":
            raise AdapterError("Unknown model action.", code="no_such_action")
        model = str(params.get("model") or "").strip()
        if not model:
            raise AdapterError("No model was named to unload.", code="missing_param")
        # The name travels in the body, never in the path.
        response = await ctx.request("POST", f"{base_url(config)}/api/generate", json_body={"model": model, "keep_alive": 0},
                                     verify=not config.get("insecure"), timeout=30, auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed(PROXY_REFUSED)
        if response.status_code == 404:
            raise AdapterError("Ollama has no such model any more.", code="action_failed")
        if response.status_code >= 400:
            raise AdapterError(f"Ollama answered with HTTP {response.status_code}.", code="action_failed")
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if not isinstance(answer, dict) or answer.get("done_reason") != "unload":
            raise AdapterError("Ollama answered, but did not say that it unloaded the model.", code="action_failed")
        ctx.forget_answers()
        return "Model unloaded."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _loaded(loaded: list[dict[str, Any]]) -> WidgetData:
        items = []
        for one in sorted(loaded, key=lambda model: (-(_size(model.get("size")) or 0.0), _name(model))):
            details = _details(one)
            items.append({
                "title": _name(one),
                "subtitle": " · ".join(part for part in (_processor(one), str(details.get("parameter_size") or ""),
                                                          str(details.get("quantization_level") or "")) if part),
                "status": "ok",
                "value": human_bytes(_size(one.get("size"))),
                "actions": [Action(id="unload", label="Unload", icon="power", confirm=True,
                                   params={"model": str(one.get("model") or one.get("name") or "")})],
            })
        memory = _memory(loaded)
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Memory", "value": human_bytes(memory)}],
            # A wall display has no hovering, and unloading is the one thing on this card to press.
            meta={"empty": "No model is loaded.", "actions_visible": True},
            metrics={"memory_mb": round(memory / 1024 / 1024, 1)},
        )

    @staticmethod
    def _installed(installed: list[dict[str, Any]], loaded: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        in_memory = {str(one.get("model") or one.get("name") or "") for one in loaded}
        items = []
        for one in sorted(installed, key=lambda model: _name(model).lower())[: max(1, int(options.get("limit") or 10))]:
            details = _details(one)
            on = str(one.get("model") or one.get("name") or "") in in_memory
            items.append({
                "title": _name(one),
                "subtitle": " · ".join(part for part in ("Loaded" if on else "", str(details.get("parameter_size") or ""),
                                                          str(details.get("quantization_level") or "")) if part),
                "status": "ok" if on else "unknown",
                "value": human_bytes(_size(one.get("size"))),
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "On disk", "value": human_bytes(sum(_size(one.get("size")) or 0.0 for one in installed))}],
            meta={"empty": "No models installed yet."},
        )

    @staticmethod
    def _summary(installed: list[dict[str, Any]], loaded: list[dict[str, Any]]) -> WidgetData:
        memory = _memory(loaded)
        return WidgetData(
            status="ok",
            primary={"label": "Loaded", "value": len(loaded)},
            secondary=[{"label": "Installed", "value": len(installed)}, {"label": "Memory", "value": human_bytes(memory)}],
            metrics={"loaded": float(len(loaded)), "memory_mb": round(memory / 1024 / 1024, 1)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        chat = {"name": "llama3.2:3b", "model": "llama3.2:3b", "size": 2_019_393_189,
                "details": {"family": "llama", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"}}
        embed = {"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest", "size": 274_302_450,
                 "details": {"family": "nomic-bert", "parameter_size": "137M", "quantization_level": "F16"}}
        coder = {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 4_683_087_332,
                 "details": {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}}
        installed = [chat, embed, coder]
        # The embedding model comes and goes, the way it does between two searches.
        loaded = [{**chat, "size": 3_110_000_000, "size_vram": 3_110_000_000}]
        if tick % 4 < 2:
            loaded.append({**embed, "size": 580_000_000, "size_vram": 0})
        if widget_kind == "loaded":
            return self._loaded(loaded)
        if widget_kind == "installed":
            return self._installed(installed, loaded, options)
        return self._summary(installed, loaded)


ADAPTER = OllamaAdapter()
