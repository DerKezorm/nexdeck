"""Gitea. Everything it shares with Forgejo lives in ``forge_base``."""

from __future__ import annotations

from .forge_base import ForgeAdapter


class GiteaAdapter(ForgeAdapter):
    kind = "gitea"
    label = "Gitea"
    product = "Gitea"
    description = "Open issues, pull requests and the latest Actions jobs of your own Git server."
    icon = "gitea"
    docs_url = "https://docs.gitea.com/api/"


ADAPTER = GiteaAdapter()
