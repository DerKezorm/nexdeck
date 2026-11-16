"""Tests for the read-only update agent HTTP protocol."""

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import httpx
import pytest


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

spec = importlib.util.spec_from_file_location(
    "nexdeck_agent_server",
    AGENT_DIR / "server.py",
)
server_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server_module
spec.loader.exec_module(server_module)


# Test-only manifest loading. Production security is unchanged.
from manifest import ManifestError, parse_manifest_text


def _fixture_manifest_loader(path):
    path = Path(path)

    if not path.is_file() or path.is_symlink():
        raise ManifestError("Invalid test manifest")

    details = path.stat()

    if details.st_uid != os.getuid() or details.st_mode & 0o022:
        raise ManifestError("Insecure test manifest")

    try:
        return parse_manifest_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ManifestError("Invalid test manifest") from exc


server_module.load_trusted_manifest = _fixture_manifest_loader


TOKEN = "test-agent-token-" + "a" * 48

VALID = {
    "deployment_id": "nexdeck-test",
    "compose_file": "/opt/nexdeck/docker-compose.yml",
    "project_directory": "/opt/nexdeck",
    "project_name": "nexdeck",
    "service_name": "nexdeck",
    "container_name": "nexdeck",
    "data_directory": "/opt/nexdeck/data",
}


@pytest.fixture
def agent(tmp_path):
    manifest_path = tmp_path / "deployment.json"
    manifest_path.write_text(
        json.dumps(VALID),
        encoding="utf-8",
    )

    # Trusted manifests must not be group/world writable.
    manifest_path.chmod(0o600)

    socket_path = tmp_path / "agent.sock"

    instance = server_module.UnixAgentServer(
        socket_path,
        manifest_path,
        TOKEN,
    )

    thread = threading.Thread(
        target=instance.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        transport = httpx.HTTPTransport(
            uds=str(socket_path),
        )

        with httpx.Client(
            transport=transport,
            base_url="http://update-agent",
            timeout=2.0,
        ) as client:
            yield client, manifest_path
    finally:
        instance.shutdown()
        thread.join(timeout=3)
        instance.server_close()


def test_authenticated_status(agent):
    client, _ = agent

    response = client.get(
        "/v1/status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "deployment_id": "nexdeck-test",
        "available": True,
        "can_update": True,
        "stage": "idle",
        "error": None,
    }


def test_missing_token_rejected(agent):
    client, _ = agent

    response = client.get("/v1/status")

    assert response.status_code == 403


def test_incorrect_token_rejected(agent):
    client, _ = agent

    response = client.get(
        "/v1/status",
        headers={"Authorization": "Bearer incorrect"},
    )

    assert response.status_code == 403


def test_unknown_endpoint_rejected(agent):
    client, _ = agent

    response = client.get(
        "/v1/anything-else",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 404


def test_invalid_manifest_fails_closed(agent):
    client, manifest_path = agent

    manifest_path.write_text(
        '{"deployment_id": "incomplete"}',
        encoding="utf-8",
    )

    response = client.get(
        "/v1/status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503


def test_update_method_not_available(agent):
    client, _ = agent

    response = client.post(
        "/v1/status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 404


def test_missing_manifest_returns_503(agent):
    """A missing trusted manifest must fail closed."""
    client, manifest_path = agent
    manifest_path.unlink()

    response = client.get(
        "/v1/status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": "invalid_deployment_manifest",
    }


def test_insecure_manifest_permissions_return_503(agent):
    """Group/world writable enrollment must be rejected."""
    client, manifest_path = agent
    manifest_path.chmod(0o666)

    response = client.get(
        "/v1/status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": "invalid_deployment_manifest",
    }


def test_authentication_precedes_manifest_access(agent, monkeypatch):
    """Unauthenticated requests must never read enrollment."""
    client, _ = agent

    def forbidden_read(*args, **kwargs):
        raise AssertionError(
            "Manifest accessed before authentication"
        )

    monkeypatch.setattr(
        server_module,
        "load_trusted_manifest",
        forbidden_read,
    )

    response = client.get(
        "/v1/status",
        headers={"Authorization": "Bearer incorrect"},
    )

    assert response.status_code == 403


def test_trusted_loader_failure_has_no_fallback(agent, monkeypatch):
    """Trusted loader failure must produce HTTP 503."""
    from manifest import ManifestError

    client, _ = agent

    def reject_manifest(*args, **kwargs):
        raise ManifestError("Simulated security rejection")

    monkeypatch.setattr(
        server_module,
        "load_trusted_manifest",
        reject_manifest,
    )

    response = client.get(
        "/v1/status",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": "invalid_deployment_manifest",
    }
