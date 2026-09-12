# Changelog

All notable changes to nexdeck. The format follows Keep a Changelog; the
project uses semantic versioning.

## 0.13.0 (2026-09-12)

### Security

- **Apprise channels are for administrators only.** Apprise follows redirects in its own HTTP library, where no address check reaches, so a member's channel could ask what listens beside the server. Members no longer see the kind and cannot add or change one, and an Apprise channel a member set up earlier refuses to send. `localhost` and the names under it now count as loopback for members.
- **Uploads are served to a session or a kiosk display only.** The running number in their address made every picture of every account countable without signing in. They are cached privately now.
- **Addresses a member typed are checked on every redirect.** RSS cards and HTTP reachability checks follow redirects through the member rule, and the Wake-on-LAN card checks its host and its broadcast address.
- **Connections no longer share cookies.** The collector used one client for every connection, so a session one service had set went along with the next request to the same host: on What's Up Docker a wrong password got in. Only the connections that sign in with a cookie keep one, each for itself.
- **A kiosk token leaves the address after the first load.** The display keeps it itself, a reload of `/k` comes back in, and the page a kiosk link opens is sent with `Referrer-Policy: no-referrer`, so the token no longer lands in proxy logs. Displays that are already on the wall move over at their next load.
- **A revoked kiosk link or permission reaches open streams.** The board stream, the log stream and the video relay ask again at least every 25 seconds whether the viewer may still be there.
- **Refresh now asks a service at most once per five seconds for each card.** Presses inside that gap get the answer of the first one; before, whoever could act on a board could send the server at a service as fast as it answered.
- **The test button of a channel takes five presses per account in ten minutes.**
- **A restore refuses archive names like `avatars/..` before anything is replaced**, a Web Push subscription moves to another account only with the same keys, and a `secret.key` from before 07.09.2026 is narrowed to 0600 when it is read.

### Changed

- **`NEXDECK_URL_BASE` is gone.** It only ever moved the cookie paths; the interface never knew a sub path, so setting it left a page that did not load. An installation that set it runs under `/` again.
- **The public address is read in one place:** the address under Settings > Address, else `NEXDECK_PUBLIC_URL`. Web Push and the rescue link read only the environment variable, so an address set in the interface signed push messages as `mailto:admin@localhost`.
- **A fresh database starts at the newest schema** instead of running every migration over the tables it has just built.

### Fixed

- **A message on a live board closes by itself again.** Every card answer started its five seconds over.
- **The "what is new" window closes at once**, also with the server gone or the session expired.
- **A board file or an import with an unreadable layout is refused before the old cards are deleted**, and provisioning rolls back when a file fails halfway.
- **The problems card names a tile whose reachability check fails**, instead of a red tile next to "Everything is fine".
- **A backup leaves the chart history out**, as it always meant to; it named a table that does not exist.
- **The command bar keeps the keyboard inside while it is open**, and six fields that only a placeholder named carry a label for screen readers.
- **Testing a saved connection answers an unreadable key or a crash with a message**, not with a bare 500.
- **The Web Push key pair is made once**, also when two browsers switch Web Push on at the same moment.
- **Two routes answer 404 instead of 500 when a card's page is gone.**
- **A refused address reads as one sentence**, without a double space.

### The test bench

- **`backend/tools/ci_local.py` runs the CI set on your own machine**, read from the workflow itself: installs only with `--install`, the version check with `--tag`, and a condition it does not know stops it.

## 0.12.1 (2026-09-12)

### Fixed

- **The buttons on every card are flat again.** Refresh, link, settings and remove sat in a frame at 32 pixels instead of as flat 24 pixel icons. The same held for the close buttons of dialogs, the buttons in the notices and the board's toolbar in edit mode.
- **A password no longer runs under the button that shows it.** The field kept no room for the button, so a long password disappeared behind it.
- **Sizes, borders and colors written on single elements apply again, 90 elements in all.** Among them the sign-in buttons, the round wake button, the top bar and the phone's tab bar, which had borders at their edges, and the warning chip on the backups page, which was grey. nexdeck's own styles stood outside Tailwind's cascade layers, where a rule beats every utility on the same element; they now sit in a layer, and a test fails when a rule leaves it.

## 0.12.0 (2026-09-12)

### New

