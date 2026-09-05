"""Jellyseerr: Overseerr for Jellyfin and Emby households.

Same API, same widgets; it stands on its own so it can be found by the name it
is installed under. See ``overseerr`` for why.
"""

from __future__ import annotations

from .base import Field
from .overseerr import OverseerrAdapter


class JellyseerrAdapter(OverseerrAdapter):
    kind = "jellyseerr"
    label = "Jellyseerr"
    icon = "jellyseerr"
    description = "Open requests with approve as an action, from a Jellyseerr instance."
    docs_url = "https://docs.jellyseerr.dev/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://jellyseerr:5055"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > General > API Key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )


ADAPTER = JellyseerrAdapter()
