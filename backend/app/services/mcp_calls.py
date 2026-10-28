"""The tools an AI may call over MCP, and what each call does.

The reading tools are the assistant's own (``services/assistant/tools.py``),
run with the key's account and boards. Two are only here: ``press_button``,
the one tool that changes something, and ``request_status``, the way to learn
what came of a press that waited for approval. ``propose_action`` stays in the
chat: over MCP there is nobody in front of the screen to put a button before.

A press checks everything a press in the browser checks: the right ``act`` on
the card's board (cut to the key's boards), and that the card offers exactly
this button with these parameters right now (``Collector._refuse_unless_offered``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..adapters.base import Action, AdapterError
from ..models import Board, McpRequest, User, Widget
from . import chronicle, impact, mcp
from .assistant import tools
from .mcp import Caller, McpError
from .state import live

logger = logging.getLogger("nexdeck.mcp")

_ASSISTANT = {tool["name"]: tool for tool in tools.TOOLS}


def _borrowed(name: str, group: str, *, admin_only: bool = False, description: str = "") -> dict[str, Any]:
    tool = _ASSISTANT[name]
    return {"name": name, "group": group, "level": "read", "admin_only": admin_only,
            "description": description or tool["description"], "inputSchema": tool["input_schema"]}


TOOLS: list[dict[str, Any]] = [
    _borrowed("needs_attention", "read", description=(
        "What needs a look right now on the boards this key may see: cards that are yellow or red with their reason and "
        "since when, services whose reachability check fails, and the unread warnings of the account's bell (left out "
        "for a key limited to some boards). Start here for questions like 'is anything wrong'.")),
    _borrowed("find_cards", "read"),
    _borrowed("card_details", "read"),
    _borrowed("chronicle", "read"),
    _borrowed("metric_history", "read"),
    _borrowed("diagnosis", "admin", admin_only=True),
    _borrowed("container_log", "admin", admin_only=True, description=(
        "The last lines of one container's log, from a card of Docker, Portainer or a Synology that lists containers. "
        "Secrets in the lines are masked as well as can be done.")),
    {"name": "press_button", "group": "act", "level": "act", "admin_only": False, "destructive": True,
     "description": (
         "Press a button of a card: only an action card_details lists for that card right now, with exactly the "
         "parameters listed there. Depending on the key's rights it runs at once or waits for the account to allow it "
         "in nexdeck; a dangerous button always waits. A waiting press answers with a request number for "
         "request_status."),
     "inputSchema": {"type": "object", "properties": {
         "card_id": {"type": "integer"}, "action": {"type": "string", "description": "The action id from card_details."},
         "params": {"type": "object", "description": "The parameters card_details lists for that button."},
     }, "required": ["card_id", "action"], "additionalProperties": False}},
    {"name": "request_status", "group": "read", "level": "read", "admin_only": False, "always": True,
     "description": (
         "How a press stands that waits for approval (press_button gave its number): waiting, approved (with what "
         "the button answered), declined, expired or failed (with why)."),
     "inputSchema": {"type": "object", "properties": {"request": {"type": "integer", "minimum": 1}},
                     "required": ["request"], "additionalProperties": False}},
]
BY_NAME = {tool["name"]: tool for tool in TOOLS}
#: Always there for a key, whatever its rights say, and never blocked: the way to learn what came of a request.
UNBLOCKABLE = ("request_status",)

#: How deep arguments may nest, and how long a text in them may be.
MAX_DEPTH = 10
MAX_TEXT = 2000


class ToolError(Exception):
    pass


def listed(caller: Caller) -> list[dict[str, Any]]:
    """``tools/list`` for this key: only what exists for it, with the hints a client shows its user."""
    return [{"name": tool["name"], "description": tool["description"], "inputSchema": tool["inputSchema"],
             "annotations": {"readOnlyHint": tool["group"] != "act", "destructiveHint": bool(tool.get("destructive"))}}
            for tool in TOOLS if caller.right(tool) is not None]


def _shape_problem(value: Any, depth: int = 0) -> str | None:
    if depth > MAX_DEPTH:
        return f"The arguments are nested deeper than {MAX_DEPTH} levels."
    if isinstance(value, str):
        if len(value) > MAX_TEXT:
            return f"A text in the arguments holds at most {MAX_TEXT} characters."
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return "The arguments hold text that is not valid Unicode."
    elif isinstance(value, bool):
        return None
    elif isinstance(value, int):
        if not -(2**63) <= value < 2**63:
            return "A number in the arguments is too large."
    elif isinstance(value, dict):
        for key, inner in value.items():
            problem = _shape_problem(key, depth + 1) or _shape_problem(inner, depth + 1)
            if problem:
                return problem
    elif isinstance(value, list):
        for inner in value:
            problem = _shape_problem(inner, depth + 1)
            if problem:
                return problem
    return None


def check(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """What is wrong with the arguments by the tool's schema, before anything runs or waits."""
    problem = _shape_problem(args)
    if problem:
        return problem
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if args.get(key) is None:
            return f"'{key}' is missing."
    kinds = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            if schema.get("additionalProperties") is False:
                return f"There is no argument '{key}'."
            continue
        if value is None and key not in schema.get("required", []):
            continue
        wanted = kinds.get(spec.get("type", ""))
        if wanted is not None and (not isinstance(value, wanted) or (wanted is int and isinstance(value, bool))):
            return f"'{key}' must be of type {spec['type']}."
        if "enum" in spec and value not in spec["enum"]:
            return f"'{key}' must be one of {', '.join(map(str, spec['enum']))}."
        if wanted is int and value < spec.get("minimum", value):
            return f"'{key}' is out of range."
    return None