- **20 new integrations, each measured against a running instance before it was written.** All of them start out of beta: every card and every action was run against the service in throwaway containers, and the tests carry the answers that came back.
- **Backrest:** every backup plan with its last backup, how much it holds and why it failed, failed ones first, and how many plans are fine and when the last good backup ran. A backup can be started from the card.
- **Blocky:** whether blocking is on, the queries of the last 24 hours and the share blocked, with a button to pause blocking for five minutes, and the domains blocked most often.
- **BookOrbit:** the books being read with how far along they are, what came into the library last, and the number of books and authors.
- **Gatus:** every endpoint with its last response time and why its last check failed, down ones first and then those that failed within the last 20 checks, and how many endpoints are up and down.
- **Ghostfolio:** what the portfolio is worth with today's change and the change since the start, and every holding with how it moved today.
- **Homebox:** how many things the inventory holds and what they are worth, and the warranties that end soon or just ended.
- **Komodo:** every stack and deployment with its state and server, troubled ones first, and an overview of how many stacks and deployments run and how many servers answer. A stack can be restarted from the card, and the card waits for Komodo's own result.
- **NetAlertX:** new devices on the network with a button to mark each as known, the devices that went offline, and an overview of online, new and offline devices.
- **Netdata:** raised alerts on every node with the critical ones first, the load of each node with its state and worst alert, and an overview of raised and critical alerts.
- **Ollama:** the models loaded right now with the memory each one takes, the installed models with their size on disk, and a button that unloads a model.
- **Open WebUI:** who has an account and who waits for approval, how many were active in the last three minutes, and the models it offers with their connection.
- **PhotoPrism:** how many photos and videos the library holds and how many are in review, the latest additions, and a button that indexes the originals.
- **Pocket ID:** who signed in lately, how and from where, and an overview of users, administrators and disabled accounts.
- **Sportarr:** the monitored sports events of the next days, the ones that took place without a file, and how many leagues there are.
- **Tandoor Recipes:** the meal plan for today and the next days with the time of each meal, and the shopping list with a button to tick an entry off.
- **Tube Archivist:** the videos waiting in the download queue with a button that starts them, how far a running download is, the videos downloaded last, and how many videos and channels the archive holds.
- **Wallos:** the next payments of the active subscriptions with their price, and what falls due this month and next.
- **Watchtower:** how many containers the last update run updated and how many failed, and when it ran, with a button that starts the next run. Built for the maintained fork nickfedor/watchtower.
- **What's Up Docker:** which containers run an image with a newer version, the biggest step first and the containers WUD could not check after them, and how many updates are waiting. A container WUD has a Docker trigger for can be updated from the card, and WUD can be told to check again.
- **Zabbix:** open problems with the most severe first, their hosts and a button to acknowledge each, and an overview of open, high or worse and unacknowledged problems.

### Found while measuring

