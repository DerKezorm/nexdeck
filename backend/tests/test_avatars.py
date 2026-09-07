"""Profile pictures: upload, replace, remove, serve."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin

#: A real one-pixel PNG, so the check looks at bytes that are a picture.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def upload(client: TestClient, data: bytes, filename: str = "face.png", content_type: str = "image/png") -> dict:
    response = client.post("/api/v1/auth/me/avatar", files={"file": (filename, data, content_type)}, headers=CSRF)
    return {"status": response.status_code, "body": response.json() if response.content else None}


def test_upload_sets_the_picture_and_serves_it(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    assert client.get("/api/v1/auth/me").json()["avatar_url"] is None

    result = upload(client, PNG)
    assert result["status"] == 200, result
    url = result["body"]["avatar_url"]
    assert url and url.startswith("/api/v1/avatars/")
    assert client.get("/api/v1/auth/me").json()["avatar_url"] == url

    stored = list((data_dir / "avatars").iterdir())
    assert len(stored) == 1 and stored[0].suffix == ".png"

    served = client.get(url)
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"


def test_a_new_picture_replaces_the_old_file(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    first = upload(client, PNG)["body"]["avatar_url"]
    second = upload(client, PNG + b"\x00")["body"]["avatar_url"]
    assert first != second, "every picture gets its own address"
    assert len(list((data_dir / "avatars").iterdir())) == 1, "the old file must be gone"
    assert client.get(first).status_code == 404
    assert client.get(second).status_code == 200


def test_removing_the_picture_clears_user_and_disk(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    url = upload(client, PNG)["body"]["avatar_url"]
    response = client.delete("/api/v1/auth/me/avatar", headers=CSRF)
    assert response.status_code == 200
    assert response.json()["avatar_url"] is None
    assert list((data_dir / "avatars").iterdir()) == []
    assert client.get(url).status_code == 404


def test_only_pictures_are_accepted(client: TestClient) -> None:
    setup_admin(client)
    refused = upload(client, b"<svg onload=alert(1)></svg>", "logo.svg", "image/svg+xml")
    assert refused["status"] == 400
    assert refused["body"]["detail"]["code"] == "bad_type"
    # The name and the declared type do not decide; the first bytes do.
    disguised = upload(client, b"MZ this is a program", "face.png", "image/png")
    assert disguised["status"] == 400
    assert client.get("/api/v1/auth/me").json()["avatar_url"] is None


def test_a_large_picture_is_refused(client: TestClient) -> None:
    setup_admin(client)
    too_big = upload(client, PNG + b"\x00" * (2 * 1024 * 1024 + 1))
    # 413, not 400: one status for "too large" on all three upload paths. The
    # picture used to be weighed after the whole body had been read, and the
    # refusal came out of the avatar reader with the generic 400.
    assert too_big["status"] == 413
    assert too_big["body"]["detail"]["code"] == "too_large"


def test_pictures_need_a_session(client: TestClient) -> None:
    setup_admin(client)
    url = upload(client, PNG)["body"]["avatar_url"]
    stranger = TestClient(client.app)
    assert stranger.get(url).status_code == 401


def test_every_account_has_its_own_picture(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    admin_url = upload(client, PNG)["body"]["avatar_url"]

    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    assert other.get("/api/v1/auth/me").json()["avatar_url"] is None
    kim_url = upload(other, PNG + b"\x00")["body"]["avatar_url"]
    assert kim_url != admin_url
    # Both lists carry the pictures: the short one every member sees, and the
    # full one for administrators. Boards are shared from those lists.
    for who in (other, client):
        listed = {row["username"]: row.get("avatar_url") for row in who.get("/api/v1/users").json()}
        assert listed == {"admin": admin_url, "kim": kim_url}


def test_deleting_an_account_deletes_its_picture(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    kim = create_user(client, "kim")
    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    upload(other, PNG)
    assert len(list((data_dir / "avatars").iterdir())) == 1

    assert client.delete(f"/api/v1/users/{kim['id']}", headers=CSRF).status_code == 204
    assert list((data_dir / "avatars").iterdir()) == [], "an account takes its picture with it"


def test_a_stored_name_cannot_leave_the_folder(client: TestClient, data_dir: Path) -> None:
    """The name comes from the database, and is still cut down to its last part."""
    setup_admin(client)
    from app.services import avatars

    assert (data_dir / "nexdeck.db").exists()
    try:
        avatars.read("../nexdeck.db")
    except avatars.AvatarError as failure:
        assert failure.code == "not_found"
    else:  # pragma: no cover - would mean the guard is gone
        raise AssertionError("reading outside the avatar folder must fail")
