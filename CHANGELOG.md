# Changelog

All notable changes to nexdeck. The format follows Keep a Changelog; the
project uses semantic versioning.

## 0.3.0 (2026-09-08)

Four new cards, a place to look after the files you upload, and n8n.

### New

- **Button card.** One card, one button, and nothing typed by hand: it opens a board, a page of one, or an address, picked from a list rather than spelled out in a syntax. Three looks (symbol and name, symbol alone at twice the size, name alone) and a colour if you want one. The name on that colour is black or white by luminance rather than by guess, because on half the colours somebody might pick the other choice cannot be read.
- **Picture card.** One picture, or a list of them as a slideshow with an interval, a crop and captions. Upload a file or name an address; both go in the same list, and a picture already on the server can be taken out of the media rather than uploaded again.
- **The clock has a face with hands**, drawn as one SVG with no library, and a colour for the digits or the hands. The hands are read out of the formatted time rather than off the Date: a clock set to another zone would otherwise draw one time and print another underneath it.
- **One container, one guest.** Pick a single container or virtual machine and see everything the service reports about it. Docker, Portainer, Synology's Container Manager and its Virtual Machine Manager, and Proxmox all answer. Docker's network counters, block IO and process count come along, which the container lists have been throwing away since the start.
- **n8n.** Workflows with their state and a button to publish or take one back, the most recent runs with how long each took, and a summary with the failure rate of the window it read.
- **Media.** My settings > Media lists every file you have uploaded with its size, its date and what still shows it. Deleting one names the cards and boards that would show a placeholder afterwards, and the server refuses the delete without that word rather than trusting the screen to have asked. Uploading the same file twice is one file now.
- **Icons of your own.** The icon picker takes an upload, keeps them above the two collections, and can delete one again.
- **Boards are sorted by a handle**, the way a list on a phone is, rather than by two arrow buttons. The same handle answers the arrow keys, so the list can still be sorted without a mouse.

### Fixed

- **A dragged row lost its drag.** Sorting the board list moved one place and then went dead, downwards. Not a direction: reordering moves the handle's own node in the DOM, and a moved node loses the pointer capture, so from the second step on the events went to whatever sat under the cursor.
- **Looking for an update needed the daily check to be on.** The button was hidden behind the switch, and the address behind it refused while the switch was off, so the one person most likely to want to look now and then, the administrator who deliberately keeps a daily outbound call off, was the only one who could not. The switch still decides whether nexdeck asks by itself; the button asks once, because somebody pressed it. Opening the About page with the switch off still reaches nobody, and there is a test holding that now.
- **The DSM password stopped travelling in the address.** Synology's login sent it in the query part, where it lands in DSM's own access log and in the log of every reverse proxy in between. It goes in the body now, measured against DSM 7.4.1.
- **A card drawn as a dial is measured as one.** Two cards showing the same dial had different floors under them, and nothing on screen said why.
- **The Synology volume card offers its volumes in the dial view.** It filters its rows twice, and the list the settings sheet builds its boxes from was written down after the first pass, so in the dial view the sheet said the card had nothing to pick from.
- **Tautulli leaves beta**, confirmed against a live instance.

### The test bench

- **Two guards on the numbers in the README**: the badge at the top has to count the services that exist, and every service has to stand in the adapter document. That badge said 79 when there were 78 once already, and in a browser that is invisible.
- **The end-to-end test presses a button card**, drags a board row both ways and past the end of the list, and checks what a card does while the board is being arranged. All of it in a real browser, because jsdom has no layout and every one of those tests passes there whatever the code does.

## 0.2.0 (2026-09-07)

A deep read of the whole codebase, and then the repairs it found: 146 points,
worked through in fourteen blocks. Nine of them were holes somebody could have
walked through. Every fix was held against a mutation, and the ones that could
be measured against real hardware were.

### Security