- **A fresh Backrest answers everyone.** Its configuration came back without any credentials until a user was added, and once a repository is added that configuration carries the repository password in plain text. A wrong password is answered with the same words as no password at all.
- **Backrest's dashboard knows that a backup failed, but not why.** The reason stands only in the backup's operation, so nexdeck asks for it for failed plans alone. A backup whose request nobody waits for any more still runs to its end.
- **Blocky's numbers exist only with statistics switched on.** `/api/stats` keeps a rolling 24 hours in memory and answers 503 "statistics are disabled" unless `statistics.enable: true` is set; a restart starts it from nothing.
- **Pausing Blocky answers with an empty 200.** `GET /api/blocking/disable?duration=5m` says nothing in its body, and POST gets 405, so the card asks for the blocking status afterwards to know it happened.
- **Blocky's API has no sign-in at all.** A made-up token gets the same answer as none, so whoever reaches Blocky's HTTP port may pause blocking.
- **BookOrbit has no API keys and allows five sign-ins a minute.** The sixth sign-in inside a minute got 429 Too Many Requests. The token lasts fifteen minutes, so the card keeps it and signs in again only when it runs out or is refused.
- **BookOrbit's own dashboard widgets lag behind.** Progress saved a second ago was on the continue-reading shelf at once and in the "currently reading" widget only two minutes later; the library overview and the yearly count are kept for five. The cards read the shelves.
- **Gatus hands out uptime without a password.** With basic authentication switched on, the list of statuses asked for it, while the raw uptimes, the raw response times and the configuration address answered anyone.
- **Gatus gives durations in nanoseconds and leaves an endpoint out until its first check.** A check can fail with status 200 when its response time condition does not hold, and after a restart an endpoint whose host did not resolve was missing from the list for more than ten seconds.
- **Ghostfolio's day change is wrong for a short while after an import.** Twenty seconds after three purchases were imported, yesterday's point still stood at the amount invested and "today" read +40.6%; thirty seconds later it read +1.25%. The card shows "?" while yesterday equals the investment, and a portfolio without a chart is not recorded as a zero.
- **Ghostfolio's percentages are a return on the amount invested.** A change of -0.21 on a portfolio worth 654.87 read -0.07%, because 300 had been invested. The card shows Ghostfolio's figure as it comes.
- **Ghostfolio has no API keys.** The security token of an account is exchanged for a JWT that lasts 180 days; a wrong token gets 403, a wrong JWT 401, and the admin endpoints answer 403 to an ordinary account.
- **Homebox's item list has no warranty field.** Items are entities in this version, and their summary leaves the warranty out; the CSV export has it for every item in one request, so the warranty card reads the export.
- **Homebox counts the total value two ways.** The statistics multiply by the quantity (four batteries at 5.00 counted 20.00); the totalPrice of the entity list covers only its page and ignores the quantity. The card takes the statistics.
- **Homebox 0.26.2 documents /v1/currency and answers 404.** The currency is on /v1/groups.
- **Komodo reports success before it has done anything.** A restart answered 200 with success at once, also for a user without permission on the stack; only the finished update a moment later said it had failed. nexdeck follows the update to its end and shows what it says.
- **Five wrong Komodo keys lock the address they came from.** The sixth request got 429 for 15 seconds, and so did the right key from the same address. A key without permissions sees empty lists rather than a refusal, and with the agent of a server gone every stack on it reads unknown rather than down.
- **Without an API_TOKEN line in app.conf, NetAlertX's token changes at every start.** NetAlertX draws one when it starts and writes it nowhere, so a card set up with it stops working after the next restart. Saving the settings once keeps it.
- **A NetAlertX device that goes offline while it is new still says New.** Its devStatus stays New, and only devPresentLastScan 0 tells that it was missing in the last scan, so the cards read that field.
- **NetAlertX gives its times without a time zone.** devFirstConnection and devLastConnection are in NetAlertX's own TIMEZONE setting, which the cards ask /settings/TIMEZONE for.
- **A container that restarts on a Docker network comes back to NetAlertX as a new device.** It gets a new MAC address, and its old entry stays behind as offline.
- **A Netdata child that stops streaming takes its alerts with it.** Within seconds the parent marks it stale, its health reads disabled and its raised alerts leave the list, so the node card shows it as Stale without a load and the overview counts only the nodes that report.
- **Netdata's `/api/v1/alarms` only sees the node it is asked on.** On a parent that is the parent alone; the cards use `/api/v3/alerts`, which answers for every node streaming to it.
- **Ollama has no unload call of its own.** A generate request without a prompt and with `keep_alive: 0` unloads the model; it answers `done_reason: "unload"` with 200 even for a model that was not loaded, and 404 only for one Ollama does not know.
- **A model loaded in Ollama takes more memory than its file.** `/api/ps` reports the memory in use: a model of 258 MB on disk took 364 MB loaded with a context of 4096.
- **Ollama has no sign-in at all.** A made-up bearer token gets 200 like none, so its port belongs inside the network.
- **Every request with an Open WebUI key marks its owner as active.** A card polling with an administrator's key would keep that administrator active for good, so the key's own user is left out of the active count and its row shows no time.
- **Open WebUI gives a made-up key and a user's key on an administrator's address the same 401.** Only the detail text tells them apart. API keys are off by default, and while they are off a key gets 403.
- **Open WebUI merges models of the same id across connections.** An OpenAI-compatible connection to the same Ollama added nothing to the model list until it was given a prefix.
- **PhotoPrism answers a wrong password with an empty library.** `/api/v1/config` gives 200 in public mode with every count at 0, so the adapter insists on user mode and calls anything else a refused password.
- **A PhotoPrism client access token cannot list photos.** It reads the counts and may index, but every photo search answers 400 "Unable to do that"; an app password of an account works.
- **PhotoPrism answers the index call only when indexing is over.** A second start meanwhile gets 500 "Already running", and no REST answer tells that an index runs.
- **Failed sign-ins leave no trace in Pocket ID's audit log.** A wrong login code, one of the wrong length and one used twice all get 401, and the log gains nothing; version 2.14 has no event for a failed attempt, so the card shows sign-ins only.
- **No Pocket ID API key can make another one.** Creating a key with an API key gets 403 api_key_auth_not_allowed. Without a browser, a login code from `pocket-id one-time-access-token <user>` exchanged at `/api/one-time-access-token/<code>` gives the session that makes a key. STATIC_API_KEY is the other way, and it adds an administrator called Static API User to the user list, which the card leaves out.
- **A Pocket ID key of a user who is not an administrator sees neither the users nor the audit log.** Both answer 403, so the cards need an administrator's key.
- **Sportarr's `wanted` counts the coming events too.** `/api/stats` said 56 where `/api/wanted/missing` listed 40: it counts every monitored event without a file, including those still to come, so the cards take the list's total instead.
- **A made-up Sportarr key gets the same 401 as none.** `/api/health` answers without any key and cannot tell a working key from a wrong one, so the connection test asks `/api/system/status`.
- **Tandoor's shopping list hands back what was already bought.** Entries ticked off within the user's recent days (at most 14) come back with checked: true, so the card leaves them out itself.
- **A Tandoor token with the scope read is refused when it ticks something off.** Reading works with read; ticking off answered 403 until the token had read write. A missing or made-up token gets 403 as well, not 401.
- **Starting Tube Archivist's downloads answers 200 even with nothing to download.** The task runs and does nothing, so the card offers the button only while something waits and no download runs.
- **A Bearer token counts as no token at Tube Archivist.** It wants `Authorization: Token`; `Bearer` gets the same 403 as none, a wrong token 403 "Invalid token.".
- **An empty Tube Archivist queue counts as null, not 0.** `/api/stats/download/` hands out `null` for every count until something waits.
- **Wallos takes its API key only as a request parameter.** In an X-API-Key header it answered "Missing parameters". The card sends the key in the body of a POST, so it never stands in an address or an access log.
- **Wallos answers a wrong API key with HTTP 200.** A missing and a made-up key both came back as 200 with success false; only the body tells.
- **Without exchange rates Wallos adds other currencies as if they were the main one.** 15.49 USD went into the September total as 15.49 EUR, with a note about the missing Fixer key. The card then shows "Not converted" and keeps that sum out of its history.
- **Watchtower forgets its last run when it restarts.** The status answered 204 without a body until the first run and again after every restart, and the history and the metrics started from zero. A check for updates does not count as a run.
- **Watchtower counts an image no registry has neither as failed nor as skipped.** Its digest lookup got 404, and the run still reported nothing failed.
- **What's Up Docker leaves a session cookie behind when an account signs in.** After one request with the administrator's user and password, the same client got in with no credentials, a made-up token and a wrong password, and a read-only token could start a check. nexdeck therefore takes only an API token, which sets no cookie.
- **What's Up Docker crashes when an update runs on a container that has none.** The trigger answered 500 "Cannot read properties of undefined", so the card offers the button only where WUD found an update and lists a Docker trigger for that container. An updated container comes back under a new id, and the old one is gone.
- **Zabbix answers a refused token with HTTP 200.** A missing or made-up token gets a JSON-RPC error "Not authorized." inside a 200, and `apiinfo.version` refuses any request that carries the token header.
- **Zabbix's `problem.get` includes suppressed problems unless told `suppressed: false`.** The problem view of Zabbix leaves them out. Suppressing takes effect a few seconds after the call, and an unsuppress sent in between is skipped without a word.
- **The plain Zabbix User role may acknowledge.** A user with read permission on a host group acknowledges its problems; closing one needs write permission, and an event the user may not see answers exactly like one that does not exist.

## 0.11.1 (2026-09-11)

### Fixed

