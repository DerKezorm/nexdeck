"""Overseerr and Jellyseerr, the two that Seerr grew out of.

Seerr is the merger of February 2026, and it answers the same API. The
installed base is still running the ancestors, though, and somebody looking
for "Overseerr" in the catalogue does not find it under a name they have never
heard. So they stand here by their own name, with their own logo, and inherit
everything else.
"""

from __future__ import annotations

from typing import Any

from .base import Context, Field
from .seerr import SeerrAdapter


class OverseerrAdapter(SeerrAdapter):
    kind = "overseerr"
    label = "Overseerr"
    icon = "overseerr"
    description = "Open requests with approve as an action, from an Overseerr instance."
    docs_url = "https://api-docs.overseerr.dev/"
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://overseerr:5055"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > General > API Key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/status", cache=0)
        return f"{self.label} {status.get('version', '?')} answers."


ADAPTER = OverseerrAdapter()