def result(value: Any, failed: bool = False) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    answer: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": failed}
    if not failed and isinstance(value, dict):
        answer["structuredContent"] = json.loads(json.dumps(value, default=str))
    return answer


def _bench(db: Session, caller: Caller) -> tools.Bench:
    user = db.get(User, caller.user_id)
    if user is None:
        raise ToolError("The key's account is gone.")
    return tools.Bench(db=db, user=user, grants=[], boards=caller.boards, mcp=True)


async def call(db: Session, caller: Caller, name: Any, args: Any) -> dict[str, Any]:
    """One ``tools/call``: its result, never an exception. Logged without the arguments."""
    tool = BY_NAME.get(name) if isinstance(name, str) else None
    right = caller.right(tool) if tool is not None else None
    if tool is None or right is None:
        # Denied, above the key's level, for administrators only or blocked: as unknown as a tool that does not exist.
        logger.info("MCP tool %r refused for key %s: no such tool for it.", str(name)[:60], caller.key_id)
        return result(f"No tool called {str(name)[:60]!r}.", failed=True)
    if not isinstance(args, dict):
        return result("'arguments' must be an object.", failed=True)
    problem = check(tool["inputSchema"], args)
    if problem:
        return result(problem, failed=True)
    try:
        bench = _bench(db, caller)
        if name == "press_button":
            answer = await press_button(db, bench, caller, right, args)
        elif name == "request_status":
            answer = request_status(db, caller, args)
        else:
            text, failed = await tools.run(bench, name, args)
            logger.info("MCP tool %s called by key %s%s.", name, caller.key_id, " (failed)" if failed else "")
            return result(json.loads(text), failed=failed)
    except ToolError as failure:
        logger.info("MCP tool %s called by key %s: %s", name, caller.key_id, failure)
        return result({"error": str(failure)}, failed=True)
    except McpError as failure:
        logger.info("MCP tool %s called by key %s: %s", name, caller.key_id, failure.code)
        return result({"error": failure.message}, failed=True)
    return result(answer)


# -- press_button -------------------------------------------------------------------------------


def _button(data: Any, action_id: str, params: dict[str, Any]) -> tuple[str, bool, str] | None:
    """Label, danger and row of the button a press means; the blanks a button leaves may differ."""
    if data is None:
        return None

    def fits(entry: dict[str, Any]) -> bool:
        if entry.get("id") != action_id:
            return False
        blanks = {str(one.get("name") if isinstance(one, dict) else getattr(one, "name", "")) for one in entry.get("asks") or []}
        fixed = {key: value for key, value in dict(entry.get("params") or {}).items() if key not in blanks}
        return fixed == {key: value for key, value in params.items() if key not in blanks}

    for action in data.actions:
        entry = action.model_dump()
        if fits(entry):
            return str(entry.get("label") or action_id), bool(entry.get("danger")), ""
    for item in data.items:
        for entry in (item.get("actions") or []) if isinstance(item, dict) else []:
            entry = entry.model_dump() if isinstance(entry, Action) else entry
            if isinstance(entry, dict) and fits(entry):
                return str(entry.get("label") or action_id), bool(entry.get("danger")), str(item.get("title") or "")
    return None


def _target(bench: tools.Bench, card_id: int) -> tuple[Widget, Board]:
    """The card a press means, if the key may press its buttons."""
    place = tools._places(bench).get(card_id)
    if place is None:
        # A card on a board the key may not see answers exactly like one that does not exist.
        raise ToolError("No such card.")
    widget, _page, board = place
    if tools.board_right(bench, board) not in ("act", "owner"):
        raise ToolError("The account may look at this card, but not press its buttons.")
    return widget, board


def _offered(widget_id: int, action_id: str, params: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, bool, str]]:
    from .collector import collector

    try:
        given = collector._refuse_unless_offered(widget_id, action_id, params)
    except AdapterError as failure:
        raise ToolError("The card does not offer that button with these parameters right now. Look at card_details again.") from failure
    # A button that cannot be told apart counts as dangerous: it asks.
    return given, _button(live.get(widget_id), action_id, params) or (action_id, True, "")


