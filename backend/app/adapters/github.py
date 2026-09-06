"""GitHub: what the projects you run have released.

The releases of a public repository are readable without a key. GitHub allows
sixty requests an hour per address, which is plenty for a handful of projects
on a half-hourly card, and the card says so plainly when that runs out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

API = "https://api.github.com"

#: Ready-made sets of the projects a home server usually runs.
PRESETS = {
    "media": "jellyfin/jellyfin\nRadarr/Radarr\nSonarr/Sonarr\nsabnzbd/sabnzbd",
    "infrastructure": "home-assistant/core\nNginxProxyManager/nginx-proxy-manager\npi-hole/pi-hole\nAdguardTeam/AdGuardHome",
    "nexapps": "DerKezorm/nexdeck\nDerKezorm/nexview\nDerKezorm/nexmail",
    "": "",
}
PRESET_OPTIONS = (
    ("media", "Media and downloads"),
    ("infrastructure", "Infrastructure"),
    ("nexapps", "nexapps"),
    ("", "Own list only"),
)


class GithubAdapter(Adapter):
    kind = "github"
    label = "GitHub releases"
    category = "feeds"
    description = "The newest release of every project you watch."
    icon = "github"
    docs_url = "https://docs.github.com/en/rest/releases/releases"
    needs_integration = False
    widgets = (
        WidgetType(
            kind="releases",
            label="Releases",
            description="One line per project with its newest version and when it came.",
            renderer="feed",
            default_size=(4, 4),
            refresh_seconds=1800,
            options=(
                Field("preset", "Ready-made set", type="select", default="media", options=PRESET_OPTIONS),
                Field("repos", "Own projects", type="textarea", placeholder="owner/name",
                      help="One per line, as owner/name. Replaces the ready-made set."),
                Field("limit", "Entries", type="number", default=8),
                Field("prereleases", "Include pre-releases", type="bool", default=False),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "https://github.com/"

    @staticmethod
    def _repos(options: dict[str, Any]) -> list[str]:
        own = [line.strip().strip("/") for line in str(options.get("repos") or "").splitlines() if line.strip()]
        if own:
            return own[:10]
        preset = PRESETS.get(str(options.get("preset") or "media"), "")
        return [line for line in preset.splitlines() if line][:10]

    async def _releases(self, ctx: Context, repo: str, prereleases: bool) -> dict[str, Any] | None:
        path = f"{API}/repos/{repo}/releases" if prereleases else f"{API}/repos/{repo}/releases/latest"
        response = await ctx.request(
            "GET", path,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            params={"per_page": 1} if prereleases else None,
            cache_seconds=1800,
            timeout=20,
            # GitHub answers 403 when the hourly limit is used up.
            auth_errors=False,
        )
        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise AdapterError(
                "GitHub's hourly limit for this address is used up.",
                code="rate_limited",
                hint="Sixty requests an hour without an account; watch fewer projects or set a longer interval.",
            )
        if response.status_code == 404:
            # A project without a release is not a fault; it simply has none.
            return None
        if response.status_code >= 400:
            raise AdapterError(f"GitHub answered with HTTP {response.status_code}.", code="http_error")
        payload = response.json()
        if isinstance(payload, list):
            return payload[0] if payload else None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _stamp(text: str) -> int | None:
        try:
            return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        release = await self._releases(ctx, "DerKezorm/nexdeck", False)
        return f"GitHub answers; nexdeck is at {release.get('tag_name')}." if release else "GitHub answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        repos = self._repos(options)
        if not repos:
            raise AdapterError("No project is set.", code="missing_repo")
        prereleases = bool(options.get("prereleases"))
        entries: list[dict[str, Any]] = []
        failures: list[str] = []
        for repo in repos:
            try:
                release = await self._releases(ctx, repo, prereleases)
            except AdapterError as error:
                failures.append(f"{repo}: {error.message}")
                continue
            if not release:
                continue
            name = str(release.get("tag_name") or release.get("name") or "?")
            notes = str(release.get("body") or "").strip().splitlines()
            entries.append({
                "title": f"{repo.split('/')[-1]} {name}",
                "url": release.get("html_url") or f"https://github.com/{repo}/releases",
                "source": repo + (" · pre-release" if release.get("prerelease") else ""),
                "published": self._stamp(release.get("published_at") or release.get("created_at") or ""),
                "summary": (notes[0][:280] if notes else ""),
                "image": "",
            })
        entries.sort(key=lambda entry: entry["published"] or 0, reverse=True)
        return WidgetData(
            status="ok" if entries else ("bad" if failures else "warn"),
            items=entries[: max(1, min(20, int(options.get("limit") or 8)))],
            meta={"style": "list", "failures": failures},
            error=("; ".join(failures) if failures and not entries else None),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        releases = [
            ("jellyfin 10.11.12", "jellyfin/jellyfin", "Fixes trickplay on ARM devices."),
            ("Radarr 6.3.1", "Radarr/Radarr", "Improved import matching for collections."),
            ("core 2026.9.1", "home-assistant/core", "New energy dashboard cards."),
            ("Sonarr 4.0.20", "Sonarr/Sonarr", "Season pack handling reworked."),
            ("pi-hole 6.4.4", "pi-hole/pi-hole", "Faster gravity rebuilds."),
            ("nexdeck 0.1.0", "DerKezorm/nexdeck", "First release."),
        ]
        start = tick // 150
        items = []
        for index in range(min(len(releases), max(1, min(20, int(options.get("limit") or 8))))):
            title, repo, note = releases[(start + index) % len(releases)]
            items.append({
                "title": title,
                "url": "https://github.com/",
                "source": repo,
                "published": 1788600000 - index * 86400 - tick,
                "summary": note,
                "image": "",
            })
        return WidgetData(items=items, meta={"style": "list", "failures": []})


ADAPTER = GithubAdapter()
