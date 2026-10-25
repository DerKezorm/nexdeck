"""One turn with the provider: the conversation so far in, an answer or tool calls out.

nexdeck keeps a conversation in a shape of its own (``user``, ``assistant``
with its ``calls``, ``tool`` with its ``results``) and translates it for the
provider on every turn. That way a conversation survives a change of provider
under System; what one provider answered is also kept as it came (``raw``)
and goes back to that provider unchanged, thinking blocks included.

⚠️ Claude goes through the official SDK, everything else through the
OpenAI form over HTTP, which every local runner speaks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexdeck.assistant")

#: Long enough for a few tool calls and an answer; the turn is not streamed.
MAX_TOKENS = 16000
TIMEOUT = 120.0
#: Models that decline in categories, with the server-side fallback that routes a declined turn on.
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
#: Models that take ``output_config.effort``; older ones refuse the field.
EFFORT_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5", "claude-opus-4-7", "claude-opus-4-8")
#: Block types that go back to Claude as they came; anything else (a fallback marker) stays out.
KEPT_BLOCKS = ("text", "thinking", "redacted_thinking", "tool_use")
#: Where the SDK sends Claude's turns; ``None`` is Anthropic itself. Tests point it at a server of their own.
ANTHROPIC_BASE_URL: str | None = None


class AssistantError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Turn:
    text: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)
    raw: list[Any] | None = None
    #: ``end``, ``tools`` or ``refusal``.
    stop: str = "end"
    tokens_in: int = 0
    tokens_out: int = 0


# -- Claude -----------------------------------------------------------------------------


def to_anthropic(transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in transcript:
        if entry["role"] == "user":
            messages.append({"role": "user", "content": entry["text"]})
        elif entry["role"] == "assistant":
            raw = entry.get("raw") if entry.get("provider") == "anthropic" else None
            content = [block for block in raw or [] if isinstance(block, dict) and block.get("type") in KEPT_BLOCKS]
            if not content:
                if entry.get("text"):
                    content.append({"type": "text", "text": entry["text"]})
                content += [{"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["input"]} for call in entry.get("calls") or []]
            messages.append({"role": "assistant", "content": content or [{"type": "text", "text": "…"}]})
        elif entry["role"] == "tool":
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": result["id"], "content": result["content"], "is_error": bool(result.get("is_error"))}
                for result in entry["results"]
            ]})
    return messages


async def anthropic_turn(settings: dict[str, Any], key: str, system: str, transcript: list[dict[str, Any]],
                         tools: list[dict[str, Any]]) -> Turn:
    import anthropic

    model = settings["model"]
    extra: dict[str, Any] = {"cache_control": {"type": "ephemeral"}}
    if model.startswith(EFFORT_PREFIXES):
        # A chat that looks things up: medium is enough and says so in fewer tokens.
        extra["output_config"] = {"effort": "medium"}
    betas: list[str] = []
    if model in FALLBACK_MODELS:
        betas.append("server-side-fallback-2026-07-01")
        extra["fallbacks"] = "default"
    client = anthropic.AsyncAnthropic(api_key=key, timeout=TIMEOUT, max_retries=2, base_url=ANTHROPIC_BASE_URL)
    try:
        response = await client.beta.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=[{"type": "text", "text": system}],
            messages=to_anthropic(transcript), extra_body=extra, **({"betas": betas} if betas else {}), **({"tools": tools} if tools else {}),
        )
    except anthropic.AuthenticationError:
        raise AssistantError("auth", "Anthropic refused the key.") from None
    except anthropic.PermissionDeniedError:
        raise AssistantError("auth", "The key may not use this model.") from None
    except anthropic.NotFoundError:
        raise AssistantError("model", f"Anthropic does not know the model {model!r}.") from None
    except anthropic.RateLimitError:
        raise AssistantError("rate_limited", "Anthropic is busy or the account's limit is reached. Try again in a minute.") from None
    except anthropic.APIStatusError as error:
        raise AssistantError("provider", f"Anthropic answered with HTTP {error.status_code}.") from None
    except anthropic.APIConnectionError:
        raise AssistantError("unreachable", "Anthropic could not be reached.") from None
    finally:
        await client.close()
    blocks = list(response.content)
    turn = Turn(
        text="\n\n".join(block.text for block in blocks if block.type == "text").strip(),
        calls=[{"id": block.id, "name": block.name, "input": dict(block.input or {})} for block in blocks if block.type == "tool_use"],
        raw=[block.model_dump(mode="json", exclude_none=True) for block in blocks],
        tokens_in=int(getattr(response.usage, "input_tokens", 0) or 0),
        tokens_out=int(getattr(response.usage, "output_tokens", 0) or 0),
    )
    turn.stop = "refusal" if response.stop_reason == "refusal" else "tools" if turn.calls else "end"
    return turn


# -- the OpenAI form ----------------------------------------------------------------------


def to_openai(system: str, transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for entry in transcript:
        if entry["role"] == "user":
            messages.append({"role": "user", "content": entry["text"]})
        elif entry["role"] == "assistant":
            message: dict[str, Any] = {"role": "assistant", "content": entry.get("text") or None}
            if entry.get("calls"):
                message["tool_calls"] = [
                    {"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["input"])}}
                    for call in entry["calls"]
                ]
            messages.append(message)
        elif entry["role"] == "tool":
            messages += [{"role": "tool", "tool_call_id": result["id"], "content": result["content"]} for result in entry["results"]]
    return messages


async def openai_turn(settings: dict[str, Any], key: str, system: str, transcript: list[dict[str, Any]],
                      tools: list[dict[str, Any]]) -> Turn:
    import httpx

    from ...adapters.base import outbound_client

    body: dict[str, Any] = {"model": settings["model"], "messages": to_openai(system, transcript)}
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"]}}
                         for tool in tools]
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with outbound_client(timeout=TIMEOUT) as client:
            response = await client.post(f"{settings['base_url'].rstrip('/')}/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as error:
        raise AssistantError("unreachable", f"The service could not be reached ({error.__class__.__name__}).") from None
    if response.status_code in (401, 403):
        raise AssistantError("auth", "The service refused the key.")
    if response.status_code == 404:
        raise AssistantError("model", "The service does not know this address or model.")
    if response.status_code >= 400:
        raise AssistantError("provider", f"The service answered with HTTP {response.status_code}.")
    try:
        answer = response.json()
        choice = answer["choices"][0]
        message = choice.get("message") or {}
    except (ValueError, KeyError, IndexError, TypeError):
        raise AssistantError("provider", "The service sent an answer in a form nexdeck does not read.") from None
    calls = []
    for number, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError:
            arguments = {}
        calls.append({"id": str(call.get("id") or f"call_{number}"), "name": str(function.get("name") or ""), "input": arguments if isinstance(arguments, dict) else {}})
    usage = answer.get("usage") or {}
    turn = Turn(text=str(message.get("content") or "").strip(), calls=calls,
                tokens_in=int(usage.get("prompt_tokens") or 0), tokens_out=int(usage.get("completion_tokens") or 0))
    turn.stop = "refusal" if choice.get("finish_reason") == "content_filter" else "tools" if calls else "end"
    return turn


async def turn(settings: dict[str, Any], key: str, system: str, transcript: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Turn:
    if settings["provider"] == "anthropic":
        return await anthropic_turn(settings, key, system, transcript, tools)
    if settings["provider"] == "openai":
        return await openai_turn(settings, key, system, transcript, tools)
    raise AssistantError("off", "The assistant is switched off.")
