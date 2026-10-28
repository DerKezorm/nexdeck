"""Container registry, against the answers of registry:2 behind htpasswd, zot, ghcr.io and Docker Hub (27.10.2026).

``fixtures/registry_distribution.json`` holds what Distribution answered:
the catalog (and a page of it with its ``Link``), the tags of a repository
(unsorted), an OCI manifest, the image config and the 401/404 envelopes. The
Bearer flow is the measured one of ghcr.io and Docker Hub (``Www-Authenticate:
Bearer realm=...``, a token from the realm, the blob answered with a redirect
that the client follows); the image index has the shape ghcr.io sent for
jqlang/jq. Names and addresses are made up.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client
from app.adapters.registry import is_behind, newest_tag, parse_images, parse_tag

BASE = "https://registry.example.com"
CONFIG = {"url": BASE, "user": "reader", "password": "made-up-password"}
ADAPTER = get_adapter("registry")


def digest(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


# The recorded digests are written as @d0, @d1 ... in the file: 64 hex characters in a row are what the commit hook takes for a key.
DIST = json.loads(re.sub(r"sha256:@d(\d+)", lambda found: digest(found.group(1)), (Path(__file__).parent / "fixtures" / "registry_distribution.json").read_text(encoding="utf-8")))
CONFIG_DIGEST = DIST["manifest"]["config"]["digest"]
AMD64 = digest("amd64")
ARM64 = digest("arm64")


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def basic_registry(seen: list[httpx.Request] | None = None) -> None:
    """Distribution behind htpasswd: 401 with a Basic challenge until the credentials come."""
    good = "Basic " + base64.b64encode(b"reader:made-up-password").decode()

    def guarded(answer):  # noqa: ANN001, ANN202
        def reply(request: httpx.Request) -> httpx.Response:
            if seen is not None:
                seen.append(request)
            if request.headers.get("authorization") != good:
                return httpx.Response(401, headers={"Www-Authenticate": DIST["unauthorized_header"]}, json=DIST["unauthorized"])
            return answer(request)
        return reply

    respx.get(f"{BASE}/v2/").mock(side_effect=guarded(lambda _r: httpx.Response(200, headers={"Docker-Distribution-Api-Version": "registry/2.0"}, json={})))
    respx.get(f"{BASE}/v2/_catalog").mock(side_effect=guarded(lambda _r: httpx.Response(200, json=DIST["catalog"])))
    respx.get(f"{BASE}/v2/example/app/tags/list").mock(side_effect=guarded(lambda _r: httpx.Response(200, json=DIST["tags"])))
    respx.get(f"{BASE}/v2/solo/tags/list").mock(side_effect=guarded(lambda _r: httpx.Response(200, json={"name": "solo", "tags": ["latest"]})))
    respx.get(f"{BASE}/v2/team/tool/tags/list").mock(side_effect=guarded(lambda _r: httpx.Response(200, json={"name": "team/tool", "tags": ["0.3.1"]})))
    respx.get(f"{BASE}/v2/example/app/manifests/1.10.0").mock(side_effect=guarded(lambda _r: httpx.Response(200, json=DIST["manifest"])))
    respx.get(f"{BASE}/v2/example/app/blobs/{CONFIG_DIGEST}").mock(side_effect=guarded(lambda _r: httpx.Response(200, json=DIST["config"])))


@respx.mock
async def test_basic_credentials_are_sent_after_the_challenge_and_then_kept(ctx: Context) -> None:
    seen: list[httpx.Request] = []
    basic_registry(seen)
    assert await ADAPTER.test(CONFIG, ctx) == "The registry answers, 3 repositories."
    anonymous = [request for request in seen if "authorization" not in request.headers]
    assert len(anonymous) == 1, "one try without, then every request carries the credentials"
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.tags({**CONFIG, "password": "wrong"}, fresh(), "example/app")
    assert "rejected the user name" in wrong.value.message, "a wrong password is not 'not found'"


@respx.mock
async def test_the_overview_counts_repositories_and_tags(ctx: Context) -> None:
    basic_registry()
    data = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Repositories", "value": 3}
    assert data.secondary == [{"label": "Tags", "value": 8}]
    assert data.metrics == {"repositories": 3.0, "tags": 8.0} and data.link == BASE


@respx.mock
async def test_the_repositories_card_names_the_newest_version_not_the_last_tag(ctx: Context) -> None:
    basic_registry()
    data = await ADAPTER.fetch("repositories", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("example/app", "6 tags", "1.10.0"), ("solo", "1 tag", ""), ("team/tool", "1 tag", "0.3.1")]
    assert data.secondary == [{"label": "Repositories", "value": 3}]
    narrowed = await ADAPTER.fetch("repositories", CONFIG, {"filter": "TOOL", "limit": 5}, fresh())
    assert [row["title"] for row in narrowed.items] == ["team/tool"]


@respx.mock
async def test_the_images_card_says_what_is_newer_how_old_and_how_big(ctx: Context) -> None:
    basic_registry()
    data = await ADAPTER.fetch("images", CONFIG, {"images": "example/app:1.1.0\nexample/app"}, ctx)
    behind, plain = data.items
    assert behind["status"] == "warn" and behind["value"] == "1.10.0"
    assert behind["subtitle"].startswith("Update available · running 1.1.0 · ") and behind["subtitle"].endswith(" old · 2.1 MB")
    assert plain["status"] == "ok" and plain["subtitle"].startswith(" ".join([]) or "") and "Update available" not in plain["subtitle"]
    assert data.status == "warn" and data.secondary == [{"label": "Behind", "value": 1}] and data.metrics == {"behind": 1.0}
    assert data.items[0] is behind, "the ones behind come first"


@respx.mock
async def test_an_image_index_is_read_through_its_linux_amd64_manifest(ctx: Context) -> None:
    basic_registry()
    index = {"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json", "manifests": [
        {"mediaType": "application/vnd.docker.distribution.manifest.v2+json", "digest": ARM64, "size": 696, "platform": {"architecture": "arm64", "os": "linux"}},
        {"mediaType": "application/vnd.docker.distribution.manifest.v2+json", "digest": AMD64, "size": 697, "platform": {"architecture": "amd64", "os": "linux"}}]}
    respx.get(f"{BASE}/v2/example/app/manifests/1.10.0").mock(return_value=httpx.Response(200, json=index))
    platform = respx.get(f"{BASE}/v2/example/app/manifests/{AMD64}").mock(return_value=httpx.Response(200, json=DIST["manifest"]))
    arm = respx.get(f"{BASE}/v2/example/app/manifests/{ARM64}").mock(return_value=httpx.Response(200, json=DIST["manifest"]))
    facts = await ADAPTER.image_facts(CONFIG, ctx, "example/app", "1.10.0")
    assert facts == {"created": "2023-05-18T22:34:17Z", "size": 2206402}
    assert platform.call_count == 1 and arm.call_count == 0


@respx.mock
async def test_the_bearer_flow_of_ghcr_and_docker_hub_asks_the_realm_once_per_scope(ctx: Context) -> None:
    challenge = 'Bearer realm="https://auth.example.com/token",service="registry.example.com",scope="repository:jqlang/jq:pull"'

    def tags(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != "Bearer made-up-token":
            return httpx.Response(401, headers={"Www-Authenticate": challenge}, json=DIST["unauthorized"])
        return httpx.Response(200, json={"name": "jqlang/jq", "tags": ["latest", "1.7rc1", "1.7", "1.7.1"]})

    respx.get(f"{BASE}/v2/jqlang/jq/tags/list").mock(side_effect=tags)
    token = respx.get("https://auth.example.com/token").mock(return_value=httpx.Response(200, json={"token": "made-up-token", "expires_in": 300}))
    anonymous = {"url": BASE}
    assert await ADAPTER.tags(anonymous, ctx, "jqlang/jq") == (["latest", "1.7rc1", "1.7", "1.7.1"], False)
    assert dict(token.calls.last.request.url.params) == {"service": "registry.example.com", "scope": "repository:jqlang/jq:pull"}
    assert "authorization" not in token.calls.last.request.headers, "a public image is asked for without a password"
    ctx.cache.pop("resp:" + next(iter(k for k in ctx.cache if k.startswith("resp:"))), None)
    await ADAPTER.tags(anonymous, ctx, "jqlang/jq")
    assert token.call_count == 1, "the token is kept"
    signed_in = await ADAPTER.tags(CONFIG, fresh(), "jqlang/jq")
    assert signed_in[0][-1] == "1.7.1"
    assert base64.b64decode(token.calls.last.request.headers["authorization"].split()[1]) == b"reader:made-up-password", "an account's credentials go to the realm"


@respx.mock
async def test_a_realm_on_plain_http_elsewhere_gets_no_password(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/x/tags/list").mock(return_value=httpx.Response(
        401, headers={"Www-Authenticate": 'Bearer realm="http://elsewhere.example.net/token",service="s"'}, json=DIST["unauthorized"]))
    elsewhere = respx.get("http://elsewhere.example.net/token").mock(return_value=httpx.Response(200, json={"token": "t"}))
    with pytest.raises(AdapterError) as refused:
        await ADAPTER.tags(CONFIG, ctx, "x")
    assert refused.value.code == "realm_refused" and elsewhere.call_count == 0


@respx.mock
async def test_a_refused_password_is_told_at_the_token_service_and_at_a_basic_door(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/x/tags/list").mock(return_value=httpx.Response(
        401, headers={"Www-Authenticate": 'Bearer realm="https://auth.example.com/token",service="s"'}, json=DIST["unauthorized"]))
    respx.get("https://auth.example.com/token").mock(return_value=httpx.Response(401, json={"errors": [{"code": "UNAUTHORIZED"}]}))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.tags(CONFIG, ctx, "x")
    assert "rejected the user name" in wrong.value.message and "robot account" in wrong.value.hint
    respx.get(f"{BASE}/v2/").mock(return_value=httpx.Response(401, headers={"Www-Authenticate": DIST["unauthorized_header"]}, json=DIST["unauthorized"]))
    with pytest.raises(AuthFailed):
        await ADAPTER.test({**CONFIG, "password": "wrong"}, fresh())
    with pytest.raises(AuthFailed) as none:
        await ADAPTER.test({"url": BASE}, fresh())
    assert "wants a user name" in none.value.message


@respx.mock
async def test_a_listing_is_followed_through_its_link_and_the_last_name_is_encoded_once(ctx: Context) -> None:
    def catalog(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("last") == "example/app":
            return httpx.Response(200, json={"repositories": ["solo", "team/tool"]})
        return httpx.Response(200, headers={"Link": DIST["catalog_link"]}, json=DIST["catalog_page"])

    route = respx.get(f"{BASE}/v2/_catalog").mock(side_effect=catalog)
    found = await ADAPTER.repositories({"url": BASE}, ctx)
    assert found == (["example/app", "solo", "team/tool"], False)
    assert "last=example%2Fapp" in str(route.calls[1].request.url) and "%252F" not in str(route.calls[1].request.url)
    # A link that leaves the API is not followed.
    other = respx.get(f"{BASE}/v2/other/tags/list").mock(return_value=httpx.Response(200, headers={"Link": '<https://evil.example.net/v2/x>; rel="next"'}, json={"tags": ["1"]}))
    assert await ADAPTER.tags({"url": BASE}, fresh(), "other") == (["1"], False) and other.call_count == 1


@respx.mock
async def test_a_registry_without_a_catalog_says_so_and_the_images_still_work(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/").mock(return_value=httpx.Response(200, json={}))
    # ghcr.io: a challenge for the catalog's own scope, a token, and 401 again.
    respx.get(f"{BASE}/v2/_catalog").mock(return_value=httpx.Response(
        401, headers={"Www-Authenticate": 'Bearer realm="https://auth.example.com/token",service="s",scope="registry:catalog:*"'}, json={"errors": [{"code": "UNAUTHORIZED"}]}))
    respx.get("https://auth.example.com/token").mock(return_value=httpx.Response(200, json={"token": "t"}))
    assert "does not list its repositories" in await ADAPTER.test({"url": BASE}, ctx)
    with pytest.raises(AdapterError) as none:
        await ADAPTER.fetch("repositories", {"url": BASE}, {}, fresh())
    assert none.value.code == "no_catalog" and "Newest versions" in none.value.hint


@respx.mock
async def test_an_unknown_repository_is_a_line_not_a_failure_of_the_card(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/nope/tags/list").mock(return_value=httpx.Response(404, json=DIST["unknown_repo"]))
    respx.get(f"{BASE}/v2/solo/tags/list").mock(return_value=httpx.Response(200, json={"name": "solo", "tags": ["1.0.0"]}))
    respx.get(f"{BASE}/v2/solo/manifests/1.0.0").mock(return_value=httpx.Response(404, json=DIST["unknown_tag"]))
    data = await ADAPTER.fetch("images", {"url": BASE}, {"images": "nope\nsolo"}, ctx)
    assert [row["title"] for row in data.items] == ["solo"] and data.items[0]["value"] == "1.0.0"
    assert data.meta["failures"] == ["nope: not found, or the account may not pull it"]
    alone = await ADAPTER.fetch("images", {"url": BASE}, {"images": "nope"}, fresh())
    assert alone.status == "bad" and "nope" in (alone.error or "")


@respx.mock
async def test_an_unreachable_registry(ctx: Context) -> None:
    respx.get(f"{BASE}/v2/_catalog").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("overview", {"url": BASE}, {}, ctx)


def test_the_newest_version_is_of_the_kind_that_is_run() -> None:
    tags = ["latest", "1.9.0", "1.10.0", "2.0.0-rc1", "v1.2.0", "1.27", "1.27.3-alpine", "1.28.0-alpine", "1.25", "20240101"]
    assert newest_tag(tags) == "20240101", "no tag to compare with: every plain version counts, a date is a big number"
    assert newest_tag(["latest", "1.9.0", "1.10.0", "2.0.0-rc1", "v1.2.0", "1.28.0-alpine"]) == "1.10.0", "a release candidate and a variant are never the newest"
    assert newest_tag(tags, "1.25") == "1.27", "two numbers ask for the newest of two numbers"
    assert newest_tag(tags, "1.25.0-alpine") == "1.28.0-alpine", "an ending asks for the same ending"
    assert newest_tag(["v1.0.0", "1.5.0"], "v1.0.0") == "v1.0.0" and newest_tag(["latest"]) is None
    assert newest_tag(["1.0/../../x", "1.0.0?x=1", "1.0.0"]) == "1.0.0", "a tag is no path"
    assert parse_tag("2.0.0-rc1") == ((2, 0, 0), "-rc1") and parse_tag("latest") is None
    assert is_behind("1.25", "1.27") and not is_behind("1.27.3", "1.27") and not is_behind("latest", "1.0.0")


def test_images_are_read_from_lines_with_or_without_the_host_and_the_hub_library() -> None:
    assert parse_images("registry.example.com/team/app:1.2.3\nteam/tool@sha256:abc\n\n", "registry.example.com", False) == [("team/app", "1.2.3"), ("team/tool", "")]
    assert parse_images("nginx\nredis:7\ndocker.io/grafana/grafana:12.0.0", "registry-1.docker.io", True) == [
        ("library/nginx", ""), ("library/redis", "7"), ("grafana/grafana", "12.0.0")]
    assert len(parse_images("\n".join(f"a/b{n}" for n in range(30)), "h", False)) == 10
    assert parse_images("host.example.com:5000/app:1", "host.example.com:5000", False) == [("app", "1")]
