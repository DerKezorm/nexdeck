"""Forgejo. Everything it shares with Gitea lives in ``forge_base``."""

from __future__ import annotations

from .forge_base import ForgeAdapter


class ForgejoAdapter(ForgeAdapter):
    kind = "forgejo"
    label = "Forgejo"
    product = "Forgejo"
    description = "Open issues, pull requests and the latest Actions jobs of your own Forgejo."
    icon = "forgejo"
    docs_url = "https://forgejo.org/docs/latest/user/api-usage/"


ADAPTER = ForgejoAdapter()
