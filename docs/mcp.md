# AI from outside: MCP

nexdeck speaks the Model Context Protocol, so a program such as Claude Code, claude.ai or any other MCP client can look at your boards: what needs a look, what a card shows, what happened lately and how a number moved. With the level for it, it can also press the buttons cards offer, and you decide each press in nexdeck before it runs. A program acts as the account that connected it and never sees more: only the boards that account may open, and fewer if the key is limited to some of them.

MCP is off until an administrator switches it on.

## Switching it on

An administrator opens **System > AI from outside (MCP)** and sets:

- **Allow MCP.** Off out of the box. While it is off no key works, and `/api/mcp` answers 404 as if it did not exist. Keys are kept and work again when it is switched back on.
- **Highest level.** `Read` or `Read and act` (the default). No key goes above it: lowering it holds for keys made before as well.
- **Allow connectors.** Off out of the box. On, a program can ask a signed-in person for access over OAuth instead of being handed a key (see [Connecting a program](#connecting-a-program)). Switching connectors off, or MCP as a whole, ends every connector at once; they do not come back with the switch, their accounts connect them again.
- **Blocked tools.** A blocked tool is gone for every key: it is missing from `tools/list` and answers like a tool that does not exist. Nothing is blocked out of the box.
- **All keys.** Every key and connector of every account, with its owner. Revoking one here ends it at once.

## Making a key

Every account that is not a guest makes its own keys under **My settings > AI from outside (MCP)**:

- **Name**, such as "Claude Code on my laptop". Up to 80 characters.
- **Level.** `Read` looks at cards, the chronicle and history. `Read and act` may also press card buttons. The form offers only what the administrator allows, and starts at `Read`.
- **Expires** after 30, 90 (the default) or 365 days, or never.
- **Boards.** All boards the account may see, later ones too, or only the ones you tick. A board the key was not given does not exist for it.

The key is shown once, right after it is made, with two lines to copy: one for Claude Code and one as JSON for other programs. nexdeck keeps only its SHA-256 and its first characters, to tell keys apart in the list. The list shows each key's level, boards, when it was last used and when it runs out; connectors stand in the same list with the name of their program.

An account holds at most 20 keys and connectors. A revoked or expired key does not count; a connector counts as long as it can still refresh. Revoking a key ends it at once, and the key cannot come back.

## Connecting a program

The endpoint is `https://<your nexdeck>/api/mcp`. The transport is "Streamable HTTP" without streams: every request is a `POST` and gets its answer as JSON, a notification gets `202`, and `GET` gets `405`. The protocol versions `2025-06-18`, `2025-03-26` and `2024-11-05` are spoken. No session is kept; every request names its key.

### Claude Code with a key

```
claude mcp add --transport http nexdeck https://deck.example.com/api/mcp --header "Authorization: Bearer ndm_..."
```

This is the line the key page offers to copy, with your address and the key filled in.

### Other programs with a key

A program that takes a JSON list of remote servers usually wants this:

```json
{
  "mcpServers": {
    "nexdeck": {
      "type": "http",
      "url": "https://deck.example.com/api/mcp",
      "headers": { "Authorization": "Bearer ndm_..." }
    }
  }
}
```

A quick check from a shell:

```
curl -s https://deck.example.com/api/mcp \
  -H "Authorization: Bearer ndm_..." -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### As a connector, over OAuth

With connectors allowed, a program needs only the address. In Claude Code:

```
claude mcp add --transport http nexdeck https://deck.example.com/api/mcp
```

Then type `/mcp` in Claude Code, choose `nexdeck` and **Authenticate**. The browser opens nexdeck's consent page (`/connect`). Sign in if you are not, check the program and the address it returns to, choose the level (it starts at `Read` and goes no higher than the administrator allows) and the boards, and allow it. The connector then stands in your list of keys, where you set its rights per tool and revoke it like any key.

claude.ai and other hosted programs connect the same way, but they reach nexdeck from the internet: nexdeck must be reachable over HTTPS at a public address, and that address must be set under **System > Address** or in `NEXDECK_PUBLIC_URL`. Every address nexdeck names to a program (in the metadata and in the 401) comes from that setting; without one, from the request as it arrived (see [Behind a reverse proxy](#behind-a-reverse-proxy)).

What the program does by itself:

- The 401 of `/api/mcp` names `/.well-known/oauth-protected-resource` (RFC 9728), which names nexdeck as its own authorization server, described at `/.well-known/oauth-authorization-server` (RFC 8414).
- It registers itself at `/api/mcp/oauth/register` (RFC 7591): public programs only, with 1 to 10 return addresses.
- It sends you to `/api/mcp/oauth/authorize`, which always hands you on to the consent page, with PKCE (S256).
- It trades the code at `/api/mcp/oauth/token` and gets an access token for an hour and a refresh token for 30 days. `/api/mcp/oauth/revoke` (RFC 7009) ends a connector from the program's side.

Signing the same program in again from the same account replaces its connector and keeps the rights per tool you set for it.

## Tools

| Tool | Group | Level | Out of the box | What it does |
|---|---|---|---|---|
| `needs_attention` | Reading | Read | Allow | What needs a look right now: yellow and red cards with their reason and since when, failing reachability checks, and the unread warnings of the account's bell (left out for a key limited to some boards, because the bell speaks of every board). |
| `find_cards` | Reading | Read | Allow | Finds cards by title, service, kind or board, up to 60, each with its id, colour, reason and headline number. |
| `card_details` | Reading | Read | Allow | Everything one card shows: colour and reason, numbers, up to 25 rows, and the buttons it offers right now with their action ids and parameters. |
| `chronicle` | Reading | Read | Allow | What changed lately, newest first: colour changes, outages, maintenance, new versions, restarted containers, changes made in nexdeck. Up to 720 hours back. |
| `metric_history` | Reading | Read | Allow | How one number of a card moved over the last hours (at most 24): lowest, highest, average, latest and a few points. |
| `diagnosis` | Administration | Read, administrators only | Deny | Why a service is in trouble, as its diagnosis page shows it. A key limited to some boards hears only about the cards, lines and buttons of those boards. |
| `container_log` | Administration | Read, administrators only | Deny | The last lines of one container's log, from a card that lists the container, with secrets masked as well as can be done. |
| `press_button` | Card actions | Read and act | Ask | Presses a button a card offers right now. See [Pressing buttons](#pressing-buttons). |
| `request_status` | (always there) | Read | Allow | How a press stands that waits for approval, and what came of it. Every key has it; it cannot be denied or blocked, and it answers only about the key's own requests. |

`tools/list` marks every tool but `press_button` with `readOnlyHint`, and `press_button` with `destructiveHint`. Times in answers are given on the clock of the server (`TZ`), with their offset.

A card or board the key may not see answers exactly like one that does not exist.

## Rights per tool

Under each key, **Rights per tool** sets for every tool:

- **Allow**: it runs at once.
- **Ask me first**: the call waits for your answer in nexdeck.
- **Deny**: the tool does not exist for the key. It is missing from `tools/list`, and calling it answers like a tool that does not exist.

Reading and administration tools only look, so they are allowed or denied, never asked for. A tool above the key's level, one for administrators on an account that is not one, and one the administrator blocked are greyed out with the reason, and do not exist for the key whatever its right says.

## Pressing buttons

`press_button` takes `card_id`, `action` and `params`. It checks what a press in the browser checks: the account needs the right to act on the card's board (cut down to the key's boards), and the card must offer exactly this button with these parameters right now. Otherwise the program is told to look at `card_details` again.

- **Allow**, and the button is not dangerous: it is pressed at once, and the program gets the button's answer.
- **Ask me first**, or a **dangerous button** (a stop, a shutdown, anything the card marks as such) even where pressing is allowed: nothing is pressed. nexdeck keeps the request with its arguments fixed (as canonical JSON with a SHA-256), and the program gets a request number and the time it runs out.

A request shows up in the bell of the account, with **Allow** and **Decline** right there, and on its own page (`/mcp/requests/<id>`) with the program, the tool, card, board, row and button, the parameters, what it would hit (the same facts as the confirmation of a press in the browser), and until when you can answer. A channel under **My settings > Notifications** that subscribes to "A program asks to press a button" gets the request as a message too.

A dangerous button cannot be allowed with one click: the bell offers **Review** and **Decline**, and on the request page **Allow** asks a second time.

Nothing happens until you answer. **Allow** presses exactly what was asked, with the rights as they stand at that moment: the key must still be valid, MCP still on, the tool still allowed and not blocked, the account still allowed to act on the board, and the card must still offer the button. If any of that changed, the request ends as failed with "This is no longer possible". A request runs out after **10 minutes**. At most 20 requests wait for one account, and 10 for one key; past that the program is told to wait.

The program learns what came of it with `request_status`: `waiting`, `approved` with the button's answer, `declined`, `expired` or `failed` with why.

Every press over MCP is written in the action log like a press in the browser, as `<key> (MCP)` and, when somebody allowed it, `approved by <name>`. The chronicle gets a line such as "Restart on Running containers by Claude Code (MCP), approved by Kim", and the bell tells you the result. Decided requests are swept together with the action log (`NEXDECK_KEEP_ACTION_LOG_DAYS`); a waiting one runs out first.

## Security

**Walls of `/api/mcp`, in this order:**

1. A request that carries an `Origin` header is refused with 403. Every browser sends one, MCP programs do not, so no web page can use a key it got hold of, and DNS rebinding goes nowhere.
2. MCP switched off: 404, for every method, even with a valid key.
3. No key, or one that is wrong, revoked, expired or otherwise stopped (below): 401 with `WWW-Authenticate: Bearer`, naming the resource metadata when connectors are allowed.
4. More than 240 requests a minute with one key: 429 with `Retry-After: 60`.
5. An `MCP-Protocol-Version` header naming a version not spoken here: 400.
6. A message over 1 MB: 413. JSON that does not parse: 400.

Then for each call: a tool the key does not have answers like an unknown one, and arguments that do not fit the tool's schema (nested deeper than 10, a text over 2000 characters, a request over 64 kB) are refused before anything runs or waits. The session cookie of a browser counts for nothing at this address, and neither does an API token.

**What stops a key.** A key acts as its account, as that account stands at each request:

- A new password ends every key and connector of the account, as it ends every session and API token. Disabling an account does the same.
- A key of an account that is disabled, or was made a guest, stops working. Guests cannot make keys at all.
- While the installation asks for a second factor the account has not set up, its keys wait, as its API tokens do.
- The level never goes above the administrator's highest level, and a key with chosen boards never sees others, also when the account gets more.

**Tokens.** Everything a program holds starts with a prefix, so it can be told apart and found in a log:

| Prefix | What it is | Lasts |
|---|---|---|
| `ndm_` | A key made by hand, 43 random characters after the prefix | 30, 90 or 365 days, or until revoked |
| `ndo_` | A connector's access token | 1 hour |
| `ndr_` | A connector's refresh token | 30 days, used up by each refresh |
| `ndc_` | The code a connector trades for its tokens | 10 minutes, once |

Only SHA-256 hashes of them are stored. Each travels in `Authorization: Bearer`, never in an address, and the log masks all four wherever they appear in a line (`ndm_***`). The log (`nexdeck.mcp`) records every call with the tool and the key's number, never the arguments.

**Connectors (OAuth).**

- PKCE with S256 is required, nothing else. Programs are public clients; a program that wants a client secret is refused.
- The `resource` (RFC 8707) must be this nexdeck's `/api/mcp`, at the authorization request, the consent, the code trade and every refresh.
- Return addresses: `https://` anywhere, or plain `http://` to `localhost` or `127.0.0.1` on any port; never a fragment or a user in the address, and only exactly the addresses the program registered. The authorization endpoint never redirects to the program itself: every mistake lands on the consent page, which explains it and offers a way back only to a registered address.
- The consent needs a session signed in with a password: not an API token, not a session opened on the home network without one. Guests cannot connect programs.
- A code is good once and for 10 minutes. Brought a second time, it ends the connector the first trade made.
- The refresh token changes with every refresh. A used one brought again means somebody holds a copy: the whole chain ends, connector included, and the account connects the program again.
- A new password, a disabled account or a guest role ends a connector at once (its access token gets 401, its refresh is refused). A second factor that is owed makes it wait. Revoking it in the list, or switching connectors or MCP off, ends it too.
- A request the account allowed in the bell still runs after the connector's access hour, as long as the connector can refresh.
- Registering needs no account, so it is limited: 10 an hour from one sender (an IPv6 sender counts by its /64), 30 a minute for the whole server, and at most 500 programs. Past that only a program nobody uses that is older than an hour makes room; one in use is never pushed out. Behind a reverse proxy the sender is read through `NEXDECK_TRUSTED_PROXIES`.

## When something does not work

| Answer | What it means |
|---|---|
| 401 | No valid key: wrong, revoked or expired, a password changed since it was made, the account disabled, a guest, or a second factor it still owes. A connector's access token after its hour (the program refreshes by itself) or after connectors were switched off. Make a new key or connect the program again. |
| 403 `origin_refused` | The request carries an `Origin` header: it came from a web page, or a proxy adds the header. |
| 404 | MCP is switched off under System, or connectors are (for `/.well-known/...` and `/api/mcp/oauth/...`). |
| 429 | More than 240 requests a minute with one key: wait a minute. On registration: too many programs registered from one sender or at once. |
| 400 `protocol_version` | The program asks for a protocol version nexdeck does not speak. |
| "No tool called ..." | The tool is denied for the key, above its level, for administrators only, or blocked by the administrator. |
| "No such card." | The card is on a board the key or its account may not see, or it does not exist. |
| "This is no longer possible: ..." | A request was allowed, but since it was asked the key, the account's right on the board, the tool or the button went away. |

### Behind a reverse proxy

- **`/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` must reach nexdeck.** A proxy that answers `/.well-known/` itself, for its certificates say, has to pass these two through. So must anything in front of nexdeck that asks for a sign-in of its own: programs cannot pass it, so `/api/mcp`, `/api/mcp/oauth/` and `/.well-known/oauth-` must go through untouched, with their `Authorization` header.
- **Name the proxy in `NEXDECK_TRUSTED_PROXIES`.** Without a public address, the addresses nexdeck names to a program take their scheme and host from `X-Forwarded-Proto` and `X-Forwarded-Host`, and those are believed only from a named proxy. A program then gets `http://` or the internal host name and fails. The same list lets the limit on registrations count each sender instead of the proxy. Setting the public address under **System > Address** (or `NEXDECK_PUBLIC_URL`) is the surer way.
- Connectors are tested with nexdeck at the root of its host (`https://deck.example.com`). Under a sub-path, a program that looks for the server metadata the way RFC 8414 describes does not find it.

## Addresses

| Address | Purpose |
|---|---|
| `POST /api/mcp` | The MCP endpoint, with a key or a connector's access token. |
| `GET /api/v1/mcp/status` | Whether MCP and connectors are on, the highest level, and the endpoint programs use. |
| `GET /api/v1/mcp/tools` | Every tool with its group, level, default right, and whether it is blocked or for administrators only. |
| `GET`, `POST /api/v1/mcp/keys` | The own keys; make one with `name`, `level`, `expires_days` (30, 90, 365 or `null`) and `boards` (`null` for all). Only from a session, not from an API token. |
| `PUT /api/v1/mcp/keys/{id}/rights`, `DELETE /api/v1/mcp/keys/{id}` | Set the rights per tool, revoke a key. |
| `GET /api/v1/mcp/requests`, `GET .../{id}`, `POST .../{id}/approve`, `POST .../{id}/decline` | The own requests (`?status=waiting` and so on), one of them, and the answer to it. |
| `GET`, `PUT /api/v1/mcp/admin`, `GET /api/v1/mcp/admin/keys`, `DELETE /api/v1/mcp/admin/keys/{id}` | The administrator's switches, every key, revoking any of them. |

The interactive documentation at `/api/docs` lists them with their fields.