- **A board named after a number reached another board.** A board's slug may be digits, and the lookup tried the slug before the number, so whoever called their board "7" was told they owned board 7: they could read the live data of every private board there, run its actions, move its cards onto their own and delete them.
- **An action on a card could be anything.** The server took the action name and its parameters as given, so a member with the "act" level on one board could send a container name that was never on any card and stop it. An action must now have stood in the card's last delivered data, with exactly those parameters.
- **The board import read the server's environment.** `${VAR}` is meant for the operator's own files under `data/boards/`. The same code served the import that every member may call, so a member could import a board whose connection carried `${NEXDECK_SECRET_KEY}` and read it straight back out of the connection list. An import over HTTP now expands nothing and creates no connections.
- **The machine's own metadata service was in reach.** A widget option is enough to name an address, and `169.254.169.254` hands out the credentials of the host. Every outbound client is now built by one factory with one rule about where not to go, and the rule hangs on the client, not on the call.
- **Uploads could run in nexdeck's own origin.** An SVG walked past a check that named three strings. Every uploaded file is now served with a sandbox of its own, and the policy covers the addresses under `/api/` as well: the icon proxy hands out SVG it fetched from a public collection, and that is a document that can run script.
- **Secrets stayed out of the log, the export and the archive** in the places they were still getting through.
- **The second factor counts on every way in.** The OIDC return path opened a session past a configured factor; a downgraded guest could still edit; an empty `sub` counted as an identity.
- **Password guessing was capped per address, and the address is not ours.** Behind a reverse proxy the client address is whatever a header says. Attempts are now counted per account as well.
- **The DSM password stopped travelling in the address.** Synology's login sent it in the query part, where it lands in DSM's own access log and in the log of every proxy in between. It goes in the body now. Measured against DSM 7.4.1.

### New

- **A way back in when the last administrator is locked out.** `NEXDECK_RESCUE=1` prints a one-time sign-in link, good for fifteen minutes, and does not start the server. To the terminal only, never to the log: a sign-in link in a log file is a sign-in link in every backup of that log file.
- **Running nexdeck, written down.** [docs/operating.md](docs/operating.md) covers the data volume, why the key file and the database belong together, backups, restoring, updating and the Docker socket. Seventeen settings that were documented nowhere are in the README, and a guard keeps that table in step with the code.
- **A board can be arranged without a mouse.** Arrow keys move the focused card, Shift resizes it, all three form factors follow, and the same save path runs as after a drag. Until now a board could be arranged with a mouse and by no other means.
- **While editing, the whole card is the handle.** A card whose face is a link or a strip of bars had nothing to take hold of but the padding at its rim.
- **A card is measured as what it is drawn as.** A card switched to a dial was still held to the floor of the view it declares, so two cards showing the same dial had different minimum sizes.
- **Old records are cleaned up on a schedule**, uploads nobody references are swept, and every limit has a number behind it that can be set.

### Fixed

- **A card could fall silent for good.** An unreadable secret, an adapter this build no longer has, or any unexpected failure ended the widget's refresh task, and the dead task was still held, so the error was never even printed: a blank card and an empty log.
- **A card that does not know a number says so.** Missing values were drawn as zero, which reads as "measured and fine". A card with nothing to divide by now says it does not know, and 54 places that computed a percentage got the same rule.
- **A board never belongs to nobody.** Deleting a user left their boards ownerless; the delete now asks what should become of them and either hands them over or removes them.
- **An import reads before it deletes.** Replacing a board used to throw the pages away and then look at the file.
- **A connection's number no longer haunts the cards that named it.** SQLite hands out deleted row numbers again, so a new connection inherited the cards of the old one.
- **A stale board layout is refused rather than silently overwritten** when two browsers arrange the same board.
- **A `/api/` address that does not exist answers JSON**, not the whole dashboard page with HTTP 200.
- **The interface can be read without guessing.** Six colour tokens were below the contrast the text on them needs, in both the dark and the light mode; dialogs held the focus for the first time; the phone reaches a board's pages, and the edit bar fits on it.

### Faster

- **The response cache forgets again**, has a ceiling, and three adapters stopped writing keys that could never be hit. A board with a Plex history card grew by a few hundred megabytes a day.
- **Home Assistant costs one query, not one per event.**
- **A board's sparklines are a sparkline again**: the history call handed out every point of twenty-four hours, of which the browser keeps eight percent.
- **A widget tick no longer repaints the whole board.**
- **Less goes over the wire**: answers are compressed, the service worker no longer precaches 1.45 MB of alphabets and a video library nobody has asked for yet.

### The test bench

- **Playwright measures the built frontend behind FastAPI**, which is what the image ships. The dev server sets no Content-Security-Policy, so everything the real policy blocks passes in front of it and fails behind it, silently.
- **Coverage is measured** on the run that happens anyway: 82.1% backend, 33.1% frontend, both with a floor that CI holds.
- **Three guards had no floor** and would have passed on an empty scan. One of them was looking for a pattern that no longer existed.

## 0.1.0 (2026-09-06)

### New

