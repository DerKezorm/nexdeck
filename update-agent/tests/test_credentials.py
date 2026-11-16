"""Security regression tests for update-agent credentials."""

import os

import pytest

from server import load_agent_token


TOKEN = "secure-test-token-" + "x" * 48


@pytest.fixture
def credential(tmp_path):
    path = tmp_path / "agent.token"
    path.write_text(TOKEN + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_protected_credential(credential):
    assert load_agent_token(credential) == TOKEN


def test_environment_credential(monkeypatch):
    monkeypatch.setenv("NEXDECK_UPDATE_AGENT_TOKEN", TOKEN)
    assert load_agent_token() == TOKEN


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o666])
def test_insecure_permissions_rejected(credential, mode):
    credential.chmod(mode)
    with pytest.raises(ValueError):
        load_agent_token(credential)


def test_symlink_rejected(credential, tmp_path):
    link = tmp_path / "linked.token"
    link.symlink_to(credential)
    with pytest.raises(ValueError):
        load_agent_token(link)


def test_missing_file_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXDECK_UPDATE_AGENT_TOKEN", TOKEN)
    with pytest.raises(ValueError):
        load_agent_token(tmp_path / "missing.token")


def test_oversized_credential_rejected(credential):
    credential.write_bytes(b"x" * 4097)
    with pytest.raises(ValueError):
        load_agent_token(credential)


def test_short_credential_rejected(credential):
    credential.write_text("short", encoding="utf-8")
    with pytest.raises(ValueError):
        load_agent_token(credential)


def test_whitespace_rejected(credential):
    credential.write_text(TOKEN + " invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        load_agent_token(credential)


def test_invalid_utf8_rejected(credential):
    credential.write_bytes(b"\xff" * 40)
    with pytest.raises(ValueError):
        load_agent_token(credential)


def test_file_takes_precedence_over_environment(
    credential, monkeypatch
):
    monkeypatch.setenv(
        "NEXDECK_UPDATE_AGENT_TOKEN",
        "different-token-" + "z" * 48,
    )
    assert load_agent_token(credential) == TOKEN


def test_group_owned_credential_rejected(credential):
    credential.chmod(0o640)
    with pytest.raises(ValueError):
        load_agent_token(credential)


def test_empty_environment_rejected(monkeypatch):
    monkeypatch.delenv("NEXDECK_UPDATE_AGENT_TOKEN", raising=False)
    with pytest.raises(ValueError):
        load_agent_token()