async def _press(widget: Widget, board: Board, caller: Caller, action_id: str, params: dict[str, Any], *, approved_by: str = "") -> str:
    """Press the button now, logged as a press in the browser is, and written in the chronicle."""
    from .collector import collector
    from .notify import emit

    actor = caller.actor + (f", approved by {approved_by}" if approved_by else "")
    label = (_button(live.get(widget.id), action_id, params) or (action_id, True, ""))[0]
    title = widget.title or widget.kind
    try:
        message = await collector.run_action(widget.id, action_id, params, actor=actor[:120], user_id=caller.user_id)
    except AdapterError as failure:
        emit("action_failed", f"{action_id} on {title} failed", failure.message, level="warn", user_ids=[caller.user_id],
             integration_id=widget.integration_id)
        logger.warning("Action %r on %r failed for %s: %s", action_id, title, actor, failure.message)
        raise ToolError(failure.message) from failure
    logger.info("Action %r ran on %r by %s: %s", action_id, title, actor, message)
    chronicle.record("mcp_call", level="info", widget_id=widget.id, integration_id=widget.integration_id, board_id=board.id,
                     user_id=caller.user_id, name=title, after=label, detail=f"{label} on {title} by {actor}")
    emit("action_done", f"{action_id} on {title}", message, user_ids=[caller.user_id], integration_id=widget.integration_id)
    return message


async def press_button(db: Session, bench: tools.Bench, caller: Caller, right: str, args: dict[str, Any]) -> dict[str, Any]:
    from .notify import emit

    action_id = str(args["action"])
    params = dict(args.get("params") or {})
    widget, board = _target(bench, int(args["card_id"]))
    given, (label, danger, row) = _offered(widget.id, action_id, params)
    title = widget.title or widget.kind
    if right == "allow" and not danger:
        message = await _press(widget, board, caller, action_id, given)
        return {"status": "done", "message": message}
    # Asked first: the right says so, or the button is dangerous, which asks even where pressing is allowed.
    facts = await impact.facts(widget.id, action_id, given)
    shown = canonical_args(widget.id, action_id, params)
    request = mcp.add_request(db, caller, "press_button", shown, widget_id=widget.id, card=title, board=board.name,
                              action=action_id, label=label, danger=danger, impact=facts)
    what = f"{label} ({row})" if row else label
    emit("mcp_request", f"{caller.key_name} asks to press {what} on {title}", f"Board {board.name}. Allow or decline in nexdeck.",
         level="warn" if danger else "info", link=f"/mcp/requests/{request.id}", user_ids=[caller.user_id])
    return {"request": request.id, "status": "waiting", "expires_at": request.expires_at.isoformat(),
            "note": (f"Waiting for approval in nexdeck, request {request.id}. It runs out in {mcp.REQUEST_MINUTES} minutes. "
                     f"Ask request_status with request {request.id} to learn what came of it.")}


def canonical_args(card_id: int, action_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """The arguments of a press as they are kept: exactly what was asked, nothing the card filled in."""
    return {"card_id": card_id, "action": action_id, "params": params}


def request_status(db: Session, caller: Caller, args: dict[str, Any]) -> dict[str, Any]:
    mcp.expire(db)
    row = db.get(McpRequest, int(args["request"]))
    # Only the key that asked learns about its request; any other number does not exist.
    if row is None or row.key_id != caller.key_id:
        raise ToolError("No such request.")
    answer: dict[str, Any] = {"request": row.id, "status": row.status, "expires_at": row.expires_at.isoformat()}
    if row.result is not None:
        answer["result"] = row.result
    return answer


# -- approval -----------------------------------------------------------------------------------


async def approve(db: Session, user: User, row: McpRequest) -> None:
    """Press what a request asked for, with the rights as they stand now. The request is claimed already."""
    name = user.display_name or user.username
    try:
        args = mcp.arguments_of(row)
        caller = mcp.caller_of_key(db, row.key_id)
        tool = BY_NAME.get(row.tool)
        # ⚠️ Checked again now, not when it was asked: in ten minutes the key may
        # have been withdrawn, the account lost its right on the board, MCP
        # switched off, the tool blocked, or the card stopped offering the button.
        if caller is None or tool is None or caller.right(tool) is None:
            raise ToolError("the key may not use this tool any more.")
        bench = _bench(db, caller)
        widget, board = _target(bench, int(args["card_id"]))
        given, _found = _offered(widget.id, str(args["action"]), dict(args.get("params") or {}))
    except McpError as failure:
        mcp.finish(db, row, "failed", {"error": failure.message})
        logger.info("MCP request %s could not run: %s", row.id, failure.code)
        return
    except ToolError as failure:
        mcp.finish(db, row, "failed", {"error": f"This is no longer possible: {failure}"})
        logger.info("MCP request %s is no longer possible: %s", row.id, failure)
        return
    try:
        message = await _press(widget, board, caller, str(args["action"]), given, approved_by=name)
    except ToolError as failure:
        mcp.finish(db, row, "failed", {"error": str(failure)})
        return
    mcp.finish(db, row, "approved", {"message": message})
    logger.info("MCP request %s approved by %s and run.", row.id, user.username)
