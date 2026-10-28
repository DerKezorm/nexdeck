"""Lemmy: how big your instance is, and what waits for a moderator or an admin.

⚠️ **Not run against Lemmy.** A test instance wants PostgreSQL, pict-rs and
the Lemmy server, three processes, and only one measuring container was
allowed. This is built from Lemmy's API documentation (version 3 of the API,
Lemmy 0.19 and 0.20), the answers in the tests have the documented shape, and
the card is a beta for that reason. Whether a newer Lemmy that moved the API
keeps ``/api/v3`` is not known.

What the documentation says and this relies on:

- ``GET /api/v3/site`` needs no sign-in on an open instance: ``version`` and
  ``site_view.counts`` with ``users``, ``posts``, ``comments``,
  ``communities`` and ``users_active_day``, ``_week``, ``_month`` and
  ``_half_year``; ``site_view.local_site.registration_mode`` is ``Open``,
  ``RequireApplication`` or ``Closed``.
- ``POST /api/v3/user/login`` with ``{"username_or_email", "password"}`` gives
  ``{"jwt": ...}``, sent as ``Authorization: Bearer``. A wrong login is
  HTTP 400 with ``{"error": "incorrect_login"}``, a request without one
  ``{"error": "not_logged_in"}``: Lemmy answers 400 for its errors.
- ``GET /api/v3/report_count`` gives ``post_reports``, ``comment_reports``
  and, for an admin, ``private_message_reports``; for a moderator the reports
  of the communities they moderate.
  ``GET /api/v3/registration_application/count`` gives
  ``registration_applications`` and is for admins.
  ``GET /api/v3/user/unread_count`` gives ``replies``, ``mentions`` and
  ``private_messages``.
"""

from __future__ import annotations

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
    base_url,
)

MODES = {"Open": "Open", "RequireApplication": "Needs approval", "Closed": "Closed"}
#: What Lemmy says, in HTTP 400, when the sign-in is the problem.
SIGN_IN = ("incorrect_login", "not_logged_in", "couldnt_find_that_username_or_email", "password_incorrect", "login_banned")


