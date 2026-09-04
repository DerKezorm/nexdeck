# Changelog

All notable changes to nexdeck. The format follows Keep a Changelog; the
project uses semantic versioning.

## 0.1.0 (unreleased)

### New

- **Live boards.** The server collects every service once and pushes changes to every open browser over Server-Sent Events. Sparklines from 24 hours of condensed history.
- **30 integrations.** Docker, Proxmox, Portainer, Synology DSM, Unraid, TrueNAS, Pi-hole, AdGuard Home, UniFi, Speedtest Tracker, Plex, Jellyfin, Emby, Nexview, Seerr, Radarr, Sonarr, Lidarr, Readarr, Prowlarr, SABnzbd, NZBGet, qBittorrent, Transmission, Deluge, Home Assistant, Uptime Kuma, Beszel, Glances, Prometheus. Plus clock, weather, RSS, JSON API, iCal, calendar, notes, bookmarks, iframe and app tiles.
- **Actions on the cards.** Restart containers, start VMs, pause downloads, approve requests, toggle Home Assistant entities. Destructive actions ask once; every action is logged.
- **Three screens.** Desktop, phone as an installable app with a bottom bar, and wall displays through kiosk links with page cycling and night dimming.
- **Users and sharing.** Administrators, users and guests; boards shared per user or per role with view, edit or act.
- **Reachability checks** for app tiles with uptime bars and outage notifications after a threshold.
- **Notifications** through Telegram, e-mail, Web Push, ntfy, Gotify, Discord, Slack and Apprise.
- **Boards as files.** Export and import as YAML; files in `data/boards/` provision boards; Docker labels `nexdeck.*` and `homepage.*` create tiles.
- **OpenID Connect** sign-in next to local accounts, personal API tokens, English and German interface.