- **Live boards.** The server collects every service once and pushes changes to every open browser over Server-Sent Events. Sparklines from 24 hours of condensed history.
- **79 integrations.** Docker, Proxmox, Proxmox Backup Server, Portainer, Coolify, Synology DSM, Unraid, TrueNAS, Nextcloud, Syncthing, Pi-hole, AdGuard Home, Technitium, NextDNS, UniFi, MikroTik, FRITZ!Box, Traefik, Nginx Proxy Manager, OPNsense, pfSense, Tailscale, Headscale, Gluetun, authentik, Speedtest Tracker, Scrutiny, UPS through PeaNUT, Reolink, Plex, Jellyfin, Emby, Tautulli, Immich, Nexview, Seerr, Overseerr, Jellyseerr, Radarr, Sonarr, Lidarr, Readarr, Prowlarr, Bazarr, SABnzbd, NZBGet, qBittorrent, Transmission, Deluge, Home Assistant, Uptime Kuma, Beszel, Glances, Prometheus, Grafana, Gotify, ntfy, Audiobookshelf, Navidrome, Komga, Kavita, Calibre-Web, Tdarr, Unmanic, FileFlows, Maintainerr, Jellystat, Paperless-ngx, evcc, Frigate, Hacker News, YouTube, GitHub releases, share prices, Twitch, Wake-on-LAN. Plus clock, weather, RSS, JSON API, iCal, calendar, notes, bookmarks, iframe and app tiles.
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
- **Confirmed against live instances.** Plex, Jellyfin, Emby, Radarr, Sonarr, Lidarr, SABnzbd, Seerr, Synology DSM, UniFi Network, Reolink, Home Assistant, Nexview, Nginx Proxy Manager, authentik and ntfy have had every widget run against a real service and lost the beta mark; the other adapters keep it until someone confirms them.
- **Reolink cameras.** A Home Hub, an NVR or a single camera: the camera list with battery and what each one detects right now, findings (offline, low battery, storage), and one camera large as a self-renewing snapshot or as live video. The server relays the camera's HTTP-FLV stream with the session token and the browser plays it with Media Source Extensions; no transcoder, no extra service, no password in any address. H.264 streams only; a browser without Media Source Extensions falls back to snapshots. Confirmed at a Home Hub with seven cameras. Reolink devices allow only a few sessions, so nexdeck holds one per integration, logs out when it stops, and waits a minute after the device has refused a login for want of sessions.
- **Jellyfin and Emby for operators.** Findings (pending restart, failed or running tasks, scans, failed sign-ins, errors in the activity log, low disk space), users with their devices and the most played titles, read from the activity log; recently added as a poster grid, one tile per series. Neither API reports the server's own CPU or memory, so there is no load card for them.
- **Recently added with covers.** Plex shows the newest movies, series or albums as a poster grid; posters and stream thumbnails come through the server, so no service token ever appears in an image address.
- **Sign in with Plex.** The Plex integration gets its token from plex.tv through a PIN and offers the account's own server, local address first; no token to copy out of an XML page.
- **UniFi with an API key.** Network 9.0 consoles are read through the Integration API with a key from the console; no local account and no two-factor exception needed. Older controllers keep the account sign-in.
- **Fourteen more services, the ten that were missed most.** Bazarr closes the *arr chain; Overseerr and Jellyseerr stand under their own names next to Seerr; Immich counts pictures and the room they take; Traefik and Nginx Proxy Manager finally cover the reverse proxy, with the days a certificate has left; the UPS arrives through PeaNUT; OPNsense and pfSense answer for everyone who does not run Ubiquiti; Nextcloud reports users, files and free space; Scrutiny reads the state of the single disk, which is the only number that announces a failure before it happens; Tautulli brings the Plex numbers people already have; and Gotify and ntfy, which nexdeck could only write to, are now readable as well. Every one of them comes with demo data and its widgets, and every parser is proven against a recorded answer.
- **The media corner, eleven more.** Audiobookshelf and Navidrome for what is listened to, Komga, Kavita and Calibre-Web for what is read, Tdarr, Unmanic and FileFlows for what is converted in the background, Maintainerr for what the clean-up rules have collected, Jellystat for the numbers beside Jellyfin, and Frigate, the standard answer to video surveillance. Calibre-Web has no API and is read through the address of its own table view, which the card says out loud when a version moves it.
- **Network and access, seven more.** Tailscale and Headscale for the tunnel that is always up, Gluetun for the one a downloader hides behind, Technitium and NextDNS beside Pi-hole and AdGuard, MikroTik for everyone who does not run Ubiquiti, and authentik, which nexdeck could already sign people in with and can now be read the other way. Skipped for want of a documented API: WG-Easy, OpenWrt, Omada and Authelia.
- **The rest of the house, seven more.** Grafana says which alert rules are firing, Coolify what is deployed and what is building, Syncthing whether the folders are in sync, Proxmox Backup Server how full the datastores are and whether the jobs ran, Paperless-ngx what came into the inbox, the FRITZ!Box what the line is doing, and evcc where the power in the house goes. Skipped: Dockge, which speaks only over its socket, Komodo, whose state values the documentation does not spell out, and the ESPHome dashboard, whose REST endpoints are marked deprecated and undocumented in their own repository.
- **Content feeds, a corner of their own.** Hacker News, YouTube, GitHub releases, share prices and Twitch, under a new heading in the widget library. Only Twitch needs credentials, and those are an application at dev.twitch.tv rather than an account; everything else reads what those services hand out to anyone. Each one ships a ready-made set of sources, so a card says something before anything is typed, and an own list replaces it.
- **Wake-on-LAN.** One card, one button, one MAC address: the magic packet that wakes a machine, and, if it was given an address, whether the machine is answering yet. The broadcast only travels inside the network the container sits in, and the field says so, because that is what everyone gets wrong.
- **The bar reaches outside.** Ctrl+K still finds boards, cards and settings, and now hands a typed word on: to a search engine, or to a service that is already connected. A shortcut jumps straight there, so `!y cats` goes to YouTube. The targets are set once under Settings > System > Search, and the connected services can be taken over with one press.
- **A colour and a style sheet of your own.** Seven accent colours, or any colour typed in, applied to every account and both brightnesses. Underneath, a style sheet the operator writes, loaded on every page after everything nexdeck ships. It is checked before it is stored: @import would fetch a file from somewhere else, and a closed style tag would be a hole.