class LemmyAdapter(Adapter):
    kind = "lemmy"
    label = "Lemmy"
    category = "feeds"
    description = "Users, posts, communities and active users of your Lemmy instance, and the reports and applications waiting for you."
    icon = "lemmy"
    docs_url = "https://join-lemmy.org/api/"
    keywords = ("fediverse", "social", "reddit")
    #: Built from the documentation; never run against Lemmy.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://lemmy.example.com"),
        Field("username", "User name", help="Of a moderator or an admin, for the card with reports. Not needed for the instance figures."),
        Field("password", "Password", type="password", secret=True, help="Of that user. Lemmy has no access tokens of its own, so nexdeck signs in and keeps the session."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="instance",
            label="Instance",
            description="Users, posts, comments and communities, how many users were active this month, and how people can sign up.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=900,
            metrics=("users", "posts", "active"),
        ),
        WidgetType(
            kind="moderation",
            label="Moderation",
            description="Reported posts, comments and messages and applications to join that wait for you, and your unread replies.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("reports", "applications"),
        ),
    )

    # -- asking Lemmy -------------------------------------------------------------------------

    async def _login(self, config: dict[str, Any], ctx: Context) -> str:
        user = str(config.get("username") or "").strip()
        if not user:
            raise AuthFailed("This card needs a user name and a password.")
        response = await ctx.request("POST", f"{base_url(config)}/api/v3/user/login", json_body={"username_or_email": user, "password": str(config.get("password") or "")},
                                     verify=not config.get("insecure"), timeout=20, auth_errors=False)
        body = self._body(response)
        if response.status_code in (400, 401, 403):
            failure = AuthFailed("Lemmy rejected the user name or the password." if str(body.get("error")) in SIGN_IN else f"Lemmy refused the sign-in: {body.get('error') or response.status_code}.")
            failure.hint = "Use the name and password you sign in to Lemmy with. An account with two-factor authentication is not supported."
            raise failure
        if response.status_code >= 400:
            raise AdapterError(f"Lemmy answered with HTTP {response.status_code}.", code="http_error")
        token = str(body.get("jwt") or "")
        if not token:
            raise AdapterError("Lemmy gave no session. The account may still wait for approval or for its mail to be verified.", code="no_session")
        ctx.cache["lemmy:jwt"] = token
        return token

    @staticmethod
    def _body(response: Any) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, signed: bool = False, retry: bool = True, cache: float = 30) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if signed:
            headers["Authorization"] = f"Bearer {ctx.cache.get('lemmy:jwt') or await self._login(config, ctx)}"
        response = await ctx.request("GET", f"{base_url(config)}/api/v3{path}", headers=headers, verify=not config.get("insecure"),
                                     cache_seconds=cache, timeout=25, auth_errors=False)
        body = self._body(response)
        if response.status_code in (400, 401, 403) and str(body.get("error")) in SIGN_IN:
            ctx.cache.pop("lemmy:jwt", None)
            if signed and retry:
                # A session that has run out: sign in again, once, and not from memory.
                await self._login(config, ctx)
                return await self._get(config, ctx, path, signed, retry=False, cache=0)
            failure = AuthFailed("Lemmy rejected the session." if signed else "This Lemmy instance wants a sign-in for that.")
            failure.hint = "A private instance answers nobody without one; enter a user name and a password."
            raise failure
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Lemmy does.", code="not_lemmy", hint="The URL is the address of the instance, such as https://lemmy.example.com.")
        if response.status_code >= 400:
            raise AdapterError(f"Lemmy answered with HTTP {response.status_code}: {body.get('error') or 'no reason given'}.", code="http_error")
        if not body:
            raise AdapterError("Lemmy did not answer with JSON.", code="not_json", hint="The URL probably points at a web page or a reverse proxy.")
        return body

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        site = await self._get(config, ctx, "/site", cache=0)
        if "site_view" not in site:
            raise AdapterError("This address answers, but not the way Lemmy does.", code="not_lemmy")
        version = str(site.get("version") or "").strip()
        head = f"Lemmy {version}" if version else "Lemmy"
        if str(config.get("username") or "").strip():
            ctx.cache.pop("lemmy:jwt", None)
            await self._get(config, ctx, "/user/unread_count", signed=True, cache=0)
            return f"{head} accepts the sign-in of {str(config['username']).strip()}."
        return f"{head} answers; the instance figures need no sign-in."

    # -- the cards --------------------------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "instance":
            return self.instance_card(await self._get(config, ctx, "/site"), link)
        reports = await self._get(config, ctx, "/report_count", signed=True)
        try:
            applications = await self._get(config, ctx, "/registration_application/count", signed=True)
        except AdapterError as error:
            # Only an admin may ask; a moderator gets the reports and no word about applications.
            if error.code != "http_error":
                raise
            applications = None
        unread = await self._get(config, ctx, "/user/unread_count", signed=True)
        return self.moderation_card(reports, applications, unread, link)

    @staticmethod
    def instance_card(site: dict[str, Any], link: str | None = None) -> WidgetData:
        view = site.get("site_view") if isinstance(site.get("site_view"), dict) else {}
        counts = view.get("counts") if isinstance(view.get("counts"), dict) else {}
        mode = str(((view.get("local_site") or {}).get("registration_mode")) or "")
        secondary = [{"label": "Posts", "value": int(counts.get("posts") or 0)}, {"label": "Comments", "value": int(counts.get("comments") or 0)},
                     {"label": "Communities", "value": int(counts.get("communities") or 0)}, {"label": "Active this month", "value": int(counts.get("users_active_month") or 0)},
                     {"label": "Active this week", "value": int(counts.get("users_active_week") or 0)}]
        if mode:
            secondary.append({"label": "Sign-ups", "value": MODES.get(mode, mode)})
        if site.get("version"):
            secondary.append({"label": "Version", "value": str(site["version"])})
        return WidgetData(
            status="ok",
            primary={"label": "Users", "value": int(counts.get("users") or 0)},
            secondary=secondary,
            metrics={"users": float(counts.get("users") or 0), "posts": float(counts.get("posts") or 0), "active": float(counts.get("users_active_month") or 0)},
            link=link,
        )

    @staticmethod
    def moderation_card(reports: dict[str, Any], applications: dict[str, Any] | None, unread: dict[str, Any], link: str | None = None) -> WidgetData:
        posts, comments = int(reports.get("post_reports") or 0), int(reports.get("comment_reports") or 0)
        messages = int(reports.get("private_message_reports") or 0)
        waiting = posts + comments + messages
        secondary = [{"label": "Reported posts", "value": posts}, {"label": "Reported comments", "value": comments}]
        if reports.get("private_message_reports") is not None:
            secondary.append({"label": "Reported messages", "value": messages})
        count = None
        if applications is not None:
            count = int(applications.get("registration_applications") or 0)
            secondary.append({"label": "Applications waiting", "value": count})
        secondary.append({"label": "Unread replies", "value": sum(int(unread.get(key) or 0) for key in ("replies", "mentions", "private_messages"))})
        return WidgetData(
            status="warn" if waiting or count else "ok",
            primary={"label": "Open reports", "value": waiting},
            secondary=secondary,
            metrics={"reports": float(waiting), "applications": float(count or 0)},
            link=link,
        )

    # -- demo -----------------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "moderation":
            return self.moderation_card({"post_reports": int(fake.walk("lemmy-posts", tick, 0, 3)), "comment_reports": int(fake.walk("lemmy-comments", tick, 0, 4)),
                                         "private_message_reports": 0},
                                        {"registration_applications": int(fake.walk("lemmy-apps", tick, 0, 2))},
                                        {"replies": int(fake.walk("lemmy-replies", tick, 0, 6)), "mentions": 1, "private_messages": 0})
        return self.instance_card({"version": "0.19.5", "site_view": {"counts": {"users": 410, "posts": 5300 + tick // 30, "comments": 21800, "communities": 36,
                                                                                  "users_active_month": 96, "users_active_week": 61, "users_active_day": 18},
                                                                    "local_site": {"registration_mode": "RequireApplication"}}})


ADAPTER = LemmyAdapter()
