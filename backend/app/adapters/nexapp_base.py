"""What the read APIs of the nexapps family have in common.

nexcanvas, nexbrand, nexpaper and nexdiary answer a program the same way: a
credential in ``Authorization: Bearer``, never in the address; a request that
carries an ``Origin`` header refused (browsers send one, programs do not); an
operator's switch that is off until somebody opens it; a wrong or withdrawn
credential; a rate. Each says so as ``{"detail": {"code": …, "message": …}}``.
This turns those refusals into sentences that say what to do, once, so four
adapters do not word them four ways.

The codes differ a little: nexpaper calls its credential a key and answers
``key_invalid``, the other three answer ``token_invalid``. Anything that is
401 and not one of the named cases is a credential that does not hold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .base import AdapterError, AuthFailed, Context, base_url


def code_of(response: Any) -> str:
    """The app's own code of a refusal, from ``{"detail": {"code": …}}``."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return str(detail.get("code") or "") if isinstance(detail, dict) else ""


def epoch_of(moment: Any) -> float | None:
    """An ISO time as seconds since the epoch; one without a zone is UTC, as the apps store it."""
    try:
        when = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def count_of(value: Any) -> int:
    """A number from an answer, or nought when it is missing or not a number."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


class NexappApi:
    """A mixin for the adapters of the family: one authenticated, cached GET under ``/api/v1``."""

    #: The app's name as the sentences say it.
    app = ""
    #: What the credential is called in that app: ``token`` or ``key``.
    thing = "token"
    #: Where the operator switches the API on, and where a person makes the credential.
    where_on = ""
    where_make = ""
    #: The name of the connection field that holds the credential.
    secret = "api_key"
    #: What only this app's ``/me`` answers with, and what only its siblings' do. The four answer ``/me`` alike
    #: and two share the token prefix ``nxa_``, so without this a nexcanvas token at a nexdiary card passed the
    #: test and drew a streak of nought (found against real instances on 11.10.2026).
    own_fields: tuple[str, ...] = ()
    sibling_fields: tuple[str, ...] = ("spaces", "clients", "scope")

    async def _me(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """``/me``, refused when the address answers as another app of the family."""
        me = await self._get(config, ctx, "/me", cache=0)
        me = me if isinstance(me, dict) else {}
        foreign = [name for name in self.sibling_fields if name in me and name not in self.own_fields]
        if foreign or any(name not in me for name in self.own_fields):
            raise AdapterError(
                f"This address answers, but not as {self.app}.", code="wrong_app",
                hint=f"Enter the address of {self.app} and a {self.thing} made there; another app of the family answers here.",
            )
        return me

    async def _get(
        self,
        config: dict[str, Any],
        ctx: Context,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cache: int = 30,
        missing: tuple[str, str, str] | None = None,
    ) -> Any:
        """The JSON under ``/api/v1{path}``.

        ``missing`` is what a 404 means for this route, as ``(message, code, hint)``:
        an old app that has no such route, or a board the token may not read.
        """
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", params=params, cache_seconds=cache, auth_errors=False,
            headers={"Authorization": f"Bearer {config.get(self.secret) or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        self._refuse(response, missing)
        try:
            return response.json()
        except ValueError:
            raise AdapterError(
                f"{self.app} did not answer with JSON; is this the address of {self.app}?", code="bad_answer",
                hint="Use the address you open the app with, without a path.",
            ) from None

    def _refuse(self, response: Any, missing: tuple[str, str, str] | None) -> None:
        code = code_of(response)
        status = response.status_code
        if code == "origin_refused":
            raise AdapterError(
                f"{self.app} refuses requests that carry an Origin header.", code="origin_refused",
                hint=f"A proxy in front of {self.app} may be adding one; use the address of {self.app} itself.",
            )
        if code == "api_off":
            raise AdapterError(
                f"API access is switched off in {self.app}.", code="api_off",
                hint=f"{self.where_on}; the {self.thing} itself stays valid.",
            )
        if code == "token_wrong_kind":
            raise AdapterError(
                f"This is a device token. {self.app} reads with an API key that starts with npk_.", code="wrong_kind",
                hint=self.where_make,
            )
        if code == "key_scope":
            raise AdapterError(
                "This key may only upload files. The cards need a key with the scope read.", code="wrong_scope",
                hint=self.where_make,
            )
        if code == "too_many_attempts":
            raise AdapterError(
                f"{self.app} lets this address rest for a while after wrong keys.", code="rate_limited",
                hint="Correct the key in this connection; the address is let in again after a quarter of an hour.",
            )
        if status == 429 or code == "slow_down":
            raise AdapterError(f"{self.app} asks for fewer requests for a minute.", code="rate_limited")
        if status == 401:
            failure = AuthFailed(f"{self.app} does not know this {self.thing}; it may have run out or been withdrawn.")
            failure.hint = self.where_make
            raise failure
        if status == 404 and missing:
            message, missing_code, hint = missing
            raise AdapterError(message, code=missing_code, hint=hint)
        if status == 404:
            raise AdapterError(
                f"{self.app} answered with HTTP 404.", code="http_error",
                hint=f"Use the address you open {self.app} with, without a path such as /api/v1.",
            )
        if status >= 400:
            raise AdapterError(f"{self.app} answered with HTTP {status}.", code="http_error")

    def _expect(self, answer: Any, *fields: str) -> dict[str, Any]:
        """The answer of a card's route, refused when it has none of the fields only this app sends.

        Without it a card at the address of another app of the family drew noughts instead of saying so. One of
        them is enough: an answer that lacks a few is still this app's, and the cards make do without them.
        """
        if not isinstance(answer, dict) or not any(field in answer for field in fields):
            raise AdapterError(
                f"This address answers, but not as {self.app}.", code="wrong_app",
                hint=f"Enter the address of {self.app} and a {self.thing} made there; another app of the family answers here.",
            )
        return answer