- **Opening a wall display's link no longer locks you out of every other board.** The link leaves a kiosk cookie in the browser, and that cookie used to win over the signed-in account: every other board, its cards and its live updates answered "This kiosk token belongs to another board", and the app said only that the board could not be loaded. Now the account and the display each count for what they grant, and the higher of the two applies. A display without a sign-in still sees its own board and nothing else.
- **nexdeck no longer fills a Reolink device's sessions.** A Reolink hub lets only a few accounts in at once and keeps a session for an hour; after a few restarts it answered "too many users are signed in". Four ways of opening a session without closing it are gone: cards that started together each logged in on their own, the Test button and the dropdowns asked of the device never logged out, saving or deleting a connection dropped its session, and a renewed session kept the old one in place for its last minute.

## 0.11.0 (2026-09-11)

### New

- **A music player card for Plex, Jellyfin and Emby.** It plays the music library of the server in the browser: the newest albums, albums, artists, playlists, a search and the queue, with the cover filling the card and lending it its colour. Plays are not reported to the server, so nothing turns up in its history.
- **The music keeps playing from board to board.** When the card is out of sight, a floating bar takes over. Drag it into any corner or fold it into a round button with a progress ring, or put the player into the top bar instead. My settings > Music player.
- **Small cards open the library beside the board.** One button opens it as a sheet with the search inside. While nothing plays the card shows four covers or one, the newest albums or some picked at random; a cover opens its album, and the round button on it plays the album.
- **Playlists are edited on the server.** Make one from a track, an album or the whole queue, add and take out tracks, rename and delete. Smart playlists on Plex stay read-only.
- **Sound quality and volume per browser.** The original file, or converted to 320 or 128 kbit/s. When a track stalls again and again, the player steps down by itself and says so. Jellyfin and Emby also make instant mixes. There is no volume slider on an iPhone or iPad, where the buttons on the side decide.
- **Who may play is who may act.** Somebody who may only look sees the card without buttons, and a kiosk plays only when its link allows actions.
- **0.9.0 and 0.10.0 were never published on their own.** Everything listed under them arrives with this release.

### Found while measuring

- **Plex lists a device for every client identifier it sees,** even when nothing is reported, and that entry cannot be deleted through its API. nexdeck always sends the same identifier.
- **Converted sound comes without a length and without Range,** from Jellyfin and from Plex alike. Skipping into such a track starts the conversion again at that second.
- **Plex refuses HLS for music** on every platform it was asked with. Jellyfin hands it out, and Safari gets converted sound from Jellyfin that way.
- **Jellyfin renames a playlist only through the item itself;** its playlist route answers 400 to an API key. Adding a track that is already in a playlist adds it a second time, so nexdeck leaves those out.
- **Emby runs untested.** It shares Jellyfin's API, and the server it was measured against held no music.

## 0.10.0 (2026-09-11)

### New

- **Five new integrations, each measured against a running instance before it was written.** All five start out of beta: every card was run against the service in throwaway containers, wg-easy with a real WireGuard client connected to it.
- **RomM:** every platform with its number of games and its size, the games added last, and a library summary.
- **NetBox:** the devices that are not active, failed ones first, how full each prefix is by the IP addresses documented in it, and an inventory of devices, sites and addresses.
- **Dawarich:** the kilometres of this month and this year, when the last point came in, and the distance of every month so far. The card warns when no point has arrived for a day, which is where a phone that stopped sending shows up.
- **wger:** your weight with the change over the last 30 days, and the latest weigh-ins with the change from the one before.
- **wg-easy:** which WireGuard clients are connected, with their traffic or when they were last seen, and how many are connected at all.

### Found while measuring

- **ArchiveBox was left out.** Its stable release 0.7.4 has no REST API; only the pre-releases do, and their number changes almost daily.
- **RomM answers a token it does not know with 500, not 401,** and its statistics need no token at all. A library scan cannot be started over the REST API.
- **NetBox answers the secret half of a v2 token with "Invalid v1 token".** A v2 token only works whole, starting with `nbt_`. A prefix carries no utilisation, so the card counts the addresses inside it.
- **Dawarich's distances lag behind its points.** After an import the points were counted at once and the distance stayed at 0 km; the job that calculates it runs every hour.
- **wger answers its API key sent as a bearer token with 500.** It has to be sent as `Token`.
- **wg-easy 15 dropped the addresses of version 14,** and only its client list carries the handshakes and the traffic.

## 0.9.0 (2026-09-11)

### New

- **Six new integrations, each measured against a running instance before it was written.** All six start out of beta: every card was run against the service in throwaway containers, and the tests carry the answers that came back.
- **Vikunja:** open tasks that are overdue, due today or due in the next days across every project, with the time they are due, and a summary of overdue, due today and open. What counts as today follows a time zone field on the integration.
- **Kimai:** the running timer first with the time it has run, then this week's entries, and a summary of the hours booked this week and today. A running timer can be stopped from the card.
- **Grocy:** products that expired, are overdue or due soon, and what fell below its minimum stock, with a pantry summary.
- **Shlink:** short URLs with their visits, most visited or newest first, and which of them no longer redirect because their validity ended or their visits are used up. The summary counts visits, bots and visits that led nowhere.
- **Meilisearch:** every index with its documents, an index whose last indexing failed first with the reason, and a summary with the documents and the size of the database.
- **Linkwarden:** the links saved last with their collection and tags, pinned ones only if wanted, and how many links, collections, pinned links and tags there are.

### Fixed

- **The buttons on the rows of the n8n and Synology cards work again.** Publishing a workflow, or starting and stopping a container or a virtual machine on a Synology, was refused with "This card is not offering any action right now." The check that a card only runs what it offered recognised a row's buttons in one of the two shapes adapters hand them over in. Found while pressing the new Kimai stop button in a browser.

