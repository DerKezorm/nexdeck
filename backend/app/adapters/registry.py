"""Container registry (OCI Distribution API): repositories, tags and the newest version of an image.

Measured on 27.10.2026 against registry:2 (Distribution) behind htpasswd, and
zot (anonymous), both run as containers; and, read only, against ghcr.io and
Docker Hub with public images.

- ``GET /v2/`` answers 200, or 401 with ``WWW-Authenticate``. Distribution
  and zot ask for ``Basic realm="..."``; ghcr.io and Docker Hub for
  ``Bearer realm="https://ghcr.io/token",service="ghcr.io"``. The token comes
  from the realm (``token`` in the answer), for the scope
  ``repository:<name>:pull``, with the account's Basic credentials if there
  are any, and without them for a public image.
- ``/v2/_catalog`` lists the repositories on Distribution and zot. ghcr.io
  answers 401 and Docker Hub has none: those registries are read through the
  images listed on the card.
- ``tags/list`` is **not sorted by version** (Distribution: insertion order,
  zot and Docker Hub: alphabetical, so "1.10.0" lies before "1.9.0"). ``n``
  pages it with a ``Link: <...>; rel="next"`` header, which Distribution did
  not honour for tags, so a page that comes back whole is taken as whole.
  zot writes ``last=example/app`` unencoded, Distribution encodes the slash.
- A tag's date is not in the tag list. It is the ``created`` of the image
  config: tag -> manifest -> (for a list or index, the linux/amd64 manifest)
  -> config blob. ghcr.io redirects the blob to another host (307), which the
  shared client follows without the token; ``created`` carries nanoseconds there.
- Errors are ``{"errors": [{"code": "NAME_UNKNOWN", ...}]}`` with 404.
"""

from __future__ import annotations

import base64
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

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
    human_bytes,
)

ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v2+json",
))
INDEXES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
#: A repository name as the specification writes it.
NAME = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$")
#: A tag that is a version: digits and dots, with a leading v; the rest of the name is its flavour.
VERSION = re.compile(r"^(v?)(\d+(?:\.\d+)*)([A-Za-z0-9_.-]*)$")
CHALLENGE = re.compile(r'(\w+)="([^"]*)"')
NEXT = re.compile(r'<([^>]*)>\s*;\s*rel="?next"?')
#: How many tags and repositories are read at most, in pages: a registry with more is not listed whole.
TAG_PAGES = 5
CATALOG_PAGES = 10
#: Repositories whose tags the overview counts.
COUNTED = 20

IMAGES_FIELD = Field("images", "Images", type="textarea", required=True, placeholder="library/nginx:1.25.3",
                     help="One per line, as name or name:tag. With a tag the card says whether a newer one exists with the same ending, such as -alpine. At most ten.")


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def parse_tag(tag: str) -> tuple[tuple[int, ...], str] | None:
    """A tag's numbers and its flavour (``-alpine``, ``-rc1``, or nothing), or None for a tag that is no version."""
    # ⚠️ A tag comes from the registry and goes into an address: only what a tag may be.
    found = VERSION.match(tag) if len(tag) <= 128 else None
    if not found or len(found.group(2)) > 40:
        return None
    return _numbers(found.group(2)), found.group(3)


def newest_tag(tags: list[str], current: str = "") -> str | None:
    """The highest version among the tags that are of the same kind as ``current``.

    ⚠️ Same kind: the tags that end the same way and, when ``current`` is given,
    have as many numbers (1.25 asks for the newest two-number tag, not for
    1.27.3). Without ``current`` only plain versions count, so that a release
    candidate or a variant such as ``-alpine`` is never "the newest".
    """
    want = parse_tag(current) if current else None
    flavour = want[1] if want else ""
    best: tuple[tuple[tuple[int, ...], int], str] | None = None
    for tag in tags:
        parsed = parse_tag(tag)
        if not parsed or parsed[1] != flavour:
            continue
        numbers = parsed[0]
        if want and (len(numbers) != len(want[0]) or tag.startswith("v") != current.startswith("v")):
            continue
        key = (numbers + (0,) * (20 - len(numbers)), len(numbers))
        if best is None or key > best[0]:
            best = (key, tag)
    return best[1] if best else None


