"""The self-update interface starts disabled and is administrator-only."""

from fastapi.testclient import TestClient

from .conftest import create_user, login, setup_admin


def test_update_status_is_disabled_by_default(client: TestClient) -> None:
    setup_admin(client)

    response = client.get("/api/v1/self-update/status")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "available": False,
        "deployment": "unknown",
        "can_update": False,
        "reason": "agent_not_configured",
    }


def test_only_administrators_can_read_update_status(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")

    member = TestClient(client.app)
    login(member, "kim", "another-long-password")

    response = member.get("/api/v1/self-update/status")

    assert response.status_code == 403


def test_unauthenticated_users_cannot_read_update_status(client: TestClient) -> None:
    setup_admin(client)

    visitor = TestClient(client.app)
    response = visitor.get("/api/v1/self-update/status")

    assert response.status_code == 401


def test_configured_socket_does_not_enable_updates(
    client: TestClient,
    monkeypatch,
) -> None:
    """Configuration alone must never grant update capability."""
    from app import config

    monkeypatch.setenv(
        "NEXDECK_UPDATE_AGENT_SOCKET",
        "/tmp/nexdeck-test-agent-not-running.sock",
    )
    config.reset_settings_cache()

    try:
        setup_admin(client)

        response = client.get("/api/v1/self-update/status")

        assert response.status_code == 200
        assert response.json() == {
            "configured": False,
            "available": False,
            "deployment": "unknown",
            "can_update": False,
            "reason": "agent_configuration_incomplete",
        }
    finally:
        config.reset_settings_cache()


def test_socket_and_token_still_cannot_enable_updates(
    client: TestClient,
    monkeypatch,
) -> None:
    """Both settings alone must not imply a trusted agent."""
    from app import config

    monkeypatch.setenv(
        "NEXDECK_UPDATE_AGENT_SOCKET",
        "/tmp/nexdeck-test-agent-not-running.sock",
    )
    monkeypatch.setenv(
        "NEXDECK_UPDATE_AGENT_TOKEN",
        "test-only-agent-credential",
    )
    monkeypatch.setenv(
        "NEXDECK_UPDATE_DEPLOYMENT_ID",
        "nexdeck-test-deployment",
    )
    config.reset_settings_cache()

    try:
        setup_admin(client)
        response = client.get("/api/v1/self-update/status")

        assert response.status_code == 200
        assert response.json() == {
            "configured": True,
            "available": False,
            "deployment": "unknown",
            "can_update": False,
            "reason": "agent_unreachable",
        }
    finally:
        config.reset_settings_cache()
