"""Where each service publishes its releases (``services/versions.py``).

Kept apart and free of imports, so the adapters can name it in their options.
"""

#: The GitHub project of each kind whose releases name its versions.
#:
#: ⚠️ Only projects that publish GitHub releases with the version the service
#: reports, each one's latest release looked at on 23.10.2026. A wrong entry
#: here says "newer version out" forever, which is worse than saying nothing.
#: Readarr is not here: its project is archived and has no release left.
UPSTREAM: dict[str, str] = {
    "adguard": "AdguardTeam/AdGuardHome",
    "alertmanager": "prometheus/alertmanager",
    "authentik": "goauthentik/authentik",
    "autobrr": "autobrr/autobrr",
    "bazarr": "morpheus65535/bazarr",
    "changedetection": "dgtlmoon/changedetection.io",
    "dawarich": "Freika/dawarich",
    "docker": "moby/moby",
    "duplicati": "duplicati/duplicati",
    "evcc": "evcc-io/evcc",
    "firefly": "firefly-iii/firefly-iii",
    "gitea": "go-gitea/gitea",
    "gotify": "gotify/server",
    "grafana": "grafana/grafana",
    "grocy": "grocy/grocy",
    "homeassistant": "home-assistant/core",
    "homebox": "sysadminsmedia/homebox",
    "immich": "immich-app/immich",
    "jellyfin": "jellyfin/jellyfin",
    # Jellyseerr went into Seerr; the old project only points there.
    "jellyseerr": "seerr-team/seerr",
    "kimai": "kimai/kimai",
    "komodo": "moghtech/komodo",
    "kubernetes": "kubernetes/kubernetes",
    "lidarr": "Lidarr/Lidarr",
    "linkding": "sissbruecker/linkding",
    "linkwarden": "linkwarden/linkwarden",
    "mealie": "mealie-recipes/mealie",
    "meilisearch": "meilisearch/meilisearch",
    "navidrome": "navidrome/navidrome",
    "netbox": "netbox-community/netbox",
    "netdata": "netdata/netdata",
    "nexbeat": "DerKezorm/nexbeat",
    "nexbrand": "DerKezorm/nexbrand",
    "nexcanvas": "DerKezorm/nexcanvas",
    "nexcrate": "DerKezorm/nexcrate",
    "nexdiary": "DerKezorm/nexdiary",
    "nexlore": "DerKezorm/nexlore",
    "nexpaper": "DerKezorm/nexpaper",
    "nexpulse": "DerKezorm/nexpulse",
    "nexsift": "DerKezorm/nexsift",
    "nextcloud": "nextcloud/server",
    "nextrmnl": "DerKezorm/nextrmnl",
    "nexview": "DerKezorm/nexview",
    "octoprint": "OctoPrint/OctoPrint",
    "ollama": "ollama/ollama",
    "openwebui": "open-webui/open-webui",
    "overseerr": "sct/overseerr",
    "pihole": "pi-hole/pi-hole",
    "pocketid": "pocket-id/pocket-id",
    "prowlarr": "Prowlarr/Prowlarr",
    "radarr": "Radarr/Radarr",
    "romm": "rommapp/romm",
    "rtorrent": "rakshasa/rtorrent",
    "seerr": "seerr-team/seerr",
    "semaphore": "semaphoreui/semaphore",
    "sonarr": "Sonarr/Sonarr",
    "syncthing": "syncthing/syncthing",
    "traefik": "traefik/traefik",
    "tubearchivist": "tubearchivist/tubearchivist",
    "vikunja": "go-vikunja/vikunja",
    "wallos": "ellite/Wallos",
    "wgeasy": "wg-easy/wg-easy",
    "wger": "wger-project/wger",
    "wud": "getwud/wud",
}


def repo_of(kind: str) -> str:
    """The GitHub project whose releases name the versions of a kind, or an empty text.

    The built-in kinds are listed above; an own kind (``custom:<short>``) names its project in its description, which
    the registry holds. Looked up when asked, so a description saved a moment ago counts at once.
    """
    if kind.startswith("custom:"):
        from ..adapters import REGISTRY

        return str(getattr(REGISTRY.get(kind), "upstream", "") or "")
    return UPSTREAM.get(kind, "")