def is_behind(current: str, newest: str) -> bool:
    a, b = parse_tag(current), parse_tag(newest)
    if not a or not b:
        return False
    width = max(len(a[0]), len(b[0]))
    return a[0] + (0,) * (width - len(a[0])) < b[0] + (0,) * (width - len(b[0]))


def parse_images(text: str, host: str, docker_hub: bool) -> list[tuple[str, str]]:
    """``[(repository, tag)]`` from one image per line, a leading host or ``docker.io/`` allowed."""
    found: list[tuple[str, str]] = []
    for line in str(text or "").splitlines():
        line = line.strip().split("@", 1)[0]
        if not line:
            continue
        for prefix in (host + "/", "docker.io/", "registry-1.docker.io/"):
            if line.startswith(prefix):
                line = line[len(prefix):]
        name, _, tag = line.rpartition(":") if ":" in line.rsplit("/", 1)[-1] else (line, "", "")
        if docker_hub and "/" not in name:
            name = "library/" + name
        found.append((name, tag))
    return found[:10]


class RegistryAdapter(Adapter):
    kind = "registry"
    label = "Container registry"
    category = "hosts"
    description = "Repositories and tags of a container registry, and the newest version of the images you run. zot, Distribution, Harbor, ghcr.io and Docker Hub."
    icon = "docker"
    docs_url = "https://github.com/opencontainers/distribution-spec/blob/main/spec.md"
    keywords = ("zot", "distribution", "harbor", "ghcr", "docker hub", "oci", "image")
    #: Measured against Distribution 2 and zot as containers, and ghcr.io and Docker Hub read only; Harbor and the sign-in with an account on a hub not at all.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://registry.example.com",
              help="The registry itself, without /v2: https://ghcr.io, https://registry-1.docker.io, or your own."),
        Field("user", "User name", help="Empty for public images and for a registry without sign-in."),
        Field("password", "Password or token", type="password", secret=True,
              help="Of a robot account or a read-only access token. Public images on ghcr.io and Docker Hub need none."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Registry overview",
            description="How many repositories the registry lists and how many tags the first of them carry.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
            metrics=("repositories", "tags"),
        ),
        WidgetType(
            kind="repositories",
            label="Repositories",
            description="The repositories the registry lists, with how many tags each has and its newest version.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=900,
            options=(Field("limit", "Entries", type="number", default=10),
                     Field("filter", "Name contains", placeholder="app", help="Only repositories whose name has this in it.")),
        ),
        WidgetType(
            kind="images",
            label="Newest versions",
            description="The newest version of each image you name, how old it is, and whether it is newer than the tag you run.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=1800,
            metrics=("behind",),
            options=(IMAGES_FIELD,),
        ),
    )

    # -- asking the registry -----------------------------------------------------------

    @staticmethod
    def _credentials(config: dict[str, Any]) -> tuple[str, str] | None:
        user, password = str(config.get("user") or "").strip(), str(config.get("password") or "")
        return (user, password) if user else None

    async def raw_signed(self, config: dict[str, Any], ctx: Context) -> tuple[dict[str, str], dict[str, Any], tuple[str, str] | None] | None:
        """A card signs with the user name and the password of the connection, Basic, to the registry's own address.

        A registry that hands out tokens (Docker Hub, ghcr.io) names a token service for every repository; a card does not
        go there, so it can read such a registry only where it answers without a token.
        """
        return {}, {}, self._credentials(config)

    @staticmethod
    def _hub(config: dict[str, Any]) -> bool:
        return (urlsplit(base_url(config)).hostname or "").endswith("docker.io")

    async def _token(self, config: dict[str, Any], ctx: Context, challenge: dict[str, str], scope: str) -> str:
        realm = challenge.get("realm", "")
        where = urlsplit(realm)
        # ⚠️ The realm is named by the registry, and the account's password goes
        # to it. https anywhere is how ghcr.io and Docker Hub do it; plain http
        # only back to the registry's own host.
        if not (where.scheme == "https" or (where.scheme == "http" and where.hostname == urlsplit(base_url(config)).hostname)):
            raise AdapterError("The registry names a place to sign in that nexdeck will not send a password to.", code="realm_refused",
                               hint="A token service has to be on https, or on the registry's own host.")
        params = {key: value for key, value in (("service", challenge.get("service", "")), ("scope", challenge.get("scope") or scope)) if value}
        response = await ctx.request("GET", realm, params=params, auth=self._credentials(config), verify=not config.get("insecure"),
                                     timeout=20, auth_errors=False)
        if response.status_code in (401, 403):
            failure = AuthFailed("The registry rejected the user name or the password." if self._credentials(config) else "The registry wants a user name and a password.")
            failure.hint = "Use a robot account or an access token with permission to pull."
            raise failure
        if response.status_code >= 400:
            raise AdapterError(f"The registry's token service answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
            token = str(answer.get("token") or answer.get("access_token") or "")
        except (ValueError, AttributeError) as error:
            raise AdapterError("The registry's token service did not answer with JSON.", code="not_json") from error
        if not token:
            raise AdapterError("The registry's token service gave no token.", code="no_token")
        lasts = max(30, min(300, int(answer.get("expires_in") or 60)) - 10)
        ctx.cache.setdefault("registry:tokens", {})[scope] = (token, time.monotonic() + lasts)
        return token

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, scope: str = "", params: dict[str, Any] | None = None,
                   accept: str = "", retry: bool = True) -> Any:
        """One response, signed in the way the registry asked for. 401 and 403 come back as they are, for the caller to place."""
        headers = {"Accept": accept} if accept else {}
        held = ctx.cache.get("registry:tokens", {}).get(scope)
        signed = False
        if held and held[1] > time.monotonic():
            headers["Authorization"] = f"Bearer {held[0]}"
        elif ctx.cache.get("registry:basic") and self._credentials(config):
            # ⚠️ As a header and not as ``auth=``: the answers kept for a few seconds are told apart by their headers.
            # With ``auth=`` the 401 of the first try came back for the second, with the password.
            user, password = self._credentials(config) or ("", "")
            headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
            signed = True
        response = await ctx.request("GET", f"{base_url(config)}{path}", headers=headers, params=params, verify=not config.get("insecure"),
                                     cache_seconds=20, timeout=25, auth_errors=False)
        if response.status_code == 401 and retry:
            challenge = response.headers.get("www-authenticate", "")
            fields = dict(CHALLENGE.findall(challenge))
            scheme = challenge.split(" ", 1)[0].lower()
            if scheme == "bearer":
                await self._token(config, ctx, fields, scope)
                return await self._get(config, ctx, path, scope, params, accept, retry=False)
            if scheme == "basic" and self._credentials(config) and not signed:
                ctx.cache["registry:basic"] = True
                return await self._get(config, ctx, path, scope, params, accept, retry=False)
            if scheme == "basic":
                failure = AuthFailed("The registry rejected the user name or the password." if signed else "The registry wants a user name and a password.")
                failure.hint = "Use a robot account or an access token with permission to pull."
                raise failure
        if response.status_code == 401 and signed:
            # The second try, with the password, and the answer is still 401.
            failure = AuthFailed("The registry rejected the user name or the password.")
            failure.hint = "Use a robot account or an access token with permission to pull."
            raise failure
        return response

    @staticmethod
    def _json(response: Any) -> Any:
        if response.status_code >= 400:
            raise AdapterError(f"The registry answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("The registry did not answer with JSON.", code="not_json",
                               hint="The URL is the address of the registry itself, without /v2.") from error

    async def _pages(self, config: dict[str, Any], ctx: Context, path: str, scope: str, key: str, size: int, pages: int) -> tuple[list[str] | None, bool]:
        """A listing followed through its ``Link`` header; None if it is not allowed here, and whether it was cut short."""
        found: list[str] = []
        params: dict[str, Any] | None = {"n": size}
        for _ in range(pages):
            response = await self._get(config, ctx, path, scope, params)
            if response.status_code in (401, 403, 404, 405):
                return (None if not found else found), False
            body = self._json(response)
            found += [str(one) for one in (body.get(key) or []) if isinstance(one, str)] if isinstance(body, dict) else []
            link = NEXT.search(response.headers.get("link", ""))
            if not link or not link.group(1).startswith("/v2/"):
                return found, False
            path, _, query = link.group(1).partition("?")
            # Decoded here: Distribution writes last=example%2Fapp, zot last=example/app, and the client encodes once.
            params = dict(parse_qsl(query))
        return found, True

    async def tags(self, config: dict[str, Any], ctx: Context, repo: str) -> tuple[list[str] | None, bool]:
        if not NAME.match(repo):
            raise AdapterError(f"{repo} is not a repository name.", code="bad_repository")
        return await self._pages(config, ctx, f"/v2/{repo}/tags/list", f"repository:{repo}:pull", "tags", 1000, TAG_PAGES)

    async def repositories(self, config: dict[str, Any], ctx: Context) -> tuple[list[str] | None, bool]:
        return await self._pages(config, ctx, "/v2/_catalog", "registry:catalog:*", "repositories", 100, CATALOG_PAGES)

    async def image_facts(self, config: dict[str, Any], ctx: Context, repo: str, tag: str) -> dict[str, Any]:
        """When the image under a tag was built and how big it is to pull, from its manifest and its config."""
        scope = f"repository:{repo}:pull"
        response = await self._get(config, ctx, f"/v2/{repo}/manifests/{tag}", scope, accept=ACCEPT)
        if response.status_code >= 400:
            return {}
        manifest = self._json(response)
        if str(manifest.get("mediaType") or "") in INDEXES or "manifests" in manifest:
            wanted = next((one for one in manifest.get("manifests") or []
                           if (one.get("platform") or {}).get("os") == "linux" and (one.get("platform") or {}).get("architecture") == "amd64"), None)
            wanted = wanted or next((one for one in manifest.get("manifests") or [] if (one.get("platform") or {}).get("os") != "unknown"), None)
            if not wanted or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(wanted.get("digest") or "")):
                return {}
            response = await self._get(config, ctx, f"/v2/{repo}/manifests/{wanted['digest']}", scope, accept=ACCEPT)
            if response.status_code >= 400:
                return {}
            manifest = self._json(response)
        size = sum(int(layer.get("size") or 0) for layer in manifest.get("layers") or [] if isinstance(layer, dict))
        digest = str((manifest.get("config") or {}).get("digest") or "")
        created = ""
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            config_response = await self._get(config, ctx, f"/v2/{repo}/blobs/{digest}", scope)
            if config_response.status_code < 400:
                try:
                    created = str(config_response.json().get("created") or "")
                except (ValueError, AttributeError):
                    created = ""
        return {"created": created, "size": size}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        response = await self._get(config, ctx, "/v2/")
        if response.status_code in (401, 403):
            raise AuthFailed("The registry rejected the user name or the password.")
        answers_like_one = response.status_code == 200 and ("docker-distribution-api-version" in response.headers or response.text.strip().startswith("{"))
        if not answers_like_one:
            raise AdapterError("This address answers, but not the way a container registry does.", code="not_registry",
                               hint="The URL is the address of the registry itself, without /v2.")
        repositories, _ = await self.repositories(config, ctx)
        if repositories is None:
            return "The registry answers. It does not list its repositories, so read it through the images named on a card."
        return f"The registry answers, {len(repositories)}{'+' if len(repositories) >= 1000 else ''} repositories."

    # -- the cards ------------------------------------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "images":
            return await self._images(config, options, ctx)
        repositories, cut = await self.repositories(config, ctx)
        if repositories is None:
            raise AdapterError("This registry does not list its repositories.", code="no_catalog",
                               hint="ghcr.io and Docker Hub do not; name the images on the Newest versions card instead.")
        repositories = [repo for repo in repositories if NAME.match(repo)]
        if widget_kind == "overview":
            counted = repositories[:COUNTED]
            total = 0
            for repo in counted:
                tags, _ = await self.tags(config, ctx, repo)
                total += len(tags or [])
            return self.overview_card(len(repositories), total, len(repositories) > COUNTED or cut, base_url(config))
        needle = str(options.get("filter") or "").strip().casefold()
        shown = [repo for repo in repositories if needle in repo.casefold()][: max(1, min(50, int(options.get("limit") or 10)))]
        found: list[tuple[str, list[str]]] = []
        for repo in shown:
            tags, _ = await self.tags(config, ctx, repo)
            found.append((repo, tags or []))
        return self.repositories_card(found, len(repositories), cut, base_url(config))

    async def _images(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        host = urlsplit(base_url(config)).netloc
        images = parse_images(str(options.get("images") or ""), host, self._hub(config))
        if not images:
            raise AdapterError("No image is set.", code="missing_image")
        found: list[dict[str, Any]] = []
        failures: list[str] = []
        for repo, current in images:
            try:
                tags, _cut = await self.tags(config, ctx, repo)
                if tags is None:
                    failures.append(f"{repo}: not found, or the account may not pull it")
                    continue
                newest = newest_tag(tags, current)
                facts = await self.image_facts(config, ctx, repo, newest) if newest else {}
            except AuthFailed:
                raise
            except AdapterError as error:
                if error.code in ("unreachable", "rate_limited"):
                    raise
                failures.append(f"{repo}: {error.message}")
                continue
            found.append({"repo": repo, "current": current, "newest": newest, "tags": len(tags), **facts})
        data = self.images_card(found)
        data.meta = {**(data.meta or {}), "failures": failures}
        if failures and not data.items:
            data.error = "; ".join(failures)
            data.status = "bad"
        return data

    @staticmethod
    def overview_card(repositories: int, tags: int, more: bool, link: str | None = None) -> WidgetData:
        return WidgetData(
            status="ok",
            primary={"label": "Repositories", "value": repositories},
            secondary=[{"label": "Tags", "value": f"{tags}+" if more else tags}],
            metrics={"repositories": float(repositories), "tags": float(tags)},
            link=link,
        )

    @staticmethod
    def repositories_card(found: list[tuple[str, list[str]]], total: int, cut: bool, link: str | None = None) -> WidgetData:
        items = []
        for repo, tags in found:
            newest = newest_tag(tags)
            items.append({
                "title": repo,
                "subtitle": f"{len(tags)} tags" if len(tags) != 1 else "1 tag",
                "value": newest or "",
                "status": "ok",
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Repositories", "value": f"{total}+" if cut else total}],
            link=link,
            meta={"empty": "The registry has no repository."},
        )

    @staticmethod
    def images_card(found: list[dict[str, Any]], now: float | None = None) -> WidgetData:
        rows = []
        behind = 0
        for one in found:
            newest, current = one.get("newest"), str(one.get("current") or "")
            late = bool(newest and current and is_behind(current, newest))
            behind += 1 if late else 0
            if not newest:
                row = {"title": one["repo"], "subtitle": "No version tag" if one.get("tags") else "No tags", "status": "unknown", "value": ""}
            else:
                age = ago(one.get("created"), now) if one.get("created") else ""
                parts = ("Update available" if late else "", f"running {current}" if current and late else "", f"{age} old" if age else "",
                         human_bytes(one["size"]) if one.get("size") else "")
                row = {"title": one["repo"], "subtitle": " · ".join(part for part in parts if part), "status": "warn" if late else "ok", "value": newest}
            rows.append((row["status"] != "warn", row))
        rows.sort(key=lambda entry: entry[0])
        return WidgetData(
            status="warn" if behind else "ok",
            items=[row for _late, row in rows],
            secondary=[{"label": "Behind", "value": behind}],
            metrics={"behind": float(behind)},
            meta={"empty": "No image is set."},
        )

    # -- demo -----------------------------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time() - tick % 60
        if widget_kind == "overview":
            return self.overview_card(14, 96 + int(fake.walk("registry-tags", tick, 0, 4)), False)
        if widget_kind == "repositories":
            return self.repositories_card([
                ("example/api", ["1.8.0", "1.9.0", "1.10.0", "latest"]), ("example/web", ["2.3.1", "2.4.0", "v2.4.1"]),
                ("team/tool", ["0.3.1"]), ("mirror/alpine", ["3.19", "3.20", "3.22", "edge"]),
            ], 14, False)
        late = (tick // 600) % 2 == 0
        return self.images_card([
            {"repo": "library/nginx", "current": "1.25.3" if late else "1.27.3", "newest": "1.27.3", "tags": 140, "created": "2026-10-02T09:00:00Z", "size": 69_000_000},
            {"repo": "example/api", "current": "1.9.0", "newest": "1.10.0", "tags": 12, "created": "2026-10-20T12:30:00Z", "size": 41_000_000},
            {"repo": "grafana/grafana", "current": "", "newest": "12.2.0", "tags": 300, "created": "2026-09-30T08:00:00Z", "size": 190_000_000},
        ], now)


ADAPTER = RegistryAdapter()
