"""The name and the logo of the installation: public to read, admin to change."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" fill="#16a34a"/></svg>'


def png(width: int, height: int) -> bytes:
    """A PNG header of the given size: the server reads the header, not the pixels."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IEND", b"")


def upload(client: TestClient, logo: bytes = SVG, content_type: str = "image/svg+xml", small: bytes | None = None, large: bytes | None = None):  # noqa: ANN201
    return client.post(
        "/api/v1/settings/brand/logo",
        files={
            "logo": ("logo.svg", logo, content_type),
            "icon192": ("icon-192.png", small if small is not None else png(192, 192), "image/png"),
            "icon512": ("icon-512.png", large if large is not None else png(512, 512), "image/png"),
        },
        headers=CSRF,
    )


def test_without_a_name_or_logo_everything_says_nexdeck(client: TestClient) -> None:
    setup_admin(client)
    client.cookies.clear()
    answer = client.get("/api/v1/brand")
    assert answer.status_code == 200, "the sign-in page reads it before anyone signs in"
    assert answer.json() == {"name": "", "logo": None, "favicon": None, "app_icons": None, "board_in_title": True}


def test_an_administrator_names_the_installation(client: TestClient) -> None:
    setup_admin(client)
    saved = client.put("/api/v1/settings/brand", json={"name": "  Homelab\nNord  "}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "HomelabNord", "line breaks have no place in a title"
    client.cookies.clear()
    assert client.get("/api/v1/brand").json()["name"] == "HomelabNord"


def test_a_name_too_long_for_the_bar_gets_a_sentence(client: TestClient) -> None:
    setup_admin(client)
    answer = client.put("/api/v1/settings/brand", json={"name": "x" * 41}, headers=CSRF)
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "name_too_long"


def test_only_an_administrator_changes_it(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "member")
    login(client, "member", "another-long-password")
    assert client.put("/api/v1/settings/brand", json={"name": "Mine"}, headers=CSRF).status_code == 403
    assert upload(client).status_code == 403
    assert client.delete("/api/v1/settings/brand/logo", headers=CSRF).status_code == 403
    assert client.get("/api/v1/brand").json()["name"] == ""


def test_a_logo_is_served_to_everyone_in_a_sandbox(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    answer = upload(client)
    assert answer.status_code == 200, answer.text
    client.cookies.clear()
    brand = client.get("/api/v1/brand").json()
    assert brand["logo"].startswith("/api/v1/brand/logo?v=")
    assert brand["favicon"] == brand["logo"]
    assert set(brand["app_icons"]) == {"192", "512"}
    served = client.get(brand["logo"])
    assert served.status_code == 200
    assert served.content == SVG
    assert served.headers["content-type"].startswith("image/svg+xml")
    assert served.headers["content-security-policy"].startswith("sandbox"), "an SVG must not run in nexdeck's origin"
    icon = client.get(brand["app_icons"]["512"])
    assert icon.status_code == 200 and icon.headers["content-type"] == "image/png"
    assert sorted(path.name for path in (data_dir / "brand").iterdir()) == ["icon-192.png", "icon-512.png", "logo.svg"]


def test_a_new_logo_gets_a_new_address_and_replaces_the_old_file(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    upload(client)
    first = client.get("/api/v1/brand").json()["logo"]
    upload(client, png(64, 64), "image/png")
    second = client.get("/api/v1/brand").json()["logo"]
    assert first != second, "no browser may keep showing the old one"
    assert sorted(path.name for path in (data_dir / "brand").iterdir()) == ["icon-192.png", "icon-512.png", "logo.png"]


@pytest.mark.parametrize(
    ("logo", "content_type", "code"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "image/svg+xml", "bad_svg"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml", "bad_svg"),
        (b"<html><body>not a picture</body></html>", "image/svg+xml", "bad_type"),
        (b"GIF89a....", "image/gif", "bad_type"),
        (b"", "image/png", "empty"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * (512 * 1024), "image/png", "too_large"),
    ],
    # ⚠️ Named, not shown: pytest puts the id into an environment variable, and half a megabyte does not fit.
    ids=["svg-handler", "svg-script", "html", "gif", "empty", "too-large"],
)
def test_a_logo_that_is_not_safe_or_not_a_picture_is_refused(client: TestClient, logo: bytes, content_type: str, code: str) -> None:
    setup_admin(client)
    answer = upload(client, logo, content_type)
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == code
    assert client.get("/api/v1/brand").json()["logo"] is None


@pytest.mark.parametrize(("small", "large"), [(png(512, 512), png(512, 512)), (png(192, 192), png(512, 511)), (png(192, 192), SVG)], ids=["small-too-big", "large-off-by-one", "large-not-png"])
def test_app_icons_have_to_be_pngs_of_their_size(client: TestClient, small: bytes, large: bytes) -> None:
    setup_admin(client)
    answer = upload(client, small=small, large=large)
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "bad_icon"


def test_the_tab_and_the_app_can_keep_nexdecks_mark(client: TestClient) -> None:
    setup_admin(client)
    upload(client)
    client.put("/api/v1/settings/brand", json={"name": "Homelab", "favicon": "nexdeck", "app_icon": "nexdeck", "board_in_title": False}, headers=CSRF)
    brand = client.get("/api/v1/brand").json()
    assert brand["logo"] is not None
    assert brand["favicon"] is None
    assert brand["app_icons"] is None
    assert brand["board_in_title"] is False


def test_a_choice_that_is_not_offered_is_refused(client: TestClient) -> None:
    setup_admin(client)
    answer = client.put("/api/v1/settings/brand", json={"favicon": "somewhere-else"}, headers=CSRF)
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "bad_favicon"


def test_removing_the_logo_takes_the_files(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    upload(client)
    address = client.get("/api/v1/brand").json()["logo"]
    answer = client.delete("/api/v1/settings/brand/logo", headers=CSRF)
    assert answer.status_code == 200
    assert client.get("/api/v1/brand").json()["logo"] is None
    assert client.get(address).status_code == 404
    assert list((data_dir / "brand").iterdir()) == []


def test_the_installed_app_takes_the_name_and_the_icons(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    built = tmp_path / "static"
    built.mkdir()
    (built / "manifest.webmanifest").write_text(json.dumps({"name": "nexdeck", "short_name": "nexdeck", "icons": [{"src": "/icon-192.png"}], "display": "standalone"}))
    monkeypatch.setattr(main, "_static_dir", lambda: built)
    setup_admin(client)
    plain = client.get("/manifest.webmanifest").json()
    assert plain["name"] == "nexdeck" and plain["icons"] == [{"src": "/icon-192.png"}], "unchanged without a brand"

    client.put("/api/v1/settings/brand", json={"name": "Homelab Nord"}, headers=CSRF)
    upload(client)
    branded = client.get("/manifest.webmanifest")
    assert branded.headers["content-type"].startswith("application/manifest+json")
    body = branded.json()
    assert body["name"] == body["short_name"] == "Homelab Nord"
    assert [icon["sizes"] for icon in body["icons"]] == ["192x192", "512x512", "512x512"]
    assert body["icons"][0]["src"].startswith("/api/v1/brand/icon-192.png?v=")
    assert body["display"] == "standalone", "the rest of the manifest stays"


def test_the_logo_travels_with_a_backup(client: TestClient) -> None:
    """⚠️ Like the profile pictures: the setting holds the file name, the file lives beside the database."""
    from .test_backup import _archive, _inside, _make

    setup_admin(client)
    upload(client)
    entry = _make(client)
    files = _inside(_archive(client, entry["name"]))
    assert files.get("brand/logo.svg") == SVG
    assert "brand/icon-512.png" in files
