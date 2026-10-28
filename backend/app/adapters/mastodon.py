"""Mastodon: your own server's users and posts, what waits for a moderator, and your own account.

⚠️ **Not run against Mastodon.** A test server wants PostgreSQL, Redis, a web
process, a streaming process and Sidekiq: far more than one measuring
container. This is built from Mastodon's API documentation, the answers in the
tests have the documented shape, and the card is a beta for that reason.

What the documentation says and this relies on:

- ``GET /api/v2/instance`` (no sign-in) gives ``title``, ``version``,
  ``usage.users.active_month`` and ``registrations`` (``enabled``,
  ``approval_required``). The counts of users and posts are only in
  ``GET /api/v1/instance``, ``stats.user_count``, ``status_count`` and
  ``domain_count``, which Mastodon calls deprecated but still answers.
- ``Authorization: Bearer <access token>`` of an application made under
  Preferences > Development. The scope ``read`` covers the own account;
  ``admin:read:reports`` and ``admin:read:accounts`` the moderation, for a user
  with the role that may manage reports and users.
- ``GET /api/v1/admin/reports?resolved=false`` lists the open reports, each
  with ``category`` (spam, violation, legal, other), ``comment`` and
  ``target_account.account.acct``. ``GET /api/v1/admin/accounts?status=pending``
  lists the sign-ups waiting for approval with their ``invite_request``. Both
  page by ``Link`` and take ``limit``; the cards read the first page, so a
  count of the full page is shown with a plus.
- ``GET /api/v1/accounts/verify_credentials`` gives ``followers_count``,
  ``following_count``, ``statuses_count`` and ``last_status_at`` (a day, not a
  time). ``GET /api/v1/notifications/unread_count`` (Mastodon 4.3) gives
  ``{"count": n}``; before that the unread ones are those after the marker of
  ``GET /api/v1/markers?timeline[]=notifications``.
"""

from __future__ import annotations

import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)

#: A page of a listing; a full page is "at least that many".
PAGE = 40
CATEGORIES = {"spam": "Spam", "violation": "Rule violation", "legal": "Legal", "other": "Other"}
REGISTRATIONS = ("Closed", "Open", "Needs approval")


def _text(value: Any, size: int = 100) -> str:
    return " ".join(str(value or "").split())[:size]


def _acct(account: Any) -> str:
    """The name of an account, with the domain when it lives on another server; also of an admin account that holds one."""
    if isinstance(account, dict) and isinstance(account.get("account"), dict):
        account = account["account"]
    return str((account or {}).get("acct") or (account or {}).get("username") or "?") if isinstance(account, dict) else "?"