### Found while measuring

- **Vikunja 2 has no `/tasks/all` any more.** An API token asking there is told its token is invalid, although it is fine. The list of tasks is `/tasks`. A token also cannot read the user's own time zone, which is why the integration asks for one.
- **Grocy lists an expired product twice,** as expired and as overdue. The list card shows it once.
- **Shlink keeps a short URL that no longer redirects in its list** without saying so, and counts the visit that met the 404 as an orphan visit instead.
- **Meilisearch answers a key that lacks a right exactly like a wrong key,** and its default read-only admin key can read every other key. The field asks for a key of its own. A failed task stays in the task list after the index has recovered, so the cards judge an index by its latest task.
- **Kimai reads the times of its filters in the user's own time zone** and refuses a time with an offset, so the card takes the zone and the first day of the week from the user.

## 0.8.0 (2026-09-11)

### New

- **Eight new integrations, each measured against a running instance before it was written.** Like the six of 0.7.0, all of them start out of beta: every card was run against the service in throwaway containers, and the tests carry the answers that came back.
- **Gitea and Forgejo:** open issues or pull requests across your repositories, the latest Actions jobs with the red ones marked, from one repository or the ones that changed last, and a summary with the number of repositories.
- **CrowdSec:** the addresses and ranges this installation blocks, with the scenario and the time left, read with a bouncer key that may read decisions and nothing else.
- **Semaphore UI:** how every template last ended, red ones first, and how many are running.
- **Karakeep:** the latest saved links and notes, and a reading list of what is not archived yet.
- **Mealie:** the meal plan from today on, what is still on the shopping list, and a kitchen summary.
- **Kopia:** every snapshot source with its last good snapshot, a failed one first with the reason.
- **Duplicati:** every backup job with its last good backup, a failed one first with the reason, and which job is running or waiting.

### Changed

- **"Failed" reads "Fehlgeschlagen" in German.** It said "Fehlversuche", which fit failed sign-ins but not a failed backup or job.

### Found while measuring

- **Kopia does not show a failed snapshot where the sources are listed.** The source stays idle with its older good snapshot; only the task list says it failed, and the call that started the snapshot answered with success. The task list is kept in memory, so a restart of the server forgets the failure.
- **Duplicati keeps an old error after a good run.** A job that failed and then ran fine still carries the error next to its new backup, so a job counts as failed only while its error is newer. The server's error flag stays on for the same reason until the notification is dismissed.
- **Gitea and Forgejo no longer agree on their list of workflow runs.** The field names, the states and even the order differ. The list of jobs answered the same on both, so the cards read that. Forgejo also names itself with the Gitea version it forked from, which the connection test leaves out.
- **CrowdSec answers no decision at all with `null`** instead of an empty list, and without a filter its list includes the whole community blocklist. The cards ask for this installation's own decisions unless told otherwise.
- **Mealie lists a meal plan in the order it was entered,** not by date.

## 0.7.0 (2026-09-11)

### New

- **Six new integrations, each measured against a running instance before it was written.** All six start out of beta: every card was run against the service itself in throwaway containers, and the tests carry the answers that came back, not the documentation's.
- **Cup:** which container images have a newer version waiting, the biggest step first, with a button that makes Cup look again. Cup checks only at start unless it has a refresh interval, so the summary says when it last looked once that is more than a day ago.
- **Healthchecks:** cron jobs and background work, down and late ones first, and a summary of how many are up, late and down. The hosted healthchecks.io works as well, and the read-only key is enough.
- **ChangeDetection.io:** watched pages with the latest change and the ones that fail, changes nobody has looked at yet, and a button that checks every watch now.
- **Miniflux:** the newest unread entries, the feeds that fail to fetch with the reason, and a summary of unread and failing.
- **autobrr:** recent releases with the filter and what the download client said, and a summary of pushed releases and the filters switched on.
- **Firefly III:** net worth, balance, spent and earned for the month or the year, which subscriptions are paid and which are due, and how full each budget is.

### Found while measuring

- **Healthchecks closes the connection after every answer without saying so.** Over a kept-alive connection, four of twenty requests sent back to back failed with "server disconnected". The adapter asks for the connection to be closed, and then none did.
- **ChangeDetection.io's watch list lacks what its documentation promises.** Neither `paused` nor `notification_muted` is in the list of 0.60.4, so a paused watch reads as not checked yet.
- **Firefly III answers a missing token with its sign-in page** unless the request asks for JSON, and a subscription made through its API counts as neither paid nor unpaid until it is switched on.
- **Cup exits at start when a single registry answers 429.** Nothing nexdeck can change; the card then says Cup cannot be reached.
- **autobrr's statistics count since its first start.** The summary does not stay red over an error from weeks ago; it warns only when no filter is switched on.

## 0.6.2 (2026-09-10)

### Changed

- **A phone shows the board in the order it was arranged.** The phone and the tablet each kept a layout of their own, written once when a card was added and never again, so arranging a board on a monitor left both as they were. Measured on a board of 25 cards: 6 stood in the same place on the phone as on the monitor, one was 15 places off, and 19 were half the width of the screen, lists included. There is now one arrangement. From 700 pixels up the board is drawn as arranged, only narrower or wider, so a wall tablet shows what was set up at the desk. Below that the cards are stacked in reading order, row by row and left to right, at the full width; two cards that are small on the wide board and equally tall share a row.
- **On a phone, edit mode leaves the order alone.** A card cannot be dragged or resized there any more, and a note says that cards are arranged on a wider screen. Settings and removing work as before, and the arrow keys still move a card in the wide arrangement.
- **Layouts saved for the tablet and the phone are no longer used.** They stay in the database and in exported files, so an older version reading the same data still finds them, and nothing saves them any more.

