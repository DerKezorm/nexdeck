"""A pretend GitHub for the sharing of cards (KARTEN-16): the Device Flow, the users, and the issues of the Workshop.

It extends the pretend repository of the Card shop (``karten14_sample``) with what a signed-in administrator talks to
GitHub about. Nothing here reaches the network: ``respx`` answers every request to ``github.com`` and
``api.github.com`` from this object and fails the test for a request to any other address.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.db import db_session
from app.models import User
from app.workshop import catalog, files, github_login, real_values, submit

from .karten14_sample import REPO, GitHub, entry

DAY = "2026-10-28"
BOT = {"id": 41898282, "login": "github-actions[bot]", "type": "Bot"}
CLIENT_ID = "Iv23lilswL5wrA1Z5D4T"


def account(user_id: int) -> Any:
    """The account with this number as ``real_values`` wants to know it (a number nobody has gets a name nobody has)."""
    with db_session() as db:
        row = db.get(User, user_id)
        return SimpleNamespace(id=user_id, username=row.username if row else "nobody", created_at=row.created_at if row else None)


class Hub(GitHub):
    """The pretend GitHub with people, a Device Flow and the issues of the Workshop repository."""

    def __init__(self) -> None:
        super().__init__()
        #: Access token -> the person it belongs to.
        self.tokens: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, str] = {}
        #: Logins that cannot see the (private) repository.
        self.outsiders: set[str] = set()
        self.issues: list[dict[str, Any]] = []
        self.comments: dict[int, list[dict[str, Any]]] = {}
        # -- the Device Flow
        self.person_at_the_screen: dict[str, Any] | None = None
        self.device_calls = 0
        self.token_calls = 0
        self.slow_down = 0
        self.answer_with: str | None = None
        self.interval = 5
        self.expires_in = 900
        self.access_lifetime = 28800
        self.refresh_lifetime = 15811200
        self.refuse_refresh = False
        self.counter = 0
        #: The next creation of an issue is made, and its answer is lost on the way.
        self.lose_the_answer_of_the_next_issue = False
        self.created_at = f"{DAY}T10:00:00Z"
        #: The bodies of what was sent to the issues, in order.
        self.sent: list[dict[str, Any]] = []
        #: The discussions of the Workshop by node id: the address and the logins that put a thumb on it.
        self.discussions: dict[str, dict[str, Any]] = {}
        #: Whether the App may react to discussions; without, GitHub says "Resource not accessible by integration".
        self.discussion_rights = True
        #: Every GraphQL request: the login behind the token (or none), the query and its variables.
        self.graphql: list[dict[str, Any]] = []

    # -- people --------------------------------------------------------------------------------

    def person(self, login: str = "someone", number: int = 4242) -> dict[str, Any]:
        return {"id": number, "login": login, "type": "User"}

    def sign_in_as(self, person: dict[str, Any]) -> None:
        """The person types the code on github.com: the next question for the token is answered."""
        self.person_at_the_screen = person

    def token_of(self, request: httpx.Request) -> str:
        return request.headers.get("authorization", "").removeprefix("Bearer ").strip()

    def give_token(self, person: dict[str, Any]) -> dict[str, Any]:
        self.counter += 1
        access, refresh = f"ghu_access{self.counter}", f"ghr_refresh{self.counter}"
        self.tokens[access] = person
        self.refresh_tokens[refresh] = access
        return {
            "access_token": access, "expires_in": self.access_lifetime, "refresh_token": refresh,
            "refresh_token_expires_in": self.refresh_lifetime, "token_type": "bearer", "scope": "",
        }

    def revoke_everything(self) -> None:
        """The person withdrew the App at GitHub: every token stops working."""
        self.tokens.clear()
        self.refresh_tokens.clear()

    # -- the answers -----------------------------------------------------------------------------

    def answer(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "down":
            raise httpx.ConnectError("no route to host")
        if request.url.host == "github.com":
            return self.answer_login(request)
        if request.url.path == "/user":
            self.requests.append(request)
            who = self.tokens.get(self.token_of(request))
            return httpx.Response(200, json=who) if who else httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path.startswith(f"/repos/{REPO}/issues"):
            self.requests.append(request)
            return self.answer_issues(request)
        if request.url.path == "/graphql":
            self.requests.append(request)
            return self.answer_graphql(request)
        return super().answer(request)

    # -- the discussions -------------------------------------------------------------------------

    def open_discussion(self, node: str = "D_kwDOtest1", number: int = 7) -> dict[str, Any]:
        """A discussion of the Workshop; returns what the catalog names of it."""
        url = f"https://github.com/{REPO}/discussions/{number}"
        self.discussions[node] = {"url": url, "thumbs": set()}
        return {"id": node, "url": url}

    def answer_graphql(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        who = self.tokens.get(self.token_of(request))
        self.graphql.append({"login": who["login"] if who else None, "token": self.token_of(request), "query": body["query"], "variables": body.get("variables", {})})
        if who is None:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if not self.discussion_rights:
            return httpx.Response(200, json={"data": None, "errors": [{"type": "FORBIDDEN", "message": "Resource not accessible by integration"}]})
        query, variables = body["query"], body.get("variables", {})
        if "Reaction(" in query:
            found = self.discussions.get(variables.get("id", ""))
            if found is None:
                return httpx.Response(200, json={"data": None, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a node"}]})
            (found["thumbs"].add if "addReaction" in query else found["thumbs"].discard)(who["login"])
            groups = [{"content": "THUMBS_UP", "reactors": {"totalCount": len(found["thumbs"])}}, {"content": "HEART", "reactors": {"totalCount": 2}}]
            return httpx.Response(200, json={"data": {"addReaction" if "addReaction" in query else "removeReaction": {"reactionGroups": groups}}})
        if "resource(" in query:
            # As GitHub: a discussion is no UniformResourceLocatable, the whole question is refused.
            return httpx.Response(200, json={"errors": [{"extensions": {"code": "cannotSpreadFragment"}, "message": "Fragment on Discussion can't be spread inside UniformResourceLocatable"}]})
        by_number = "discussion(number:" in query
        if by_number:
            address = f"https://github.com/{variables.get('owner')}/{variables.get('name')}/discussions/{variables.get('number')}"
            node = next((key for key, one in self.discussions.items() if one["url"] == address), None)
        else:
            node = variables.get("id") if variables.get("id") in self.discussions else None
        if node is None and by_number:
            return httpx.Response(200, json={"data": {"repository": {"discussion": None}}, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a Discussion"}]})
        if node is None:
            return httpx.Response(200, json={"data": {"node": None}})
        groups = [
            {"content": "THUMBS_UP", "viewerHasReacted": who["login"] in self.discussions[node]["thumbs"], "reactors": {"totalCount": len(self.discussions[node]["thumbs"])}},
            {"content": "HEART", "viewerHasReacted": False, "reactors": {"totalCount": 2}},
        ]
        home = "/".join(self.discussions[node]["url"].split("/")[3:5])
        found = {"id": node, "repository": {"nameWithOwner": home}, "reactionGroups": groups}
        return httpx.Response(200, json={"data": {"repository": {"discussion": found}} if by_number else {"node": found}})

    def answer_login(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if request.url.path == "/login/device/code":
            self.device_calls += 1
            if form.get("client_id") != CLIENT_ID:
                return httpx.Response(200, json={"error": "incorrect_client_credentials"})
            return httpx.Response(200, json={
                "device_code": f"device-{self.device_calls}", "user_code": f"WDJB-{1000 + self.device_calls}",
                "verification_uri": "https://github.com/login/device", "expires_in": self.expires_in, "interval": self.interval,
            })
        if request.url.path != "/login/oauth/access_token":
            return httpx.Response(404, json={})
        self.token_calls += 1
        if form.get("grant_type") == "refresh_token":
            access = self.refresh_tokens.pop(form.get("refresh_token", ""), None)
            if access is None or self.refuse_refresh:
                return httpx.Response(200, json={"error": "bad_refresh_token"})
            return httpx.Response(200, json=self.give_token(self.tokens.pop(access)))
        if self.answer_with:
            return httpx.Response(200, json={"error": self.answer_with})
        if self.slow_down > 0:
            self.slow_down -= 1
            return httpx.Response(200, json={"error": "slow_down", "interval": self.interval + 5})
        if self.person_at_the_screen is None:
            return httpx.Response(200, json={"error": "authorization_pending"})
        return httpx.Response(200, json=self.give_token(self.person_at_the_screen))

    # -- the issues ------------------------------------------------------------------------------

    def issue_view(self, issue: dict[str, Any]) -> dict[str, Any]:
        return {**issue, "html_url": f"https://github.com/{REPO}/issues/{issue['number']}", "comments": len(self.comments.get(issue["number"], []))}

    def answer_issues(self, request: httpx.Request) -> httpx.Response:
        who = self.tokens.get(self.token_of(request))
        if who is None:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if who["login"] in self.outsiders:
            return httpx.Response(404, json={"message": "Not Found"})
        parts = request.url.path.removeprefix(f"/repos/{REPO}/issues").strip("/").split("/")
        query = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        body = json.loads(request.content) if request.content else {}
        if parts == [""] and request.method == "POST":
            self.sent.append(body)
            issue = {
                "number": len(self.issues) + 1, "title": body["title"], "body": body["body"], "state": "open",
                "user": who, "created_at": self.created_at,
            }
            self.issues.append(issue)
            if self.lose_the_answer_of_the_next_issue:
                self.lose_the_answer_of_the_next_issue = False
                raise httpx.ReadTimeout("the answer was lost")
            return httpx.Response(201, json=self.issue_view(issue))
        if parts == [""] and request.method == "GET":
            found = [one for one in self.issues if query.get("state", "open") in ("all", one["state"])]
            if "creator" in query:
                found = [one for one in found if one["user"]["login"] == query["creator"]]
            found.sort(key=lambda one: -one["number"])
            return httpx.Response(200, json=[self.issue_view(one) for one in found[: int(query.get("per_page", 30))]])
        number = int(parts[0])
        issue = next((one for one in self.issues if one["number"] == number), None)
        if issue is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if len(parts) == 1 and request.method == "PATCH":
            self.sent.append(body)
            issue.update({key: body[key] for key in ("title", "body", "state") if key in body})
            return httpx.Response(200, json=self.issue_view(issue))
        if len(parts) == 1:
            return httpx.Response(200, json=self.issue_view(issue))
        if parts[1] == "comments" and request.method == "POST":
            self.sent.append(body)
            made = {"body": body["body"], "user": who, "created_at": self.created_at}
            self.comments.setdefault(number, []).append(made)
            return httpx.Response(201, json=made)
        if parts[1] == "comments":
            return httpx.Response(200, json=self.comments.get(number, []))
        return httpx.Response(404, json={})

    # -- the action of the Workshop ---------------------------------------------------------------

    def digest(self, number: int) -> str:
        return hashlib.sha256(self.issues[number - 1]["body"].encode("utf-8")).hexdigest()

    def say(self, number: int, status: str, lines: list[str], *, close: bool = False) -> None:
        text = "\n".join(lines) + f"\n\n<!-- workshop:{status}:{self.digest(number)} -->"
        self.comments.setdefault(number, []).append({"body": text, "user": BOT, "created_at": self.created_at})
        if close:
            self.issues[number - 1]["state"] = "closed"

    def reject(self, number: int, *reasons: str) -> None:
        self.say(number, "rejected", ["**This submission cannot be accepted yet.**", "", *(f"- {one}" for one in reasons), "", "Edit the issue."])

    def defer(self, number: int) -> None:
        self.say(number, "deferred", ["**This submission waits.** An account may add 10 new entries a day."])

    def accept(self, number: int, text: str, **more: Any) -> dict[str, Any]:
        """The action takes the submission in: an entry in the catalog under the account of the issue, the issue closed."""
        issue = self.issues[number - 1]
        found = entry(text, author=str(issue["user"]["id"]), **more)
        self.entries = [one for one in self.entries if one["id"] != found["id"]] + [found]
        self.files[found["files"]["definition"]] = text.encode("utf-8")
        self.say(number, "accepted", [f"**Accepted.** `{found['id']}` is in the workshop now."], close=True)
        return found


@pytest.fixture
def hub() -> Iterator[Hub]:
    """Takes the place of the pretend repository of the shop with one that speaks the rest of GitHub as well."""
    fake = Hub()
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as network:
        network.route(host="api.github.com").mock(side_effect=fake.answer)
        network.route(host="github.com").mock(side_effect=fake.answer)
        catalog.forget()
        files.forget()
        github_login.forget()
        submit.forget()
        real_values.forget()
        yield fake
    catalog.forget()
    files.forget()
    github_login.forget()
    submit.forget()
    real_values.forget()


@pytest.fixture
def moment(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """The clock of the sign-in, as a list of one number a test moves."""
    clock = [1_793_188_800.0]  # 28 October 2026, noon, the day of the issues of the pretend GitHub
    monkeypatch.setattr(github_login, "now", lambda: clock[0])
    yield clock