### Fixed

- **A board named after a number reached another board.** A board's slug may be digits, and the code that looks up the board a page or a widget belongs to tried the slug before the number. A user who called their board "7" was therefore asked about board 7 whenever the server checked who may touch a widget of it, and was told they owned it: they could read the live data of every private board, run its actions, move its cards onto their own board and delete them. The lookup by number is now its own path that never touches a slug, and a new board can no longer be called after a number.
- **The board import read the server's environment.** `${VAR}` in a connection's settings is meant for the operator's own files under `data/boards/`. The same code served `POST /api/v1/boards/import`, which every member may call, so a member could import a board whose connection carried `${NEXDECK_SECRET_KEY}` and read the value straight back out of the connection list. That key signs every session and unlocks every stored secret. An import over HTTP now expands nothing, creates no connections at all, and refuses a connection an administrator reserved.
- **An uploaded SVG could run as part of nexdeck.** The check named three strings, and `onbegin=`, `onmouseover=` and `onload =` with a space walked past all three. Uploads are served from nexdeck's own address, so a hit would have run with the session. The check is wider now, and every uploaded file is served with a sandbox of its own, so a miss is no longer a hole. Every answer the server sends, including the ones under `/api/`, now says not to guess its type.
- **Password guessing was capped per address, and the address is not ours.** Behind a reverse proxy the client address is whatever a header says, so a guesser sent a new one with each attempt. Attempts are now counted per account as well, which nobody can spoof, and signing in successfully no longer clears the counter of the address it came from.
- **The machine's own metadata service is out of reach.** A widget option is enough to name an address, and `169.254.169.254` hands out the credentials of the host. Everything else on the network stays reachable, because that is what the product is for.
- **A card could fall silent for good.** An unreadable secret or an adapter this build no longer has ended the widget's task, and because the dead task was still held its error was never even printed: a blank card and an empty log. Those two now put a readable message on the card and try again later. One connection whose secret cannot be read no longer stops every reachability check in the installation either.
- **Five open advisories in Starlette.** Among them one that poisons `request.url.path` and walks past path-based checks. FastAPI 0.121 capped Starlette below the fixed version, so both were lifted. Every pinned dependency, 51 Python and 615 npm packages, now has nothing open against it, and `backend/tools/audit_deps.py` checks that in one run.

### Faster