### Fixed

- **The demo board comes with its arrangement again.** Setting up with the demo placed every card three columns by two, in the order it was made, instead of the arrangement the demo describes. The demo appended each place to the very lists the database session keeps as the stored value, so the new value compared equal to the old one and was never written: in the database of a fresh setup, the Media page had eleven cards and not one saved position. Boards set up with the demo before keep the arrangement they show now.

## 0.6.1 (2026-09-10)

### Fixed

- **Nexview covers show again on the approval card.** nexdeck's service worker answered every request that was not for its own API by fetching it itself, pictures from other addresses included, and that fetch failed where the page's own image would have been allowed. Measured against the built image: the same poster loaded with the worker blocked and failed with it active. Nexview is the first adapter to hand the browser a picture from somewhere else, every other one goes through nexdeck's own image proxy, which is why it had not shown before. The worker now leaves anything from another address to the browser. A test in the built arrangement loads a picture from a second origin on a page the worker controls, and it failed before the fix.

## 0.6.0 (2026-09-10)

### New

- **Approve Nexview requests from the board.** A new Nexview card, **Requests to approve**, lists what is waiting with its cover and who asked for it, and approves or turns it down with one press. When a request still needs a target folder or a quality profile, pressing Approve opens a sheet with the folders and profiles of that request's own instance: a film in 4K goes to a different Radarr than the same film in 1080p, so one list for all of them would be wrong for three of the four. Where Nexview cannot say which folders there are, the row has no Approve button rather than a button with an empty list.
- **The card follows what the key may do, not the account's role.** It asks Nexview's `/api/v1/me` first. An administrator with a read-only key carries `role: admin` and still cannot approve anything, and a card built on the role builds a button that always fails. With a key that may only read, the requests are listed without buttons and the card says why; the connection test says it at setup as well.
- **A card can ask for a choice before an action runs.** An action used to carry either fixed values from the card or one free-text field. Approving needs two picks at once, from lists that differ from row to row. An action may now carry several blanks, and a blank may be a pick list the card hands over with its answer, so the guard checks the pressed value against exactly the list that was on screen, the same way it checks every fixed parameter. A list of several never starts on its first entry: "nobody chose" must not turn into a folder a title then lands in.
- **The wall display asks the same question as the board.** Both now share one confirmation sheet. They carried the same one twice, and a press on the wall on an action with blanks would have gone out half empty and come back refused.
- **The approval card's buttons show without a hover.** Most lists keep their row buttons hidden until the pointer is over the row, so a restart button on every container does not clutter the card. A wall display with a touchscreen has no pointer, and on a card whose rows exist to be pressed the buttons would never have been seen. A card now says whether its row buttons should always show.

### Changed

- **`Action.ask` is `Action.asks` now, a list.** One adapter used the single blank, MeTube, and it has been moved over.

## 0.5.2 (2026-09-10)

### Fixed

- **The board of a fresh installation comes alive after five seconds where it used to take fourteen, and the cause was one client too many.** Every service logo a card shows is fetched by the server and kept on disk, and on a new installation nothing is kept yet: the demo board asks for eleven of them at once. The proxy built a fresh HTTP client for each, and building one costs about a second, because it builds a TLS context and reads the certificate bundle. That second is not spent waiting for the network. It is spent on the event loop, so nothing else in the server moves while it passes, and eleven of them in a row cost 11.35 seconds. Recorded in a real browser: the loop stood still for 15.6 of 20 seconds, the live stream needed 5.4 s before it was open, and the board answer that carries the first data of every card came back after 14.3 s. It comes back after 5.6 s now. What this looked like from a chair: a board full of cards that stayed empty, and a button card that led nowhere, because a card shows nothing until its first answer arrives and a button card carries where it leads in that answer.
- **A message no longer swallows the press meant for the button underneath it.** The message bubble sits in the bottom right corner for five seconds, and that is exactly where a settings sheet keeps its Save button. A press meant for Save landed on the message. On screen that is "I press Save and nothing happens", and the natural response is to press again, which does not help either. Nothing inside a message is there to be clicked except its own close button, so the bubble lets presses through now and the close button keeps its own.
- **A notification, a web push, a sign-in and the look for a newer version no longer stop the server for a second each.** The same client-per-call as above, in four quieter places. Somebody with a phone, a tablet and two browsers paid four seconds of a stopped server for one notification; the update check is the one an administrator presses by hand and then watches. All five places now keep one client for the life of the process, the way the reachability checks have since 07.09.2026, and a test counts the clients so it cannot come back.

## 0.5.1 (2026-09-09)

### Fixed

- **A setting made in a card no longer jumps back, and this time the cause was measured rather than guessed.** Two roads carry the same card into the browser: the stream pushes each answer as the server makes it, and every board request brings a snapshot of the whole board along. They arrive in whatever order the network feels like. Recorded in a real browser: saving a card sent the new answer over the stream 120 ms later, and a board request that had started 40 ms *before* the save answered 20 ms after that, carrying the state from before it. The older snapshot won. On a card the server reads every fifteen seconds nobody notices; on a clock, whose next fetch is an hour away, the old settings stay until the page is reloaded. An answer older than the one already on screen is now turned away, whichever road it came by.
- **A card's own answer cannot be overtaken by one already in flight.** Changing a widget's settings cancels its running fetch, but a cancel only takes effect at the next await, and between the adapter answering and the answer being published there is none. So a fetch made with the settings from before the save could still be put on the board. The collector now counts a widget's settings changes and throws away an answer that belongs to an older count.
- **A card whose settings changed at the wrong moment kept refreshing.** The check above answered the widget loop with "this widget is gone", which is how a deleted card stops its task, so the card would have sat unchanged until the next restart with nothing saying why. Found while testing the check itself.
- **A saved card keeps what was saved until the board really carries it.** It used to be released as soon as a board request came back, and a request already in flight comes back with what the server had before the save.

