"""Calagopus: the game servers of an account, whether they run, and what they use.

A new panel in Rust that keeps Pterodactyl's eggs and Wings, not a fork of it, so the cards and the buttons are
Pterodactyl's and the answers are not: ``/api/client`` itself does not exist, the servers are under ``/servers`` in
``servers.data`` without ``attributes``, and a server is named by its ``uuid``.

The usage is asked once per node, not once per server: the panel reads a whole node for either, and
``/servers/{id}/resources`` answers 409 for a server that is installing, moving or restoring. An answer holds only the
servers the key may see, unless the account is an administrator of the panel.

``limits.memory`` is the limit as it was set, in MiB. ``memory_limit_bytes`` is not read: Wings adds to it (a server limited
to 256 MiB reported 294).

Measured on 31.10.2026 against a fresh all-in-one panel 1.2.7 with small test servers: reading, the states, start and stop,
and the refusals. Not against a panel in use, with a second node or with a real game.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import AdapterError, Context, Field, path_segment
from .pterodactyl import PARALLEL, PterodactylAdapter

#: 100 is the most a page may hold. ``other`` is named by the API; false keeps an administrator to their own servers.
SERVERS = {"page": 1, "per_page": 100, "other": "false"}


class CalagopusAdapter(PterodactylAdapter):
    kind = "calagopus"
    label = "Calagopus"
    category = "hosts"
    description = "The game servers of a Calagopus account: which run, how much they use, and buttons to start and stop them."
    icon = "calagopus"
    docs_url = "https://calagopus.com/docs/panel/features/dashboard/api-keys"
    beta = False
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key_hint = "Check the URL; it is the address of the panel, and the key has to come from Account > API Keys."
    power_field = "action"
    power_hint = "The key needs control.start and control.stop, and the account has to be allowed to control this server."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://panel.example.com",
              help="The address of the panel."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A key from Account > API Keys. It sees the servers of that account."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In the panel open API Keys in your account and create a key. Calagopus shows it once.",
        "The key needs servers.read, and control.start and control.stop if the buttons should work.",
    )

    async def _servers(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """Each server of the account in the form of a Pterodactyl one; ``state`` is None where nothing can be said or done."""
        listed = await self._get(config, ctx, "/servers", SERVERS)
        servers = [one for one in ((listed or {}).get("servers") or {}).get("data") or [] if isinstance(one, dict)]
        nodes = {str(one.get("node_uuid")) for one in servers if one.get("node_uuid") and not one.get("is_suspended")}
        gate = asyncio.Semaphore(PARALLEL)

        async def usage_on(node: str) -> dict[str, Any]:
            try:
                async with gate:
                    answer = await self._get(config, ctx, f"/servers/nodes/{path_segment(node, 'The node')}/resources")
            except AdapterError as error:
                if error.code == "bad_param":
                    raise
                return {}
            return (answer or {}).get("resources") or {}

        usage: dict[str, Any] = {}
        for found in await asyncio.gather(*(usage_on(node) for node in sorted(nodes))):
            usage.update(found)

        def as_read(server: dict[str, Any]) -> dict[str, Any]:
            identifier = server.get("uuid")
            if server.get("is_suspended"):
                return {**server, "identifier": identifier, "state": "suspended", "resources": {}}
            resources = usage.get(str(identifier)) or {}
            # The panel refuses every signal to these (409), so they are no more "offline" than a server it cannot read.
            busy = server.get("status") or server.get("is_transferring")
            return {**server, "identifier": identifier, "state": None if busy else str(resources.get("state") or "") or None, "resources": resources}

        return [as_read(server) for server in servers]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        listed = await self._get(config, ctx, "/servers", {**SERVERS, "per_page": 1}, cache=0)
        page = (listed or {}).get("servers") or {}
        return f"Calagopus answers, {page.get('total') if page.get('total') is not None else len(page.get('data') or [])} server(s)."


ADAPTER = CalagopusAdapter()
