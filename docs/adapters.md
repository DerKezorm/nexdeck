# Integrations and widgets

An **integration** is one configured connection to a service: an address and
credentials. A **widget** shows one view of it on a board. Many widgets can
share one integration; the server asks the service once per widget interval
and caches identical requests for a few seconds.

Every adapter lives in one file under `backend/app/adapters/`. It declares
its connection fields, its widgets, and how to fetch, act and fake data.
The frontend never knows a service: every widget returns a `WidgetData`
that one of twenty-one renderers draws.

## Adapters in 0.12.0

| Adapter | Widgets | Actions | Credentials |
|---|---|---|---|
| Docker | containers, summary, load, logs | start, stop, restart, pause, resume | socket or TCP |
| Proxmox VE | node, guests, map, summary | start, shutdown, reboot | API token |
| Portainer | containers, summary | container actions | access token |
| Nomad | jobs, nodes, cluster | stop a job, scale a task group up or down | none on a cluster without ACLs, else an ACL token with node:read and namespace:read-job; the buttons need namespace:scale-job or namespace:submit-job |
| Cup | image updates, updates waiting | check now | none; Cup has no sign-in, so its port stays inside the network |
| PatchMon | PatchMon overview, hosts, operating systems | | a key of usage type API with the scope host: get, from Settings > Integrations > Auto-Enrollment & API (a GetHomepage key is refused); the URL has to be one named in PatchMon's CORS_ORIGIN |
| Coolify | applications, deployments, status | | API token; the API has to be switched on in Coolify |
| GitLab | projects (latest pipeline of the default branch, open merge requests and issues), pipelines (default branch, every branch or release tags; merge request pipelines left out), merge requests and issues (why a merge request cannot be merged yet), releases | | none for public projects; a personal, group or project access token with read_api for private ones. GitLab.com or your own GitLab; without a token GitLab.com allows 500 requests a minute per address |
| Gitea, Forgejo | open issues or pull requests, Actions jobs, repositories | | access token with read access to repositories, issues and the user |
| Jenkins | overview (jobs failing, running, queued, executors busy, nodes offline), jobs (last build of every job down to three folders, failing first, running ones with their progress, only failing or one folder) | build a job after a question (a job with parameters is built with their defaults) | user name and API token from the user's page under Security > API Token (the password cannot press the build button, it needs a CSRF crumb); Overall/Read and Job/Read, and Job/Build for the button. Beta: run against Jenkins 2.580.1 with the Folder plugin |
| Woodpecker CI | overview (repositories whose last pipeline failed, pipelines running and waiting, agents that are there), pipelines (the latest pipeline of every repository with branch, event and commit message, failing first) | | a personal access token from the user's page; an administrator's token adds the queue and the agents. Beta: only the version and the refusal were measured, because Woodpecker signs in through a forge and a test server had none; the rest is built from the documentation |
| Cronicle | overview (events whose last run failed, jobs running, completed and failed today), events (timing and last result of every event, failing first), latest runs (running jobs with progress, then the finished ones with the reason of a failure) | run an event after a question | an API key from Admin > API Keys, sent as a header (reading needs no privilege, the button needs Run Events); every Cronicle answer is HTTP 200 with the error in a code. Beta: run against one server with four shell events; that a key without Run Events is refused with a word containing "privilege" was not measured |
| Container registry | overview (repositories and tags), repositories (tags and newest version of each), newest versions (the newest version of images you name, how old and how big, and whether it is newer than the tag you run) | | user name and password or token of a robot account, or none for public images; Basic and the Bearer token flow of ghcr.io and Docker Hub. zot, Distribution, Harbor, ghcr.io, Docker Hub. ghcr.io and Docker Hub list no repositories, so only the last card works there. Beta: run against Distribution and zot as containers and read only against ghcr.io and Docker Hub, not against Harbor |
| Synapse | overview (users, rooms, deactivated users, reported messages waiting, servers that cannot be reached), reported messages (room, reason and who reported, newest first), largest rooms (members, public or private, encrypted) | | the access token of a server admin (in Element under Help & About > Advanced); the Admin API has to be reachable at the address, which a reverse proxy often prevents. The version endpoint answers without a token, so the test asks for the user list. Beta: run against Synapse 1.164.0 with two rooms and one report, the unreachable servers only from its documentation |
| Semaphore UI | last runs, automation | | API token of a user; the cards see the projects that user sees |
| Meilisearch | indexes, search | | a key of its own with stats.get, indexes.get, tasks.get and version |
| Synology DSM | system, volumes, disks, containers, vms | start, stop, restart; power on, shut down, reboot | user and password; containers and VM details through DSM's own interface calls |
| Unraid | system, array, guests | | API key (GraphQL) |
| Nextcloud | overview, active users, free space | | serverinfo token, or an administrator account |
| TrueNAS | system (with a waiting update), pools (with the last scrub), alerts; from 25.04 also interfaces, apps, disks, data protection, services, VMs and containers | | API key; use https, where a Read-Only Administrator is enough; over http only a TrueNAS before 25.04 is read, with a full administrator's key, because later versions deprecate the REST API that http is limited to |
| openmediavault | system, file systems, disks | | admin, or a user in the group openmediavault-admin; other users may sign in but read nothing. Three wrong passwords in five minutes lock the account in openmediavault until faillock resets it, so a refused password is tried again only every 15 minutes |
| Proxmox Backup Server | datastores, host, tasks | | API token; DatastoreAudit on /datastore and Sys.Audit on /system |
| Kopia | snapshots, backups | | the server's user and password; the CSRF token of its start page is fetched and kept |
| Duplicati | backup jobs, backups | | the password of the web interface; Duplicati 2.1 or newer |
| Syncthing | folders, status | | API key |
| Backrest | backup plans, backups | back up a plan now | user and password of Backrest's own sign-in, or nothing when it is switched off |
| Komodo | stacks, deployments, overview | restart a stack | API key and secret of a user, best a service user, with Read on stacks, deployments and servers and Execute on a stack to restart it; Komodo 2 |
| Arcane | overview, environments, projects, containers, image updates | start, stop and restart a container; start, stop, redeploy and update a project; update a container to its newer image | API key from Settings > API keys; environments:list, containers:list and projects:list for the cards, images:list, volumes:list and networks:list for the overview's counts, and containers:start, containers:stop, containers:restart, projects:deploy, projects:down, projects:update and image-updates:check for the buttons; Arcane 2.14 |
| Dockhand | overview, environments, stacks, containers, image updates | | API token from Profile > API tokens, or nothing when Dockhand's sign-in is switched off; a token may do everything its user may, and in the free edition every user may do everything, though the cards only read; Dockhand 1.0 |
| Kubernetes | cluster, nodes, workloads, pods in trouble | | service account token bound to the ClusterRole view and to a ClusterRole with get and list on nodes (view alone does not reach nodes); usage figures need metrics-server |
| UrBackup | overview, machines, backups | | an account of the web interface with the rights status and progress, or nothing when UrBackup has no account; finished backups need an administrator |
| Elasticsearch and OpenSearch | cluster health, indices, nodes | | Elasticsearch: an API key (the encoded value) or a user; OpenSearch: a user; the cluster privilege monitor and the index privilege monitor are enough |
| Alertmanager | firing alerts (critical first, matchers as a filter, silenced and inhibited ones on request), Alertmanager overview (firing, critical, warning, silenced, inhibited, silences in force), silences (in force and still to come, with how many alerts each keeps quiet) | | none; Alertmanager has no sign-in of its own. Basic authentication or a bearer token when a proxy in front of it asks for one; Grafana's and Mimir's Alertmanager with their path in the URL. API v2 |
| Netdata | raised alerts, load per node, alerts | | none; the agent's API is open, and a parent answers for every node that streams to it |
| Pulse | Pulse overview (active alerts, nodes, VMs, LXC and Docker containers, how many resources are critical or need attention), needs a look (the resources Pulse is not happy with, worst first, with the reason; Pulse 6.5 or newer), active alerts (critical first, acknowledged ones on request) | | an API token from Settings > API Access with the preset Kiosk / Monitoring, which is the scope monitoring:read alone, sent as X-API-Token; Pulse 6.0 or newer. Beta: run against a fresh Pulse 6.5.0 with one Docker agent, not yet against Proxmox |
| Ollama | loaded models, installed models, models | unload a model | none; Ollama has no sign-in, so its port stays inside the network |
| Open WebUI | users, models, accounts | | API key of an administrator from Settings > Account > API keys; API keys have to be switched on in the admin settings, they are off by default |
| Watchtower | last update run | run now | API token (WATCHTOWER_HTTP_API_TOKEN), with metrics and update switched on in WATCHTOWER_HTTP_API_ENDPOINTS; the maintained fork nickfedor/watchtower |
| What's Up Docker | container updates, updates waiting | update a container WUD has a Docker trigger for, check now | API token from My Profile, WUD 9 or newer; read for the cards, write for the buttons |
| Zabbix | problems, open problems | acknowledge | API token of a user with read access to the host groups; the plain User role may acknowledge |
| Pi-hole | summary, top blocked | pause 5 min, enable | app password (v6) |
| AdGuard Home | summary, top blocked | pause 5 min, enable | user and password |
| UniFi Network | network, console, devices, network map, findings, wlans | | API key (Network 9.0+), or a local account without two-factor; the network map needs the key |
| Speedtest Tracker | latest, history | | API token |
| Public IP address | address | | none (ipify or ipwho.is) |
| nextrmnl | status, sessions, history, connections | | read-only API key from nextrmnl 0.3.0 or newer, with API keys switched on |
| nexpulse | latest result (a running test live, a button to start one), history (speed or ping idle and under load), period summary, recent tests, latency under load (graded A+ to F) | | API key from nexpulse under Settings > API keys; a key that may only read fills every card, one with "Read and start tests" adds the button. nexpulse 0.1.1 or newer tells nexdeck which kind of key it is; on 0.1.0 the button is always shown |
| nexsift | nexsift inbox, newest lines | | an API key from Settings > API keys, after switching on Allow API keys; it may only read numbers and titles, never the text of a message |
| nexlore | nexlore overview, tasks, changed last, daily note | tick a task off, capture a line into the inbox, add a line to the daily note | an API token from My account > Connections > API tokens, after the operator has switched API tokens on; Read fills the cards, Write also ticks off and captures; the daily note needs Write, because it is made from the space's template when it is missing |
| nexcanvas | boards (the ones changed last with a picture each, how many changed today and this week), board (one board as a picture that renews itself) | | an API token from My account > Connections, after the operator has switched on API tokens under Settings > Server > API; it only reads, and a board the token may not read answers like one that does not exist |
| nexbrand | overview (clients, those with a published version, projects), latest versions (drafts first, then the newest published ones) | | an API token from My account > Connections, after the operator has switched on API tokens; the level Read is enough; colours, fonts, logos and notes never reach a card |
| nexpaper | inbox (the oldest waiting documents, yellow by count or age), deadlines (the next 14 days), filing (documents, this week, being read) | | an API key with the scope Read from My account, after the operator has allowed API keys under Settings > API; needs the nexpaper that has `GET /api/v1/dashboard` |
| nexdiary | diary (streak, written today, entries and notes of the month), time capsule (days until the next one opens) | | an API token from My account > Connections, after the operator has switched on API tokens under Settings > API; numbers only, never a word of the diary; needs the nexdiary that has `GET /api/v1/dashboard` |
| Traefik | overview, routers | | none, or basic authentication |
| Nginx Proxy Manager | proxy hosts, certificates, status | | an account; the token is fetched and kept |
| nginx ignition | status, traffic, certificates | reload, start, stop; renew a certificate | an API token, which carries the permissions of the user who made it: one that may only read fills every card, one that may write adds the buttons, which are offered only where they are the thing to press. Traffic needs the statistics switched on in nginx ignition, 2.47.0 or newer |
| OPNsense | system, gateways | | API key and secret |
| pfSense | system, interfaces | | API key of the package pfSense-pkg-RESTAPI |
| FortiGate | system (processor, memory, sessions, FortiOS version), interfaces (link, address, speed, traffic; the named ones turn the card red without a link), IPsec tunnels (by their phase 2 selectors), HA cluster (primary, configuration in sync) | | the token of a REST API administrator with a read-only profile and nexdeck under Trusted hosts, sent as a bearer token; an optional VDOM. Beta: not yet run against a FortiGate |
| OpenWrt | router, interfaces, DHCP devices | | root, or an rpcd login with the read groups luci-mod-status-index, luci-mod-status-index-dhcp and luci-base-network-status (the last also reads the wireless configuration); needs LuCI or uhttpd-mod-ubus |
| MikroTik | system, interfaces | | user with the read policy; needs RouterOS 7 with the REST service on |
| SNMP (switches and network devices) | device, ports, port traffic, findings, PoE | | SNMPv3 user with SHA and AES, read only; or an SNMPv2c community, which travels unencrypted. Any vendor, standard MIBs only (IF-MIB, EtherLike, ENTITY, POWER-ETHERNET, LLDP); never writes |
| FRITZ!Box | connection, line | | none, through "Transmit status information over UPnP" on port 49000; or a FRITZ!Box user for TR-064, needed in front of another router |
| Cloudflare | tunnels (healthy, degraded, down or never run, with their connections and data centres), zones (active, waiting for the name servers, paused), traffic (a zone's requests, visits, data and cached share over 24 hours) | | an API token with Account > Cloudflare Tunnel > Read, Zone > Zone > Read and Account > Account Analytics > Read, and the account ID for the tunnels. Built from Cloudflare's documentation, not yet measured |
| Tailscale | devices, status | | API access token from the admin console |
| Headscale | nodes, status | | API key from `headscale apikeys create` |
| NetBird | peers, status | | personal access token, best of a service user; self-hosted or NetBird Cloud (https://api.netbird.io) |
| Pangolin | status, sites, resources (public with their health, private with their destination) | | Integration API key of the organization with List Sites, List Resources and List Site Resources, plus the organization ID. Self-hosted, the Integration API needs `enable_integration_api` in config.yml and a route to port 3003; Pangolin Cloud at https://api.pangolin.net |
| wg-easy | WireGuard clients, VPN | | user and password; wg-easy 15 or newer |
| NetBox | devices, prefixes, inventory | | API token, read-only is enough; a v2 token is pasted whole, starting with nbt_ |
| Gluetun | tunnel | | none, or the API key if the control server has roles |
| Technitium DNS | blocking, top blocked | | API token |
| NextDNS | blocking, top blocked | | API key and the profile ID |
| authentik | status, failed sign-ins | | API token of a service account with read access |
| CrowdSec | blocked addresses, blocked | | bouncer key from `cscli bouncers add`; it may read decisions and nothing else |
| Shlink | short URLs, visits | | API key from `shlink api-key:generate` |
| Blocky | blocking, top blocked | pause 5 min, enable | none; Blocky's API has no sign-in, so its HTTP port stays inside the network, and statistics.enable has to be on (Blocky 0.35 or newer) |
| Gatus | endpoints, endpoint health | | user and password of security.basic, or nothing when Gatus has no security section |
| NetAlertX | new devices, offline devices, devices | mark as known | API token from Settings > General, sent to the API port (20212); save the settings once so the token stays the same |
| Pocket ID | recent sign-ins, users | | an administrator's API key from Settings > API keys, or STATIC_API_KEY; without a browser, a login code from `pocket-id one-time-access-token` opens the session that makes a key |
| Reolink | cameras, camera (snapshot or live video), findings | | user and password of a device account; HTTP or HTTPS switched on in the device's port settings |
| Frigate | cameras, detections, status | | none on port 5000, the internal API; a user and a password on port 8971, the authenticated one, and behind a proxy in front of it. A viewer is enough. The token is fetched and kept |
| Plex | now playing, library, libraries, recently added (covers), findings, server load, users and devices, top of the week, music player | scan a library; play music in the browser, make and change playlists (smart ones stay read-only) | Sign in with Plex (PIN at plex.tv fills token and server address), or the owner's token |
| Jellyfin, Emby | now playing, library, libraries, recently added (covers), findings, users and devices, top of the week, music player | scan every library (one alone does nothing on these, measured); play music in the browser, instant mixes, make and change playlists | API key |
| Nexview | requests, library, instances, requests to approve | approve with target folder and profile, turn down | API key; approving needs an approver's key that may write |
| nexbeat | requests (waiting, running, failed, arrived this week), library (artists and albums in Lidarr or nexcrate), requests to approve (with covers) | approve, turn down | API token from nexbeat 1.2.0 or newer under Profile > API tokens; a read-only token fills every card, approving needs an administrator's token that may write. A user's token counts only that user's requests |
| nexmail | unread mail (total and per mailbox, a mailbox whose sign-in fails is marked), latest mail (sender and subject, unread ones highlighted, each row opens the message in nexmail) | | API key from nexmail 0.17.0 or newer under Settings > API keys, with the mailboxes shared on it; the latest mail card needs the scope "Count, sender and subject" and is not offered for a key that may only count. The operator of nexmail has to allow API keys first |
| IMAP | unread mail, latest mail, folders | | user name and password or app password of the mailbox, over TLS, STARTTLS or, on a trusted network, unencrypted; no OAuth2, so Microsoft 365 is mostly out of reach. Reads counts and the sender, subject and date of a mail, never its text, and never marks anything as read |
| Mailpit | Mailpit overview (unread, all mail, accepted and rejected since the start, database size; amber while chaos is on), latest mail (sender and subject, unread highlighted, with Mailpit's own search) | | none, or the user and password of Mailpit's own login (MP_UI_AUTH or --ui-auth-file); with a webroot the URL includes it. Reading never marks a mail as read |
| nexcrate | library (there, wanted, on its way, stuck, as a ring), downloads (progress and time left), stuck downloads (needing you first, with the buttons nexcrate offers), coming up, just arrived (posters and covers), why is it missing (nexcrate's reason per wanted title), storage, findings | try again, search again, remove and search again, clear, on a stuck download | paired from the connection sheet: nexdeck shows a code, the owner confirms it in nexcrate and the key arrives by itself; a key made in nexcrate's settings works too. Every card reads with "read"; the buttons need "operate" |
| Seerr | requests, counts | approve, decline | API key |
| Overseerr, Jellyseerr | requests, counts | approve, decline | API key; same API as Seerr, listed under their own names |
| Tautulli | now playing, streams, most watched, plays per day | | API key |
| Tracearr | Tracearr overview, violations | | the public API key from Settings > API, which starts with trr_pub_ |
| RomM | platforms, recently added games, game library | | client API token with roms.read and platforms.read |
| Minecraft | server status, players online | | none; the server list ping of Java Edition over TCP, and for Bedrock Edition both the RakNet ping over UDP and the NetherNet join query over TCP that Bedrock 1.26 answers by default. SRV records are not followed |
| Immich | archive, storage, users | | API key of an administrator |
| Bazarr | status, missing subtitles, recently fetched | | API key |
| Audiobookshelf | library, listening now | | API key |
| ReadMeABook | overview, downloading, latest requests | | API token (rmab_) of an administrator from Profile > API Tokens; a user's token is turned away from the admin figures the cards read; ReadMeABook 1.2.0 or newer |
| Navidrome | library, playing now | | account; the Subsonic API signs each request with a salted token |
| Komga | library, recently added | | API key, or the account on older versions |
| Kavita | library, recently added | | API key; the token is fetched once and kept |
| Calibre-Web | library, recently added | | account; it has no API, so the address of its own table view is used |
| Tdarr | queue, nodes | | optional API key |
| Unmanic | workers, queue | | none |
| FileFlows | status, running | | optional access token |
| Maintainerr | collections, status | | none |
| Reclaimerr | Reclaimerr overview (titles marked for deletion, space they free, next automatic deletion, protections; amber on an old sync or scan or a failed task), leaving soon (the titles that go by themselves first, nearest deadline first, then the ones marked by hand, with size, days left and an open delete request of a user), tasks (schedule, last and next run) | postpone, keep, reset the timer, protect, on a title (a title marked by hand can only be protected); run now, on a task that neither deletes nor writes to Radarr and Sonarr | an rcl_ token from Settings > Integrations. Reading needs system:read, candidates:read, media:read, protections:read, tasks:read and events:read; the buttons need candidates:manage and tasks:run, and a card says which scope it misses. Sizes are known for whole movies and series only. What users vote for deletion is not in Reclaimerr's external API |
| Jellystat | libraries, most watched | | API key |
| M3U Editor | M3U Editor overview (streams the proxy carries, viewers, bandwidth, playlists, channels, guides; amber on a failed or old sync), active streams (channel, viewers by user name, running time, bandwidth; amber on a failover source or errors), playlists (channels, groups, last sync), guides (channels, last sync), recordings (running, planned, recent) | sync, on a playlist or a guide | an API token from API Tokens; the View ability is enough. The recordings need a DVR set up for the account. Custom, merged and alias playlists are listed but synced through their sources. Viewer addresses are never shown |
| Radarr, Sonarr, Lidarr, Readarr | queue, status, calendar | search missing | API key |
| Prowlarr | indexers, status | | API key |
| Jackett | Jackett overview (indexers set up, failing, public and private), indexers (failing ones first with the first line of the reason) | test an indexer | none; the admin password only when one is set in Jackett |
| Ombi | requests (pending movie, show and album requests, newest first, with who asked), request counts (pending, approved, available, declined) | approve, decline | API key from Settings > Ombi Configuration; the counts answer without a key, so the connection test reads a request list |
| slskd | Soulseek status (connected or not, shared files and folders, what is downloading and uploading, a newer version), downloads and uploads (transferring, queued and failed transfers with progress and the other user) | clear the finished transfers | an API key (web, authentication, api_keys in the slskd configuration), or the web user's name and password; the transfer lists follow slskd's OpenAPI file and are not measured, since they need a Soulseek account |
| Owncast | stream (live or offline, how long, viewers, the picture it sends, health and followers), viewers (now, the peak of the session and of all time) | disconnect the broadcaster | none for the public status; the stream key (the password of the user admin) for viewers, health and the button |
| Kodi | now playing (title, show and episode or artist and album, picture, progress and time left), Kodi status (idle, playing or paused, volume, version), library (movies, series, episodes, albums, songs) | play or pause, stop, mute, update the video library | the address of Kodi's web server (Settings > Services > Control), with its user name and password when one is set; only the sign-in and the properties were seen against a headless Kodi 18.5, a player and the library never |
| PeerTube | Instance (videos, views, users, active users, storage, followers; PeerTube keeps these for a few minutes), newest videos, Moderation (open reports with what they are about, accounts waiting, videos held back), Job queue (waiting, running, failed) | | none for the instance numbers and the newest videos; a moderator for Moderation and an administrator for the job queue, with the host name PeerTube was installed with when the URL uses another |
| rclone | transfer speed (speed with the bandwidth limit as the full dial, done, left, files, errors), transfers (the files moving with progress, then the latest finished and failed ones), rclone overview (bandwidth limit, remotes, version) | reset the counters, set the bandwidth limit | the address of `rclone rcd` (port 5572) with its --rc-user and --rc-pass, or none with --rc-no-auth |
| Stash | library (scenes, images, galleries, size, length, plays; numbers only, no titles or names), tasks (what is scanning, generating or cleaning, with progress) | scan for new files, stop all tasks | an API key (Settings > Security; it needs a user name and password first), or none when Stash has no login |
| xTeVe | xTeVe status (running, version, guide source, streams and channels when xTeVe gives them), also Threadfin | update the playlists, update the guide, map the channels again | none; the API has to be switched on in xTeVe's settings, and its API token left off |
| Your Spotify | listening (tracks played today, this week and this month), played last (the latest tracks with artist and age) | | the public token from Your Spotify's settings, and the address of its server (the API); built from the server's own code and never run against an instance with listening data |
| autobrr | recent releases, grabbed | | API key from Settings > API keys |
| NeutArr | NeutArr overview, hunted apps | | the API key from NeutArr's User page, sent as a header; NeutArr is the continuation of Huntarr |
| SABnzbd, NZBGet, qBittorrent, Transmission, Deluge | queue, speed | pause, resume | key or password |
| aria2 | queue, speed, finished and failed (the latest stopped downloads with the reason for each failure) | pause, resume, clear the list of stopped downloads | the RPC address (port 6800) and the RPC secret when aria2 runs with one |
| pyLoad | queue, speed, needs a look (failed and offline links with the reason, a waiting captcha) | pause, resume, try the failed links again | an API key (pl_...) made in pyLoad under Settings, API keys; pyload-ng 0.5 or newer |
| Qui | Qui overview, instances | | an API key, made under Settings > API keys; one key reads every qBittorrent behind Qui |
| Real-Debrid | Real-Debrid account (premium days, end, points, active torrents against the limit), torrents (progress and state), latest downloads, data used (a bar for each of the last 7, 14 or 31 days, the total and the hoster most of it came from), hoster limits (each hoster with a limit, used against what is left, and when it resets) | | the private API token from real-debrid.com/apitoken; Real-Debrid refuses many VPN and data centre addresses, and allows 250 requests a minute for all apps on an account together |
| rTorrent | queue, speed, torrents, rTorrent overview | pause, resume | the XML-RPC address (such as :8000/RPC2 of crazymax/rtorrent-rutorrent) or the address of ruTorrent, with the web server's user and password when one is set |
| MeTube | fetch a video, downloads, download count | fetch an address you type in, save the file to your own machine, remove, try again | none; MeTube has no login of its own, so whoever reaches it may queue and delete |
| Sportarr | upcoming, missing events, events | | API key from Settings > General > Security |
| Tube Archivist | download queue, latest videos, video archive | start downloads | API token from Settings > Application, sent as Token |
| Home Assistant | entity, entity list; home pages (beta) with lamps, thermostats, covers, scenes, scripts, switches, sensors and statistics | turn on/off, scenes, scripts, covers, locks; on home pages only the services of lamps, thermostats, covers, scenes, scripts, switches and input booleans | long-lived token, of an administrator for home pages; live over WebSocket |
| Uptime Kuma | monitors, summary (both by name or by status page) | | API key (metrics endpoint); a status page is read without one |
| GoatCounter | visits (today, yesterday, the last 7 and 30 days), top pages, top referrers (today, 7 or 30 days; visits without a referrer are named) | | an API token from the site's Settings > API with the permission to read statistics, which the command line cannot give; four requests a second are allowed. Run against a self-hosted GoatCounter with a few visits |
| Umami | website (visitors, page views, visits, bounce rate, visit time and who is on it now, for one website), websites (visitors and live visitors of each), top of a website (pages, referrers, countries, browsers or devices) | | the user name and password of your Umami, or the API key of Umami Cloud with the URL https://api.umami.is; Umami 2 and 3 are read alike. Beta: built from Umami's API documentation and never run, since Umami needs PostgreSQL and so a second container |
| Healthchecks | checks, checks up | | API key from the project settings; the read-only one is enough, and healthchecks.io works too |
| ChangeDetection.io | recent changes, watches | check all now | API key from Settings > API |
| n8n | workflows, last runs, summary | publish, unpublish | API key from Settings > n8n API |
| Beszel | hosts, host | | user and password |
| Glances | system, file systems, sensors | | optional password |
| Scrutiny | disks, disk health | | none |
| UPS (PeaNUT) | UPS, UPS details | | optional sign-in; PeaNUT 6.0.0 refuses a password with a colon or umlauts on its API, and any password behind a reverse proxy with HTTPS unless WEB_USERNAME and WEB_PASSWORD are set on its container |
| Gotify | messages, message count | | client token (an application token may only write) |
| ntfy | messages | | topic, and a token for a protected one |
| Prometheus | query value, query list | | optional basic auth |
| Grafana | alerts, status | | service account token; needs unified alerting, so Grafana 9.0 or newer |
| JSON API | value (with up to four badges from the same answer), list | | optional bearer token |
| iCal feed | events | | feed address |
| Paperless-ngx | archive, latest documents | | API token from the user profile |
| Papra | documents (count, size, trash), latest documents (with tags), organizations | | an API key from API keys in the user menu with Read organizations and Read documents; the organization by name or ID, or the first the key can see. Beta: run against a fresh Papra, not yet one in use |
| Mealie | meal plan, shopping list, kitchen | | API token from Profile > Manage your API tokens |
| Grocy | stock to watch, pantry | | API key from Manage API keys |
| Vikunja | due tasks, tasks | | API token with read_all for tasks and projects; the time zone for "today" is a field, because a token cannot read the user's own |
| Kimai | time entries, booked time | stop a running timer | API token from Profile > API access |
| Dawarich | distance, distance by month | | API key of the account; distances follow Dawarich's hourly calculation |
| wger | weight, weigh-ins | | API key from the profile, sent as Token |
| FileBrowser Quantum | storage | | an API token with the permission api, made in FileBrowser's settings; shares are counted when the token may read them |
| Firefly III | money, subscriptions, budgets | | personal access token from Profile > OAuth |
| Actual Budget | this month (left to budget, budgeted, spent, overspent categories), accounts (balances, on and off budget), categories (spent of the budget, overspent first) | | through [actual-http-api](https://github.com/jhonderson/actual-http-api), a second container next to Actual, because Actual has no API of its own: its URL, its API_KEY and the budget's sync ID (Settings > Show advanced settings), and for an end-to-end encrypted budget its password. Reads only |
| evcc | energy, energy flow, charging | | none; the state is readable without a password |
| BookOrbit | reading now, recently added, library | | user and password; BookOrbit has no API keys and allows five sign-ins a minute, so the token is kept |
| Ghostfolio | portfolio, holdings | | security token of the account from Settings > Access; it is exchanged for a JWT that lasts 180 days |
| Homebox | inventory, value by place or tag, warranties | | API key from Profile > API Keys (Homebox 0.26 and newer; shown only once), or the account's e-mail and password on older versions |
| PhotoPrism | photo library, recently added | start indexing | app password from Settings > Account > Apps and Devices; a client access token cannot list photos |
| Tandoor Recipes | meal plan, shopping list | tick an entry off | API token from Settings > API; the scope read is enough to look, ticking off needs read write |
| OctoPrint | printer, print job | | application key from User Settings > Application Keys; its user needs the permission Status (groups Users or Read-only) |
| Spoolman | filament stock (the filament left on all spools together, how many spools there are and how many run low), spools (each with what is left, the emptiest first) | | none; Spoolman has no sign-in, so its port stays inside the network. Beta: run against Spoolman 0.27.0, not yet one in use |
| Moonraker | printer (state, nozzle, bed and chamber temperatures; red with Klipper's own reason after an error or a shutdown), print job (file, progress, time taken and left, layer), print history (prints, print time, filament used) | pause, resume, cancel a print (cancel asks first) | none when Moonraker trusts nexdeck's address (trusted_clients in moonraker.conf), else its API key from Mainsail's or Fluidd's settings; the address is Moonraker's (port 7125). Beta: run against Moonraker with Klipper on a simulated printer, which cannot print, so a running, paused or finished print is built from the documentation |
| openHAB | overview (things online and offline, items, rules, rules that did not start; red while a thing is offline), things needing a look (offline, not started or starting, worst first, with the reason; disabled ones last), items (state of every item or of a group), item (one value as a number with its history, or a switch) | switch on and off, on a Switch item (asks first) | an API token from your profile > API Tokens, made as an administrator; without one items are read and things and rules are refused. Beta: run against openHAB 5.2.3 with the NTP binding, not yet an installation in use |
| Homebridge | Homebridge (running, starting or stopped, version and whether it is behind, load, memory and uptime of its machine), plugins (installed ones, those with an update first), accessories (state of every HomeKit service Homebridge bridges), accessory (one value as a number with its history, or a switch) | switch on and off, on a switch, outlet, lamp or fan whose On can be written (asks first) | the user and password of Homebridge's web interface (the token is fetched and kept, and renewed when it runs out), or nothing when it runs without a sign-in; a user with two-factor sign-in does not work. The accessory cards need Homebridge in insecure mode, which its Docker image and hb-service use. Beta: run against Homebridge 2.4.0 with UI 5.29.0 and the plugin homebridge-dummy, not yet an installation in use |
| Node-RED | Node-RED (flows running or stopped, version, flows and nodes deployed, memory), flows (the tabs with their node counts, disabled ones last), inject nodes (every inject node of a flow that runs) | trigger an inject node (asks first) | none when the admin API is open, else the user and password of adminAuth (type credentials); the token is fetched and kept for its week. A user who may only read fills the cards, triggering needs one who may write. Five wrong passwords lock the address out for ten minutes in Node-RED itself, so a refused password is not tried again for a quarter of an hour. Starting and stopping all flows is left out: Node-RED answers it only when runtimeState is switched on. Beta: run against Node-RED 5.0.9, not yet an installation in use |
| ESPHome | overview (devices online and offline, updates waiting, dashboard version; yellow while a device is offline or behind), devices (every device, the offline ones first, then those with an update, each linking to its own web page when it has one) | | none, or the user and password the dashboard was started with (USERNAME and PASSWORD, sent as Basic); the address is the dashboard's, usually port 6052. Reads the dashboard only, never a device. Beta: run against the ESPHome device builder 2026.10.0 with three configurations; a device that is online could not be reproduced there, so the online and offline states are built from the dashboard's own front end and from /ping of older dashboards |
| Tasmota | relay (on or off, firmware, Wi-Fi signal, uptime; one card for each relay of the device), power draw (power now with history, voltage, current, energy today, yesterday and in total; needs a device with an energy chip) | switch a relay on and off (asks first) | none, or the device's web password (WebPassword), sent as HTTP Basic and never in the address. Beta, and not measured at all: there is no Tasmota to run in a container, so every answer is taken from Tasmota's documentation of `Status 0` and its commands, and the refusal of a wrong password from its source |
| Fronius | solar production (power now with history, energy today, this year and in total, the share the house uses itself and its own supply), energy flow (solar, house, battery with charge, grid; needs a meter) | | none; the Solar API has no sign-in, but can be switched off in the inverter (Communication, Solar API). Beta, and not measured: there is no Fronius inverter to run in a container, so the answers are taken from Fronius' Solar API documentation of the power flow request |
| OpenDTU | solar power (all inverters together now with history, energy today and in total, how many produce; yellow with a radio problem or the default password), inverters (each with power, temperature and power limit; asleep at night, which is grey and no fault) | | none, or the password of OpenDTU's web interface (user admin, HTTP Basic) when read-only access to the API is switched off. Beta, and not measured: OpenDTU is firmware for an ESP32 with a radio and cannot be run in a container, so the answers are taken from its Web API documentation and source |
| Shelly | power draw (all measuring channels together now with history, energy used, temperature, Wi-Fi signal, uptime, firmware update), switches (each relay on or off with its power) | switch a relay on and off (asks first) | none, or the device's password: Gen1 devices take HTTP Basic with the user set, Gen2 and newer take Digest with SHA-256 and the user admin. Both generations are told apart by themselves. Beta, and not measured: a Shelly is a device and cannot be run in a container, so the answers are taken from Shelly's Gen1 and Gen2+ API documentation (the Digest handshake itself is tested against a computed SHA-256 response) |
| Wallos | next payments, subscription costs | | API key from the profile; it goes in the body of a POST, never in the address |
| Weather (Open-Meteo), RSS feeds, Calendar, Basics | current, headlines, upcoming, clock, countdown, timer, notes, bookmarks, iframe, app tile, heading, group, tabs, key figures, status page, notices, updates (containers from What's Up Docker, Cup, Arcane, Dockhand and Watchtower, GitHub projects, the versions of the connected services), this machine | | none; the versions of the connected services ask GitHub only while Check for updates is on |
| Hacker News | stories | | none |
| Miniflux | unread, failing feeds, feed reader | | API key from Settings > API Keys |
| FreshRSS | feed reader, unread, unread by feed | | user name and the API password from Settings > Profile, not the sign-in password; API access allowed under Administration > Authentication |
| Karakeep | recent bookmarks, reading list | | API key from Settings > API Keys |
| Linkwarden | recent links, links | | access token from Settings > Access Tokens |
| Linkding | bookmarks, recent bookmarks | | REST API token from Settings > Integrations; each account sees its own bookmarks only |
| YouTube | videos, subscriptions | | none for videos; subscriptions need a YouTube Data API v3 key and a public subscription list |
| GitHub releases | releases, issues and pull requests, workflow runs, repository (stars, forks, open issues and pull requests, the newest release, the last push), pull requests (with the state of their checks), milestones (how much is done, when due) | | none, or a personal access token that raises sixty requests an hour per address to five thousand; every pull request shown costs one more request for its checks |
| Share prices | prices | | none |
| Twitch | live | | client ID and secret of an application at dev.twitch.tv |
| Wake-on-LAN | wake | wake | none; a MAC address and a network that carries the broadcast |

Adapters marked **beta** in the interface have not been confirmed against a
live instance yet. They are built against the documented API and recorded
answers; a report with the service's version is welcome.

### Texts

Everything an adapter says is English: field labels, help texts, widget names
and descriptions, and the labels of values, chips, rows and actions. The
interface translates them by their English wording from one table per
language, `frontend/src/i18n/texts.<code>.json`. A guard in
`backend/tests/test_guards.py` fails when a new text has no German entry,
values and the parts of a line joined with " · " included, and another when a
language knows less than German does. Words around a number ("3 restarts")
are translated by a pattern: the German list is in
`frontend/src/i18n/texts.ts`, every other language follows it pattern for
pattern in `patterns.<code>.ts`. Data that is not a label (names, sizes,
identifiers) passes through untouched.

A widget that draws itself from its options (clock, notes, bookmarks, embedded
page, app tile) sets `client_only=True`; the settings sheet then hides the
refresh interval. A field of type `timezone` is offered as a list of IANA
zones. `POST /api/v1/widgets/{id}/preview` runs a fetch with draft options
without saving; the settings sheet uses it for its live preview.

An app tile may follow an integration: pick one in its settings and the
tile's link and its reachability check take the integration's address on
every read, so a changed address is changed once. A link of the tile's own
still wins.

Or it follows an app of the catalog (System > Apps): `options.app_id` names
the app and `options.address` the label of the address it opens, or `auto`.
Name, icon, description, address and check then come from the app, for an
app without an adapter as well. `auto` opens the address named for home when
the browser is in a home network (System > Home network, which may name
networks without switching the sign-in on) and the one for the road
everywhere else, including where nexdeck cannot tell. The check runs on the
home address, since nexdeck runs at home. An export names the app and carries
it along; an import over HTTP creates no app and turns a tile whose app is
missing into a tile of its own.

A card can be enlarged but never made smaller than its `default_size`;
`min_size` is what the server uses when it has to squeeze a new widget into
a tight spot.

## Renderers

`value`, `gauge`, `stats`, `list`, `nowplaying`, `calendar`, `text`,
`bookmarks`, `iframe`, `clock`, `weather`, `feed`, `log`, `chart`, `app`, `posters`,
`counters`, `camera`, `bars`, `ring`, `timeline`, `heading`, `meter`, `segments`. A fetch may pick another renderer for its data through
`meta["renderer"]`; the media library card uses that for its icon row.

Key figures (`core.figures`, renderer `figures`) hold number cards of their
page in `options.cards`, as a group does, and draw each as a tile with its
value, unit and colour. A number card is one drawn by `value`, `stats` or
`gauge` that records a metric and is refreshed by the server
(`holders.is_number_card`); anything else is left out when picked and refused
when dropped. "Yellow from" and "Red from" set `meta.level` in every
view; the dial, the LEDs, the digits and a tile read it, and a card's
settings offer the two while it is a tile. The countdown and the timer (`countdown`, `timer`) count in the
browser; a field of type `date` or `time` is the browser's own picker. A
timer's state is kept in the browser that runs it.

Every card drawn by `value`, `stats` or `gauge` that records at least one
metric gets the drawings of a number by itself: a dial, LED bars, seven
segments and a chart (a card drawn by `gauge` gets "The number" instead of
a dial, as the view `number`; `value` stays its dial), with "Full at" and "Empty at" for the dial and the
LEDs, the lines "Yellow from" and "Red from" (red below yellow means low
numbers are the bad ones), and the hours a chart reaches back: one, six or
twenty-four, as far as nexdeck keeps minute rows. Those lines colour the drawing only (`meta["level"]`); the card's
`status` stays what the service said.

Images such as posters are never linked with a token in the browser: an adapter
hands out `proxy:/path`, and `GET /api/v1/widgets/{id}/image?path=` fetches it
from the service with the adapter's `image_headers`, cached for an hour. An adapter
may override `image_source(config, path, ctx)` to turn a path into another request,
for example a camera snapshot with a session token that must not be cached
(`cache_seconds=0`). ⚠️ The route answers only for the shapes the adapter names in
`image_paths`, a tuple of `ImagePath(pattern, **query_patterns)`, checked before the cache and before
`image_source`. The default is none, so an adapter without the list hands out no pictures: a GET with the
service's credentials can do harm (Plex marks a film as watched on `/:/scrobble`). Name every shape you write,
as narrowly as the service allows. `tests/test_image_paths.py` finds adapters with pictures by itself and fails
until their real paths pass and dangerous ones do not. Live video goes the same way: `stream_source(config, options,
ctx)` names an HTTP-FLV stream, and `GET /api/v1/widgets/{id}/stream` relays its
bytes to the browser, which plays them with Media Source Extensions. The server
relays at most twelve streams at once.

## Writing an adapter

```python
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url

class ExampleAdapter(Adapter):
    kind = "example"
    label = "Example"
    category = "monitoring"
    description = "What it shows."
    icon = "example"          # a dashboard-icons name
    fields = (
        Field("url", "URL", type="url", required=True),
        Field("api_key", "API key", type="password", secret=True, required=True),
    )
    widgets = (
        WidgetType(kind="status", label="Status", description="...", renderer="value",
                   default_size=(2, 2), refresh_seconds=30, metrics=("value",)),
    )

    async def test(self, config, ctx):
        payload = await ctx.get_json(f"{base_url(config)}/api/version", headers={"X-Api-Key": config["api_key"]})
        return f"Example {payload['version']} answers."

    async def fetch(self, widget_kind, config, options, ctx):
        payload = await ctx.get_json(f"{base_url(config)}/api/status", headers={"X-Api-Key": config["api_key"]})
        return WidgetData(primary={"label": "Load", "value": payload["load"], "unit": "%"}, metrics={"value": payload["load"]})

    def demo(self, widget_kind, options, tick):
        from . import demo as fake
        value = fake.walk("example", tick, 5, 60)
        return WidgetData(primary={"label": "Load", "value": value, "unit": "%"}, metrics={"value": value})

ADAPTER = ExampleAdapter()
```

Rules:

- Secrets are fields with `secret=True`; they are encrypted at rest and never returned by the API.
- Raise `AdapterError` (or `AuthFailed`, `Unreachable`) with an English message and a hint; the card shows both.
- `metrics` are numbers recorded for sparklines; name them stably. They also
  give the card a **View** option that draws them as one chart (a number card
  from one metric on, any other card from two), so name them for a legend, not
  for a column.
- **A dial needs to know what full is.** A number in `%` is full at 100 by
  itself. A card that knows its own ceiling, such as a line's speed, passes it
  as `as_gauge(card, options, maximum=...)`: the dial and the LED bars both use
  it. A fetch that has to pick one number out of several for these views asks
  `single_number_view(options)`.
- **A drawing is offered, not written into the adapter.** A `list` card gets
  bars by itself. For a ring, set `ring=True` on the `WidgetType` **and** have
  the fetch write `meta["ring"] = ring_of(("Blocked", 400), ("Allowed", 600))`:
  only the fetch knows what the whole is, and slices taken from `secondary`
  would add up to something that does not exist.
- `demo()` must return believable, moving data for every widget kind; a test checks that.
- Add a test with recorded answers under `backend/tests/`, using `respx`.