class MastodonAdapter(Adapter):
    kind = "mastodon"
    label = "Mastodon"
    category = "feeds"
    description = "Users and posts of your own Mastodon server, reports and sign-ups waiting for a moderator, and your own account."
    icon = "mastodon"
    docs_url = "https://docs.joinmastodon.org/api/"
    keywords = ("fediverse", "social")
    #: Built from the documentation; never run against Mastodon.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://social.example.com"),
        Field("token", "Access token", type="password", secret=True,
              help="Preferences > Development > New application, with the scope read for your account, and admin:read:reports and admin:read:accounts for the moderation. Not needed for the server figures."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="server",
            label="Server",
            description="Users, posts, users active this month and servers it knows, and whether people can sign up.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=900,
            metrics=("users", "posts", "active"),
        ),
        WidgetType(
            kind="moderation",
            label="Moderation",
            description="Open reports and sign-ups waiting for approval, reports first, each with what it is about.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=300,
            metrics=("reports", "signups"),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="account",
            label="My account",
            description="Followers, accounts you follow, posts, your last post and your unread notifications.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("followers", "posts", "unread"),
        ),
    )

    # -- asking Mastodon ---------------------------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, signed: bool = True,
                   optional: bool = False, cache: float = 30) -> Any:
        """The JSON of an address. With ``optional`` a 404 or 410 is None, for what an older Mastodon does not have."""
        headers = {"Accept": "application/json"}
        token = str(config.get("token") or "").strip()
        if signed:
            if not token:
                raise AuthFailed("This card needs an access token.")
            headers["Authorization"] = f"Bearer {token}"
        response = await ctx.request("GET", f"{base_url(config)}{path}", params=params, headers=headers, verify=not config.get("insecure"),
                                     cache_seconds=cache, timeout=25, auth_errors=False)
        if response.status_code == 401:
            failure = AuthFailed("Mastodon rejected the access token.")
            failure.hint = "A token made under Preferences > Development; revoking the application ends it."
            raise failure
        if response.status_code == 403:
            failure = AuthFailed("This token may not read that.")
            failure.hint = "The moderation needs the scopes admin:read:reports and admin:read:accounts and a user who may manage reports and users."
            raise failure
        if optional and response.status_code in (404, 410):
            return None
        if response.status_code == 429:
            raise AdapterError("Mastodon is limiting the requests.", code="rate_limited", hint="Give the cards a longer interval.")
        if response.status_code >= 400:
            raise AdapterError(f"Mastodon answered with HTTP {response.status_code}.", code="http_error",
                               hint="The URL is the address of the server, such as https://social.example.com.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Mastodon did not answer with JSON.", code="not_json", hint="The URL probably points at a web page or a reverse proxy.") from error

    async def raw_signed(self, config: dict[str, Any], ctx: Context) -> tuple[dict[str, str], dict[str, Any], tuple[str, str] | None] | None:
        """The access token as a bearer token; the kind's own test asks the public instance first and is not needed for it."""
        token = str(config.get("token") or "").strip()
        return ({"Authorization": f"Bearer {token}"}, {}, None) if token else ({}, {}, None)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/api/v2/instance", signed=False, optional=True, cache=0) or await self._get(config, ctx, "/api/v1/instance", signed=False, cache=0)
        if not isinstance(info, dict) or "version" not in info:
            raise AdapterError("This address answers, but not the way Mastodon does.", code="not_mastodon")
        version = str(info["version"]).split(" ")[0]
        if str(config.get("token") or "").strip():
            me = await self._get(config, ctx, "/api/v1/accounts/verify_credentials", cache=0)
            return f"Mastodon {version} accepts the token of {_acct(me)}."
        return f"Mastodon {version} answers; the server figures need no token."

    # -- the cards --------------------------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "server":
            old = await self._get(config, ctx, "/api/v1/instance", signed=False)
            new = await self._get(config, ctx, "/api/v2/instance", signed=False, optional=True)
            return self.server_card(old, new, link)
        if widget_kind == "account":
            me = await self._get(config, ctx, "/api/v1/accounts/verify_credentials")
            unread = await self._unread(config, ctx)
            return self.account_card(me, unread, link)
        reports = await self._get(config, ctx, "/api/v1/admin/reports", {"resolved": "false", "limit": PAGE})
        signups = await self._get(config, ctx, "/api/v1/admin/accounts", {"status": "pending", "limit": PAGE})
        return self.moderation_card(reports, signups, max(1, min(30, int(options.get("limit") or 8))), link)

    async def _unread(self, config: dict[str, Any], ctx: Context) -> tuple[int, bool] | None:
        """How many notifications are unread, and whether that is only the first page of them."""
        counted = await self._get(config, ctx, "/api/v1/notifications/unread_count", {"limit": 100}, optional=True)
        if isinstance(counted, dict) and isinstance(counted.get("count"), int):
            return int(counted["count"]), False
        markers = await self._get(config, ctx, "/api/v1/markers", {"timeline[]": "notifications"}, optional=True)
        last = ((markers or {}).get("notifications") or {}).get("last_read_id") if isinstance(markers, dict) else None
        if not last:
            return None
        newer = await self._get(config, ctx, "/api/v1/notifications", {"since_id": str(last), "limit": PAGE})
        return (len(newer), len(newer) >= PAGE) if isinstance(newer, list) else None

    @staticmethod
    def server_card(old: Any, new: Any, link: str | None = None) -> WidgetData:
        old = old if isinstance(old, dict) else {}
        new = new if isinstance(new, dict) else {}
        stats = old.get("stats") if isinstance(old.get("stats"), dict) else {}
        users, posts = int(stats.get("user_count") or 0), int(stats.get("status_count") or 0)
        active = int((((new.get("usage") or {}).get("users") or {}).get("active_month")) or 0)
        registrations = new.get("registrations") if isinstance(new.get("registrations"), dict) else {}
        if registrations:
            way = REGISTRATIONS[(2 if registrations.get("approval_required") else 1) if registrations.get("enabled") else 0]
        else:
            way = REGISTRATIONS[(2 if old.get("approval_required") else 1) if old.get("registrations") else 0]
        secondary = [{"label": "Posts", "value": posts}]
        if active:
            secondary.append({"label": "Active this month", "value": active})
        secondary += [{"label": "Servers known", "value": int(stats.get("domain_count") or 0)}, {"label": "Sign-ups", "value": way},
                      {"label": "Version", "value": str(old.get("version") or new.get("version") or "?").split(" ")[0]}]
        return WidgetData(
            status="ok",
            primary={"label": "Users", "value": users},
            secondary=secondary,
            metrics={"users": float(users), "posts": float(posts), "active": float(active)},
            link=link,
        )

    @staticmethod
    def moderation_card(reports: Any, signups: Any, limit: int, link: str | None = None) -> WidgetData:
        reports = [one for one in reports if isinstance(one, dict)] if isinstance(reports, list) else []
        signups = [one for one in signups if isinstance(one, dict)] if isinstance(signups, list) else []
        rows = []
        for report in reports:
            kind = CATEGORIES.get(str(report.get("category") or ""), "Report")
            rows.append({
                "title": f"Report about {_acct(report.get('target_account'))}",
                "subtitle": " · ".join(part for part in (kind, _text(report.get("comment"))) if part),
                "status": "warn",
                "value": ago(report.get("created_at")),
            })
        for account in signups:
            rows.append({
                "title": f"Sign-up of {_acct(account)}",
                "subtitle": " · ".join(part for part in ("Waiting for approval", _text(account.get("invite_request"))) if part),
                "status": "warn",
                "value": ago(account.get("created_at")),
            })
        waiting = len(reports) + len(signups)
        cut = lambda items: f"{len(items)}+" if len(items) >= PAGE else len(items)  # noqa: E731
        return WidgetData(
            status="warn" if waiting else "ok",
            items=rows[:limit],
            secondary=[{"label": "Open reports", "value": cut(reports)}, {"label": "Sign-ups waiting", "value": cut(signups)}],
            metrics={"reports": float(len(reports)), "signups": float(len(signups))},
            link=link,
            meta={"empty": "Nothing waits for a moderator."},
        )

    @staticmethod
    def account_card(me: Any, unread: tuple[int, bool] | None, link: str | None = None) -> WidgetData:
        me = me if isinstance(me, dict) else {}
        secondary = [{"label": "Account", "value": f"@{me.get('acct') or me.get('username') or '?'}"}, {"label": "Following", "value": int(me.get("following_count") or 0)},
                     {"label": "Posts", "value": int(me.get("statuses_count") or 0)}]
        if me.get("last_status_at"):
            secondary.append({"label": "Last post", "value": ago(me.get("last_status_at"))})
        if unread is not None:
            secondary.append({"label": "Unread notifications", "value": f"{unread[0]}+" if unread[1] else unread[0]})
        return WidgetData(
            status="ok",
            primary={"label": "Followers", "value": int(me.get("followers_count") or 0)},
            secondary=secondary,
            metrics={"followers": float(me.get("followers_count") or 0), "posts": float(me.get("statuses_count") or 0), "unread": float(unread[0] if unread else 0)},
            link=str(me.get("url") or "") or link,
        )

    # -- demo ----------------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - tick % 60 - 3600))
        if widget_kind == "moderation":
            waiting = int(fake.walk("mastodon-reports", tick, 0, 3))
            reports = [{"category": "spam", "comment": "Same link in ten replies", "created_at": now, "target_account": {"account": {"acct": "promo"}}}] * waiting
            return self.moderation_card(reports, [{"created_at": now, "invite_request": "I run a small homelab blog", "account": {"acct": "newperson"}}], int(options.get("limit") or 8))
        if widget_kind == "account":
            return self.account_card({"acct": "me", "followers_count": 312 + tick // 200, "following_count": 180, "statuses_count": 1420, "last_status_at": now[:10]},
                                     (int(fake.walk("mastodon-unread", tick, 0, 9)), False))
        return self.server_card({"version": "4.5.0", "stats": {"user_count": 86, "status_count": 41200 + tick, "domain_count": 2310}},
                                {"usage": {"users": {"active_month": 52}}, "registrations": {"enabled": False, "approval_required": True}})


ADAPTER = MastodonAdapter()
