"""Where each service publishes its releases (``services/versions.py``).

Kept apart and free of imports, so the adapters can name it in their options.
"""

#: The GitHub project of each kind whose releases name its versions.
#:
#: ⚠️ Only projects that publish GitHub releases with the version the service
#: reports, each one's latest release looked at on 23.10.2026. A wrong entry
#: here says "newer version out" forever, which is worse than saying nothing.
#: Readarr is not here: its project is archived and has no release left.
#: Those added on 28.10.2026 were looked at the same way. Not here on purpose: Jenkins (its latest release is the weekly one, an LTS
#: install would be behind forever), InfluxDB (latest is 3.x, version 2 is still run), Wiki.js (latest is a 3.0 beta, the adapter
#: speaks 2), openHAB (latest is a milestone), xTeVe (stale, and Threadfin numbers differently), Keycloak (a service account is not
#: told the version), Moonraker (its latest release is v0.1.0), pyLoad (v0.4.x names no version), and the services that name
#: no version or live off GitHub.
UPSTREAM: dict[str, str] = {
    "adguard": "AdguardTeam/AdGuardHome",
    "alertmanager": "prometheus/alertmanager",
    "anchor": "ZhFahim/anchor",
    "aria2": "aria2/aria2",
    "authentik": "goauthentik/authentik",
    "autobrr": "autobrr/autobrr",
    "bazarr": "morpheus65535/bazarr",
    "bookstack": "BookStackApp/BookStack",
    "changedetection": "dgtlmoon/changedetection.io",
    "dashdot": "MauriceNino/dashdot",
    "dawarich": "Freika/dawarich",
    "docker": "moby/moby",
    "duplicati": "duplicati/duplicati",
    "esphome": "esphome/esphome",
    "evcc": "evcc-io/evcc",
    "firefly": "firefly-iii/firefly-iii",
    "gitea": "go-gitea/gitea",
    "gotify": "gotify/server",
    "grafana": "grafana/grafana",
    "grocy": "grocy/grocy",
    "homeassistant": "home-assistant/core",
    "homebox": "sysadminsmedia/homebox",
    "homebridge": "homebridge/homebridge",
    "immich": "immich-app/immich",
    "jackett": "Jackett/Jackett",
    "jellyfin": "jellyfin/jellyfin",
    # Jellyseerr went into Seerr; the old project only points there.
    "jellyseerr": "seerr-team/seerr",
    "kimai": "kimai/kimai",
    "kodi": "xbmc/xbmc",
    "komodo": "moghtech/komodo",
    "kubernetes": "kubernetes/kubernetes",
    "lemmy": "LemmyNet/lemmy",
    "lidarr": "Lidarr/Lidarr",
    "linkding": "sissbruecker/linkding",
    "linkwarden": "linkwarden/linkwarden",
    "lubelogger": "hargata/lubelog",
    "mastodon": "mastodon/mastodon",
    "mealie": "mealie-recipes/mealie",
    "meilisearch": "meilisearch/meilisearch",
    "memos": "usememos/memos",
    "myspeed": "gnmyt/MySpeed",
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
    "nodered": "node-red/node-red",
    "octoprint": "OctoPrint/OctoPrint",
    "ollama": "ollama/ollama",
    "ombi": "Ombi-app/Ombi",
    "openwebui": "open-webui/open-webui",
    "overseerr": "sct/overseerr",
    "owncast": "owncast/owncast",
    "peertube": "Chocobozzz/PeerTube",
    "pihole": "pi-hole/pi-hole",
    "pocketid": "pocket-id/pocket-id",
    "prowlarr": "Prowlarr/Prowlarr",
    "radarr": "Radarr/Radarr",
    "rclone": "rclone/rclone",
    "romm": "rommapp/romm",
    "rtorrent": "rakshasa/rtorrent",
    "seerr": "seerr-team/seerr",
    "semaphore": "semaphoreui/semaphore",
    "sftpgo": "drakkan/sftpgo",
    "slskd": "slskd/slskd",
    "sonarr": "Sonarr/Sonarr",
    "spoolman": "Donkie/Spoolman",
    "stalwart": "stalwartlabs/stalwart",
    "stash": "stashapp/stash",
    "synapse": "element-hq/synapse",
    "syncthing": "syncthing/syncthing",
    "syncthingrelay": "syncthing/syncthing",
    "tasmota": "arendst/Tasmota",
    "traccar": "traccar/traccar",
    "traefik": "traefik/traefik",
    "trilium": "TriliumNext/Trilium",
    "tubearchivist": "tubearchivist/tubearchivist",
    "vikunja": "go-vikunja/vikunja",
    "wallos": "ellite/Wallos",
    "wazuh": "wazuh/wazuh",
    "wgeasy": "wg-easy/wg-easy",
    "wger": "wger-project/wger",
    "woodpecker": "woodpecker-ci/woodpecker",
    "wud": "getwud/wud",
    "zerobyte": "nicotsx/zerobyte",
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