- **The response cache forgets again.** Nothing ever removed an entry, and three adapters put the current second into the address they asked for, so every fetch wrote a key that would never be looked up. A board with a Plex history card grew by a few hundred megabytes a day. Entries now expire out of the cache, the cache has a ceiling, and those three questions are rounded to their own cache window so the cache can actually hit.
- **Home Assistant costs one query, not one per event.** The listener's docstring promised "at most once per second each" and there was no throttle at all: every state change opened a database session on the event loop and loaded every widget of the integration. A house with a few hundred entities does that dozens of times a second. The map from entity to card is now read once, and a card is refreshed at most once a second whatever the house does.
- **The log follower writes in batches and stops when nobody looks.** One transaction per line, on the event loop, for as long as the container talks. And the function that stops a follower existed from the start with nobody calling it, so a log card opened once kept its stream until the server restarted.
- **A board's sparklines are a sparkline again.** The history call handed out every point of twenty-four hours for every metric, about a megabyte and a half on a full board, of which the browser keeps eight percent. It is thinned to what a sparkline can draw, and the call no longer fires one extra query per card to ask whether it has a check.
- **A widget tick no longer repaints the whole board.** The board and the kiosk page subscribed to the entire live store, so any update anywhere re-rendered every card, once or twice a second, forever on a wall display. Both now subscribe only to the parts they use, and the grid's three layouts are no longer rebuilt on every tick.
- **Two icons that answered 404 on every single board load.** The bookmarks card shipped with `book` and `activity`, which are drawn symbols and not logos any collection has. A drawn symbol is now drawn instead of fetched, whether or not it carries the prefix.
- **New cards are named in the language they were added in.** Picking "Fehlende Untertitel" in the library used to produce a card titled "Missing subtitles": the title is stored text, and only the English word reached the server. The service keeps its own name, and the rule against a doubled word still reads the English pair, so "UniFi Network" does not become "UniFi Network Netzwerk".
- **Profile pictures.** Every account can upload one under My settings > Profile; it stands in the bar, in the account menu and in the list of users. PNG, JPEG, GIF or WebP up to 2 MB, checked by its first bytes and never by its name. A new picture replaces the old file, deleting the account deletes it, and only signed-in browsers may fetch one.
- **The same bar on every page.** Unread notices, dark and light as two segments, the language, and the account behind its picture: one set of tools, in the board bar and on every other page. Dark and light say which of the two is on instead of showing what a click would do, and the language can be switched without going into the settings.
- **A mail server for the installation.** System > Mail server holds one SMTP server that nexdeck itself uses, with a test message that goes out before anyone depends on it. Notification channels keep their own servers; this one is for what has to leave the house before a sign-in, a forgotten password first of all. The password is stored encrypted and never travels back to the browser.
- **An address in every profile.** My settings > Profile takes an e-mail address, unique across accounts, so a password reset can end at exactly one of them. Nothing else is sent to it.
- **Administrators set passwords.** A password button on every account in System > Users, no old password needed; every session of that account ends with it. The way back in when someone has locked himself out.
- **Notifications rebuilt.** One row of services with their logos, the ways you have set up as tiles below, and the one you are working on opened underneath with a step-by-step guide beside the fields. A service can hold as many ways as you like. Saving and sending a test are one button, because a test says nothing about fields nobody kept. Channel fields and event names are translated by their English wording like the adapters, and a guard keeps a new one from slipping through in English.
- **Boards can be deleted** where they are listed, with a confirmation that names how many cards go with them. Every board opens to show its pages with the number of cards on each, and a page can be deleted there; a board keeps its last page.
- **Everyone's list holds their own boards.** An administrator may open every board in the house, which used to mean his list and his menu filled up with everybody else's. Now he sees what belongs to him and what was shared with him, and a switch above the list shows all of them when he actually wants that.
- **A tick decides what stands in the menu.** Boards without it keep their place in the list and their address; the menu at the top holds the ones worth switching to. The board being looked at is always in it, so it can still say where you are.
- **Connections can be locked for users.** A tick in the connection's settings, and only administrators build cards on it. Users neither see it in their list nor pick it in the library; what the administrator has already built with it keeps running on every board he shared.
- **The board list says whose board it is.** An administrator holds every board at the owner level, so the list used to label a colleague's board as his own. Now the owner's name stands next to the name, and the badge says "Administrator" where that is the reason he may act.
- **A guest with no board can still get out.** The "no board yet" screen had no bar and therefore no account menu: whoever landed there could not even sign out. It sits in the frame now, and it says what a guest is waiting for.
- **An About page.** What this installation is (version, boards, cards, connections), where the project lives (source, releases, issues, website, licence), the update check with a "check now" beside the answer it produced, and the thanks: the dashboards that came first, the icon collections, Open-Meteo, the notification services, and every library nexdeck stands on with its licence. Names and logos of the services belong to their projects, and the page says so.
- **Own settings apart from the system.** What belongs to a person (profile, boards, notification channels, API tokens) lives under My settings; what belongs to the installation (integrations, users, instance) lives under System, reached from the account menu. The connections stay readable for every signed-in account, because they answer the first question when a card turns red; changing them stays with the administrator, and the list of users is his alone. Old addresses under `/settings` still lead to the right page.
