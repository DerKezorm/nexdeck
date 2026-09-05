"""Emby: the same API family as Jellyfin, a different token header and its own activity log names."""

from __future__ import annotations

from .base import Field
from .jellyfin import JellyfinAdapter


class EmbyAdapter(JellyfinAdapter):
    kind = "emby"
    label = "Emby"
    description = "Active streams, library size and what was added last, with covers."
    icon = "emby"
    docs_url = "https://github.com/MediaBrowser/Emby/wiki"
    token_header = "X-Emby-Token"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://emby:8096"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > Advanced > API Keys"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    PLAYBACK_TYPES = ("playback.start",)
    SIGNIN_FAILED = "user.authenticationfailed"


ADAPTER = EmbyAdapter()
