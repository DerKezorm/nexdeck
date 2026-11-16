"""Integration tests for trusted manifest reading and validation."""

import json
import os

import pytest

from manifest import ManifestError, load_trusted_manifest


VALID = {
    "deployment_id": "nexdeck-test",
    "compose_file": "/opt/nexdeck/compose.yaml",
    "project_directory": "/opt/nexdeck",
    "project_name": "nexdeck",
    "service_name": "nexdeck",
    "container_name": "nexdeck",
    "data_directory": "/opt/nexdeck/data",
}


def create_manifest(tmp_path, document):
    directory = tmp_path / "enrollment"
    directory.mkdir(mode=0o700)

    path = directory / "deployment.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)

    return path


def test_valid_trusted_manifest(tmp_path):
    path = create_manifest(tmp_path, VALID)

    deployment = load_trusted_manifest(
        path,
        expected_uid=os.getuid(),
    )

    assert deployment.deployment_id == "nexdeck-test"
    assert deployment.container_name == "nexdeck"


def test_writable_trusted_manifest_rejected(tmp_path):
    path = create_manifest(tmp_path, VALID)
    path.chmod(0o666)

    with pytest.raises(ManifestError, match="securely read"):
        load_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_invalid_json_rejected(tmp_path):
    path = create_manifest(tmp_path, VALID)
    path.write_text("{invalid-json", encoding="utf-8")

    with pytest.raises(ManifestError):
        load_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_missing_field_rejected(tmp_path):
    document = dict(VALID)
    del document["deployment_id"]

    path = create_manifest(tmp_path, document)

    with pytest.raises(ManifestError, match="deployment_id"):
        load_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )
