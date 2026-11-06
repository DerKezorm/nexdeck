"""API tests for Synology trusted-device enrolment."""

from unittest.mock import AsyncMock, patch

from app.adapters.base import AuthFailed
from app.services.integrations import resolve_config
from tests.conftest import CSRF, setup_admin


def make_integration(client, kind="synology"):
    response = client.post(
        "/api/v1/integrations",
        json={
            "kind": kind,
            "name": "MFA Test NAS",
            "config": {
                "url": "https://nas.example:5001",
                "username": "testuser",
                "password": "testpassword",
                "insecure": True,
            },
        },
        headers=CSRF,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_successful_enrolment_encrypts_device_id(client):
    setup_admin(client)
    integration_id = make_integration(client)

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="trusted-device-secret",
    ) as enrol:
        response = client.post(
            f"/api/v1/integrations/{integration_id}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    enrol.assert_awaited_once()

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert integration is not None
        assert "trusted-device-secret" not in str(integration.config)
        assert "123456" not in str(integration.config)
        assert resolve_config(integration)["device_id"] == "trusted-device-secret"


def test_failed_enrolment_preserves_existing_credential(client):
    setup_admin(client)
    integration_id = make_integration(client)

    url = f"/api/v1/integrations/{integration_id}/mfa/enrol"

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="original-device",
    ):
        first = client.post(url, json={"otp": "123456"}, headers=CSRF)

    assert first.status_code == 200, first.text

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        side_effect=AuthFailed("Invalid OTP"),
    ):
        failed = client.post(url, json={"otp": "654321"}, headers=CSRF)

    assert failed.status_code == 400

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert resolve_config(integration)["device_id"] == "original-device"


def test_invalid_otp_format_is_rejected(client):
    setup_admin(client)
    integration_id = make_integration(client)

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
    ) as enrol:
        response = client.post(
            f"/api/v1/integrations/{integration_id}/mfa/enrol",
            json={"otp": "12345x"},
            headers=CSRF,
        )

    assert response.status_code == 422
    enrol.assert_not_awaited()


def test_non_admin_cannot_enrol(client):
    from tests.conftest import create_user, login

    setup_admin(client)
    integration_id = make_integration(client)

    create_user(client, "ordinary-user", role="user")
    login(client, "ordinary-user", "another-long-password")

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
    ) as enrol:
        response = client.post(
            f"/api/v1/integrations/{integration_id}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert response.status_code == 403, response.text
    enrol.assert_not_awaited()


def test_unauthenticated_user_cannot_enrol(client):
    setup_admin(client)
    integration_id = make_integration(client)

    client.post("/api/v1/auth/logout", headers=CSRF)

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
    ) as enrol:
        response = client.post(
            f"/api/v1/integrations/{integration_id}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert response.status_code in (401, 403), response.text
    enrol.assert_not_awaited()


def test_changing_synology_identity_clears_device(client):
    setup_admin(client)
    integration_id = make_integration(client)

    url = f"/api/v1/integrations/{integration_id}"

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="original-device",
    ):
        enrolled = client.post(
            f"{url}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert enrolled.status_code == 200

    updated = client.patch(
        url,
        json={"config": {"username": "different-user"}},
        headers=CSRF,
    )

    assert updated.status_code == 200, updated.text

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert not resolve_config(integration).get("device_id")


def test_unrelated_change_preserves_device(client):
    setup_admin(client)
    integration_id = make_integration(client)

    url = f"/api/v1/integrations/{integration_id}"

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="original-device",
    ):
        enrolled = client.post(
            f"{url}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert enrolled.status_code == 200

    updated = client.patch(
        url,
        json={
            "config": {
                "insecure": False,
                "password": "********",
            }
        },
        headers=CSRF,
    )

    assert updated.status_code == 200, updated.text

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert resolve_config(integration)["device_id"] == "original-device"


import pytest


@pytest.mark.parametrize(
    "changed_config",
    [
        {"url": "https://different-nas.example:5001"},
        {"password": "a-new-password"},
    ],
    ids=["nas-url", "password"],
)
def test_identity_changes_invalidate_device(client, changed_config):
    setup_admin(client)
    integration_id = make_integration(client)
    url = f"/api/v1/integrations/{integration_id}"

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="original-device",
    ):
        enrolled = client.post(
            f"{url}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert enrolled.status_code == 200

    updated = client.patch(
        url,
        json={"config": changed_config},
        headers=CSRF,
    )
    assert updated.status_code == 200, updated.text

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert not resolve_config(integration).get("device_id")


def test_cannot_create_synology_with_manual_device_id(client):
    setup_admin(client)

    response = client.post(
        "/api/v1/integrations",
        json={
            "kind": "synology",
            "name": "Manual Device Test",
            "config": {
                "url": "https://nas.example:5001",
                "username": "testuser",
                "password": "testpassword",
                "device_id": "injected-device-token",
            },
        },
        headers=CSRF,
    )

    assert response.status_code == 400, response.text
    assert "injected-device-token" not in response.text


def test_cannot_overwrite_enrolled_device_id(client):
    setup_admin(client)
    integration_id = make_integration(client)

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="legitimate-device",
    ):
        enrolled = client.post(
            f"/api/v1/integrations/{integration_id}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert enrolled.status_code == 200, enrolled.text

    response = client.patch(
        f"/api/v1/integrations/{integration_id}",
        json={
            "config": {
                "device_id": "injected-device-token",
            }
        },
        headers=CSRF,
    )

    assert response.status_code == 400, response.text
    assert "injected-device-token" not in response.text

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert resolve_config(integration)["device_id"] == "legitimate-device"


def test_unenrol_removes_device_but_preserves_connection(client):
    setup_admin(client)
    integration_id = make_integration(client)

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        new_callable=AsyncMock,
        return_value="trusted-device-secret",
    ):
        enrolled = client.post(
            f"/api/v1/integrations/{integration_id}/mfa/enrol",
            json={"otp": "123456"},
            headers=CSRF,
        )

    assert enrolled.status_code == 200, enrolled.text

    response = client.post(
        f"/api/v1/integrations/{integration_id}/mfa/unenrol",
        headers=CSRF,
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        config = resolve_config(integration)

        assert "device_id" not in config
        assert config["url"] == "https://nas.example:5001"
        assert config["username"] == "testuser"
        assert config["password"] == "testpassword"


def test_non_admin_cannot_unenrol(client):
    from tests.conftest import create_user, login

    setup_admin(client)
    integration_id = make_integration(client)

    create_user(client, "ordinary-user", role="user")
    login(client, "ordinary-user", "another-long-password")

    response = client.post(
        f"/api/v1/integrations/{integration_id}/mfa/unenrol",
        headers=CSRF,
    )

    assert response.status_code == 403, response.text


def test_unenrol_without_existing_device_is_safe(client):
    setup_admin(client)
    integration_id = make_integration(client)

    response = client.post(
        f"/api/v1/integrations/{integration_id}/mfa/unenrol",
        headers=CSRF,
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True


def test_unenrol_wins_over_pending_enrolment(client):
    """A delayed MFA response must not restore an un-enrolled device."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.db import db_session
    from app.models import Integration

    setup_admin(client)
    integration_id = make_integration(client)

    started = threading.Event()
    release = threading.Event()

    async def delayed_enrolment(*args, **kwargs):
        started.set()
        if not await __import__("asyncio").to_thread(release.wait, 10):
            raise RuntimeError("Timed out waiting to release enrolment")
        return "stale-trusted-device"

    url = f"/api/v1/integrations/{integration_id}"

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        side_effect=delayed_enrolment,
    ):
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                client.post,
                f"{url}/mfa/enrol",
                json={"otp": "123456"},
                headers=CSRF,
            )

            try:
                assert started.wait(10), "Enrolment did not reach Synology"

                removed = client.post(
                    f"{url}/mfa/unenrol",
                    json={},
                    headers=CSRF,
                )

                assert removed.status_code == 200, removed.text
            finally:
                release.set()

            result = pending.result(timeout=15)

    assert result.status_code == 409, result.text
    assert result.json()["detail"]["code"] == "synology_mfa_conflict"

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert integration is not None
        assert "device_id" not in integration.config
        assert integration.config["_synology_mfa_revision"] == 1


def test_create_rejects_manual_mfa_revision(client):
    """Clients must not initialise the internal MFA revision."""
    setup_admin(client)

    result = client.post(
        "/api/v1/integrations",
        json={
            "kind": "synology",
            "name": "Protected Synology",
            "config": {
                "url": "https://nas.example:5001",
                "username": "testuser",
                "password": "testpassword",
                "_synology_mfa_revision": 999,
            },
        },
        headers=CSRF,
    )

    assert result.status_code == 400, result.text
    assert result.json()["detail"]["code"] == "protected_field"


def test_update_rejects_manual_mfa_revision(client):
    """Clients must not modify the internal MFA revision."""
    setup_admin(client)
    integration_id = make_integration(client)

    result = client.patch(
        f"/api/v1/integrations/{integration_id}",
        json={
            "config": {
                "_synology_mfa_revision": 999,
            },
        },
        headers=CSRF,
    )

    assert result.status_code == 400, result.text
    assert result.json()["detail"]["code"] == "protected_field"


def test_mfa_revision_is_internal_only(client):
    """The MFA revision stays in storage, never in public or exported config."""
    from app.db import db_session
    from app.models import Integration
    from app.services.integrations import export_config, public_config

    setup_admin(client)
    integration_id = make_integration(client)

    url = f"/api/v1/integrations/{integration_id}"

    removed = client.post(
        f"{url}/mfa/unenrol",
        json={},
        headers=CSRF,
    )
    assert removed.status_code == 200, removed.text

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert integration is not None

        assert integration.config["_synology_mfa_revision"] == 1

        public = public_config(integration)
        exported = export_config(integration)

        assert "_synology_mfa_revision" not in public
        assert "_synology_mfa_revision" not in exported

    response = client.get("/api/v1/integrations")
    assert response.status_code == 200, response.text

    saved = next(
        item for item in response.json()
        if item["id"] == integration_id
    )

    assert "_synology_mfa_revision" not in saved["config"]


def test_pending_enrolment_rejected_after_identity_change_and_revert(client):
    """Changing NAS identity and reverting must invalidate pending MFA."""
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.db import db_session
    from app.models import Integration

    setup_admin(client)
    integration_id = make_integration(client)

    started = threading.Event()
    release = threading.Event()

    async def delayed_enrolment(*args, **kwargs):
        started.set()
        if not await asyncio.to_thread(release.wait, 10):
            raise RuntimeError("Timed out waiting for enrolment release")
        return "stale-trusted-device"

    url = f"/api/v1/integrations/{integration_id}"

    with patch(
        "app.adapters.synology.SynologyAdapter.enrol_mfa",
        side_effect=delayed_enrolment,
    ):
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                client.post,
                f"{url}/mfa/enrol",
                json={"otp": "123456"},
                headers=CSRF,
            )

            try:
                assert started.wait(10), "Enrolment did not reach Synology"

                changed = client.patch(
                    url,
                    json={"config": {"username": "temporary-user"}},
                    headers=CSRF,
                )
                assert changed.status_code == 200, changed.text

                reverted = client.patch(
                    url,
                    json={"config": {"username": "testuser"}},
                    headers=CSRF,
                )
                assert reverted.status_code == 200, reverted.text
            finally:
                release.set()

            result = pending.result(timeout=15)

    assert result.status_code == 409, result.text
    assert result.json()["detail"]["code"] == "synology_mfa_conflict"

    with db_session() as db:
        integration = db.get(Integration, integration_id)
        assert integration is not None
        assert "device_id" not in integration.config
        assert integration.config["_synology_mfa_revision"] == 2