## 0.5.0 (2026-09-09)

### New

- **A card can bring its own history.** Every chart so far drew what nexdeck collected, which stops after 24 hours because that is how long the minute rows are kept. A card can now hand over a history of its own, with real timestamps, and have it drawn as a line or as bars. Speedtest Tracker is the first: **History**, over 24 hours, 7, 30 or 90 days, download, upload or both. The door this opens is the point: Prometheus, Proxmox's own statistics and Tautulli all keep more than a day.
- **A failed measurement is a gap.** The line breaks where a run failed instead of dipping to the floor, which would draw an outage that never happened. The scale starts at nought for the same reason: from the lowest reading, a three percent wobble looks like a cliff.
- **Proxmox VE, Speedtest Tracker and Immich leave beta**, all three confirmed against live instances.
- **MeTube, with a field you type an address into.** A card with a text field and a button: paste a video address, press, and MeTube fetches the file. Two more cards beside it, **Downloads** and **Download count**, with a button per row to remove an entry or try a failed one again. MeTube has no login of its own, so the connection asks for an address and nothing else.
- **A card may leave one blank for whoever is standing in front of it.** Every action in nexdeck is reachable only because the card put it in its last answer with exactly those parameters, and free text has no fixed value to compare. So the adapter declares the blank: which single parameter it is, and what may go in it. Everything else about the action still has to match what was offered, and the typed value is checked before any adapter sees it. An address gets the rule a member-supplied address gets everywhere else in nexdeck: http or https, a host, nothing that only answers to the server itself.
- **A row can hand its file to the browser.** MeTube fetches to the server, which is where the file then sits. A finished row now carries a save button beside its bin, and the bytes come through nexdeck rather than from a link to the service: across origins the browser ignores a download link and plays the video in a tab instead, and on a homelab where only nexdeck is published it could not reach the service at all. What may be asked for is the list the card last delivered, the same guard the actions have.

### Fixed

- **The bin button removed nothing and said it had.** MeTube keeps its lists under the address of a download, while the id it prints on the row is the video's own; asked to delete by that id it answers ok and does nothing. It got past the first round of tests because the fixtures carried no address at all, so the adapter fell back to the id and the wrong thing looked right.
- **A button said what it did in English.** Adapters answer in English, the way they write every label, and cards translate those by wording. The one sentence a button produces was the exception: "Removed." stood in English on a German board, in the one place the eye goes right after a press. A sentence the service itself wrote back stays as it came, which is right: that is MeTube speaking, not nexdeck.
- **A waiting row says so in our own words.** "Preparing" came straight from MeTube, and a word taken from a service is a word no translation file has.
- **The scan button was a grey box.** `refresh-cw`, the symbol on the "look for new files" button shipped in 0.4.0, was not in the set the frontend bundles, and the fallback for an unknown symbol is a grey square that looks like an icon which failed to load. A guard now walks every symbol an adapter puts on a button, not only the logo beside a card's title.
- **The history card pages, because the tracker ignores `per_page`.** Measured: 5 and 500 both answer with 25. Asking once would have shown the last 25 measurements and labelled them 90 days.
- **Which end of the list is the newest is asked, not assumed.** It is undocumented, and the tracker this was written against holds two results on one page, so it could not be measured. The card reads the first and the last page and compares the timestamps; walking the wrong way would draw the oldest measurements under the words "the last 7 days".

## 0.4.0 (2026-09-08)

### New

- **A card can be asked to draw itself differently.** Three drawings on top of the one an adapter picked: a list becomes **bars**, measured against its largest row; a card that knows what its slices are becomes a **ring**; and a card that records two numbers or more becomes a **chart** of both. The choice sits in the widget settings under View, next to the dial that was already there. 91 list cards, 63 cards with two metrics and 5 with slices offer one today, and no adapter had to be edited for the first two: the rule lives in `WidgetType`, the way the row tick boxes already did.
- **Plex's server load card can be a dial.** It carries four percentages, and a dial shows one, so the settings sheet asks which: Plex's CPU or memory, or the host's. The same three pieces the Synology system card has had since it learned the trick, plus a tick box per row, so the rows a dial does not show can be taken off the card instead of sitting under it unread.
- **Look for new files, from the card.** Plex, Jellyfin and Emby have a **Libraries** card: one row per library, and a button that asks the server to look for new files. On Plex the button sits on every row; on Jellyfin and Emby only on the card, because only reading everything works there. Jellyfin and Emby say in the same answer which library is being read and the card shows it, with a progress bar; Plex reports that nowhere but its activity list, so its rows stay quiet about it.
- **A button card can trigger an action.** The third thing it does, next to opening a board and opening an address: pick a connection, pick what it offers, pick what it acts on, all three from lists. A library is "section 7" on one server and an item id on the next, so nothing is typed, and a name written by hand would point at nothing the day it is renamed.
- **What a button may reach is declared by the adapter, not by the card.** Every other action in nexdeck is reachable only because the card that offers it put it in its last answer, which is the guard from 0.2.0; a button's answer comes from its own options, and those are written by whoever may edit the board. So adapters declare a short allowlist: three do, with one action between them. On a press the target is checked again against the list the service itself hands out, because a target that is not on it either never existed or is gone.
- **What works, measured against the three real servers.** Plex scans one section and says "Scanning Films" in its activity list two seconds later. Jellyfin and Emby answer 204 to `POST /Items/{id}/Refresh` on a library and then do nothing at all: the scan task does not run, `RefreshStatus` never moves, and `metadataRefreshMode=ValidationOnly` changes neither. Only `POST /Library/Refresh` runs there, and it reads everything. None of that is in the specification, which names all three calls without saying which has an effect. So the card offers per library only where per library works: a button labelled "Films" that quietly reads every library would be worse than no button.
- **The dangerous switches are never named.** `replaceAllMetadata` and `replaceAllImages` default to false on Jellyfin and Emby, and the call sends neither, so a scan looks for files and leaves what is there alone. Plex's `force=1` is its rewrite of the metadata and is not sent either. Two tests hold both, because the safe call and the destructive one are one query parameter apart.
- **The ring is declared, never guessed.** Only a fetch knows what its numbers are parts of, so only a fetch writes the slices. Pi-hole's card shows queries, blocked and clients, and blocked is already inside queries: adding the three would draw a whole that is nowhere in the world. A card that has not worked its slices out stays what it was.

