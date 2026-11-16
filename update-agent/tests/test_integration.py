"""End-to-end tests of NexDeck communicating with its update agent."""

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = ROOT / "update-agent"
BACKEND_DIR = ROOT / "backend"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from app.services.update_agent import read_agent_status


spec = importlib.util.spec_from_file_location(
    "nexdeck_integration_agent",
    AGENT_DIR / "server.py",
)
agent_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = agent_module
spec.loader.exec_module(agent_module)


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


agent_module.load_trusted_manifest = _fixture_manifest_loader


TOKEN = "integration-test-token-" + "a" * 48
DEPLOYMENT = "nexdeck-integration"


@pytest.fixture
def running_agent(tmp_path):
    manifest_path = tmp_path / "deployment.json"

    manifest_path.write_text(
        json.dumps(
            {
                "deployment_id": DEPLOYMENT,
                "compose_file": "/opt/nexdeck/docker-compose.yml",
                "project_directory": "/opt/nexdeck",
                "project_name": "nexdeck",
                "service_name": "nexdeck",
                "container_name": "nexdeck",
                "data_directory": "/opt/nexdeck/data",
            }
        ),
        encoding="utf-8",
    )

    # Trusted manifests must not be group/world writable.
    manifest_path.chmod(0o600)

    socket_path = tmp_path / "agent.sock"

    server = agent_module.UnixAgentServer(
        socket_path,
        manifest_path,
        TOKEN,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        yield socket_path, manifest_path
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_real_agent_connection(running_agent):
    socket_path, _ = running_agent

    result = read_agent_status(
        socket_path,
        TOKEN,
        DEPLOYMENT,
    )

    assert result == {
        "available": True,
        "deployment": DEPLOYMENT,
        "can_update": True,
        "reason": "ready",
        "stage": "idle",
        "error": None,
    }


def test_real_agent_rejects_wrong_token(running_agent):
    socket_path, _ = running_agent

    result = read_agent_status(
        socket_path,
        "incorrect-token",
        DEPLOYMENT,
    )

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "agent_auth_failed"


def test_real_agent_rejects_wrong_deployment(running_agent):
    socket_path, _ = running_agent

    result = read_agent_status(
        socket_path,
        TOKEN,
        "different-deployment",
    )

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "deployment_mismatch"


def test_real_agent_invalid_manifest_fails_closed(running_agent):
    socket_path, manifest_path = running_agent

    manifest_path.write_text(
        '{"deployment_id": "incomplete"}',
        encoding="utf-8",
    )

    result = read_agent_status(
        socket_path,
        TOKEN,
        DEPLOYMENT,
    )

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "agent_unreachable"


def test_real_agent_offline_fails_closed(tmp_path):
    socket_path = tmp_path / "nonexistent.sock"

    result = read_agent_status(
        socket_path,
        TOKEN,
        DEPLOYMENT,
    )

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "agent_unreachable"
