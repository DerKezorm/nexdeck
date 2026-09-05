# Changelog

All notable changes to nexdeck. The format follows Keep a Changelog; the
project uses semantic versioning.

## 0.1.0 (unreleased)

### New

- **Live boards.** The server collects every service once and pushes changes to every open browser over Server-Sent Events. Sparklines from 24 hours of condensed history.
- **31 integrations.** Docker, Proxmox, Portainer, Synology DSM, Unraid, TrueNAS, Pi-hole, AdGuard Home, UniFi, Reolink, Speedtest Tracker, Plex, Jellyfin, Emby, Nexview, Seerr, Radarr, Sonarr, Lidarr, Readarr, Prowlarr, SABnzbd, NZBGet, qBittorrent, Transmission, Deluge, Home Assistant, Uptime Kuma, Beszel, Glances, Prometheus. Plus clock, weather, RSS, JSON API, iCal, calendar, notes, bookmarks, iframe and app tiles.
- **Actions on the cards.** Restart containers, start VMs, pause downloads, approve requests, toggle Home Assistant entities. Destructive actions ask once; every action is logged.
- **Three screens.** Desktop, phone as an installable app with a bottom bar, and wall displays through kiosk links with page cycling and night dimming.
- **Users and sharing.** Administrators, users and guests; boards shared per user or per role with view, edit or act.
- **Reachability checks** for app tiles with uptime bars and outage notifications after a threshold.
- **Notifications** through Telegram, e-mail, Web Push, ntfy, Gotify, Discord, Slack and Apprise.
- **Boards as files.** Export and import as YAML; files in `data/boards/` provision boards; Docker labels `nexdeck.*` and `homepage.*` create tiles.
- **OpenID Connect** sign-in next to local accounts, personal API tokens, English and German interface.
- **Live preview while editing.** Widget settings and the board look show every change on the card before it is saved; closing the sheet discards it.
- **Free placement.** Cards stay where they are dropped, gaps allowed; a board option pushes them up instead.
- **Plex for operators.** Findings (updates, remote access, scans, load), server load with history, users and their devices, and the most watched titles of the week or month.
- **App tiles follow an integration.** Pick a connected service in a tile's settings: name and icon come as suggestions, the link and the reachability check take the service's address on every view. Change the address once, in the integration, and every tile follows.
- **Confirmed against live instances.** Plex, Jellyfin, Emby, Radarr, Sonarr, Lidarr, SABnzbd, Seerr, Synology DSM, UniFi Network, Reolink, Home Assistant and Nexview have had every widget run against a real service and lost the beta mark; the other adapters keep it until someone confirms them.
- **Reolink cameras.** A Home Hub, an NVR or a single camera: the camera list with battery and what each one detects right now, findings (offline, low battery, storage), and one camera large as a self-renewing snapshot or as live video. The server relays the camera's HTTP-FLV stream with the session token and the browser plays it with Media Source Extensions; no transcoder, no extra service, no password in any address. H.264 streams only; a browser without Media Source Extensions falls back to snapshots. Confirmed at a Home Hub with seven cameras. Reolink devices allow only a few sessions, so nexdeck holds one per integration, logs out when it stops, and waits a minute after the device has refused a login for want of sessions.
- **Jellyfin and Emby for operators.** Findings (pending restart, failed or running tasks, scans, failed sign-ins, errors in the activity log, low disk space), users with their devices and the most played titles, read from the activity log; recently added as a poster grid, one tile per series. Neither API reports the server's own CPU or memory, so there is no load card for them.
- **Recently added with covers.** Plex shows the newest movies, series or albums as a poster grid; posters and stream thumbnails come through the server, so no service token ever appears in an image address.
- **Sign in with Plex.** The Plex integration gets its token from plex.tv through a PIN and offers the account's own server, local address first; no token to copy out of an XML page.
- **UniFi with an API key.** Network 9.0 consoles are read through the Integration API with a key from the console; no local account and no two-factor exception needed. Older controllers keep the account sign-in.