### Fixed

- **A saved change jumped back to the old one.** Pick a look in a card's settings, save, and the card showed the new look for a moment and then the old one until the page was reloaded. `onSaved` sets a hold on the preview so the card keeps the new options until the server has fetched with them; a tick later the sheet refetches the widget, finds its draft options equal to the saved ones, and reports "nothing to preview any more", which cleared the hold. The card then fell back to the collector's last answer, which still had the old options. It had been that way for as long as the sheet has had a preview.
- **The connection picker on a button offered all twenty-eight connections**, though its own help text says "only connections that offer something a button may trigger" and twenty-five of them offer nothing. It names the three that declare an action now, built from the registry rather than written out, so it cannot go stale the day a fourth one does.
- **A demo connection said it had nothing to offer.** Its address is `demo.invalid`, so asking it for a list asked nothing, and the sheet drew the honest conclusion from an answer that was not one. Demo connections answer from their own invented data now, which is where the card's rows come from anyway.
- **Synology's virtual machines were measured against the wrong thing.** The memory of a guest was divided by what it was assigned instead of by the host's, so a healthy machine reported itself 102% full; a cap at 100 and a comment calling the overshoot "overhead" kept it looking deliberate. The processor load came out ten times too high on the list card and was left out of the single card entirely, on a docstring saying the API reports none. Both figures now match what the Virtual Machine Manager shows for the same guest, held against a live DSM.
- **The machine picker offered Docker containers.** Both Synology cards asked a field called `which` and got one merged list, so picking a container on the machine card answered "there is no machine called immich_postgres". Two questions, two lists; a card saved before the split keeps its choice.
- **A button's look waited for the server.** How a card is drawn is nothing a service knows, but `look` and `colour` came back from a fetch, so choosing "symbol only" changed nothing until the page was reloaded. The card reads its own options now, which is also what makes the choice visible while it is being made.
- **Proxmox answered with no node and looked healthy.** With Privilege Separation on, a token inherits nothing from its user, and `/nodes` is then HTTP 200 with an empty list: the summary read "0 / 0 guests, 0 nodes". It says what happened now, and names the permissions. The single-guest card no longer asks for the node list it never used.
- **A fresh Speedtest Tracker failed its connection test.** It asked `results/latest`, which an installation that has not measured yet does not have, and blamed the address for a 404. It asks the list and reads the status code, so an empty tracker tests green.
- **UniFi's switch card had no demo of its own.** It fell through to the console summary, so in demo mode a switch showed the network's numbers and an empty port list. Nothing threw, so nothing said so, and the demo board is where the screenshots on the project page come from.
- **The chart drew one line of however many it had.** It took the first metric and threw the rest away. UniFi's console measures WAN in and WAN out, the server has stored both since the day it was written, and the card drew one; putting two cards side by side to compare them gave each its own scale, so the comparison was wrong as well as awkward. Every line is drawn now, on one scale, with a legend that names them the way the card does.

### The test bench

- **79 tests for the drawings, the library scan and the action button**, each held against a mutation: twenty-eight mutations, twenty-eight caught, judged on the return code rather than on the word "failed" in the output. Six are about refusing to draw (bars of rows that carry "2.5 s", a ring whose slices are all nought); five are about refusing to destroy (a library id carrying a path, Plex's `force=1`, Jellyfin's `replaceAllMetadata`, an action no adapter declared, a target the service does not know). One mutation was itself broken and passed for the wrong reason: `[] or [x]` is `[x]`, so it changed nothing. It was written again.
- **A guard against a demo that answers with another card's data.** A `demo` is a chain of `if widget_kind == ...` with a fall-through at the end, so a kind added to `widgets` and forgotten in `demo` does not fail: it quietly returns whatever the last branch makes. The guard compares the shape of every demo against the others of the same adapter, and ignores two cards drawn by the same renderer, because two poster walls carry the same fields on purpose. It found UniFi's switch on its first run.
- **The loose-key guard learned what a widget kind is.** It reads any `'a.b'` string whose first part names a section of `en.json`, and `kind: 'plex.load'` is shaped exactly like one. The value of a `kind:` property is skipped now, and only that: a section-wide exception would have blinded it to every loose `plex.*` string there is. The skip has a floor of its own, so it cannot quietly become dead code, and the guard was measured against a real loose key afterwards.

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
