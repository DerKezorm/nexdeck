"""Tests for the standalone deployment manifest validator."""

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "manifest.py"

spec = importlib.util.spec_from_file_location(
    "nexdeck_agent_manifest", MODULE_PATH
)
manifest = importlib.util.module_from_spec(spec)

import sys
sys.modules[spec.name] = manifest
spec.loader.exec_module(manifest)


VALID = {
    "deployment_id": "nexdeck-production",
    "compose_file": "/opt/nexdeck/docker-compose.yml",
    "project_directory": "/opt/nexdeck",
    "project_name": "nexdeck",
    "service_name": "nexdeck",
    "container_name": "nexdeck",
    "data_directory": "/opt/nexdeck/data",
}


def write_manifest(tmp_path, document):
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_valid_manifest(tmp_path):
    deployment = manifest.load_manifest(
        write_manifest(tmp_path, VALID)
    )
    assert deployment.deployment_id == "nexdeck-production"
    assert deployment.service_name == "nexdeck"


def test_missing_required_field(tmp_path):
    document = {**VALID}
    del document["deployment_id"]

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, document))


def test_unsafe_identifier(tmp_path):
    document = {**VALID, "service_name": "../another-service"}

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, document))


def test_relative_path(tmp_path):
    document = {**VALID, "data_directory": "./data"}

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, document))


def test_invalid_json(tmp_path):
    path = tmp_path / "deployment.json"
    path.write_text("{broken-json", encoding="utf-8")

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(path)


def test_manifest_must_be_object(tmp_path):
    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, []))


def test_parent_traversal_rejected(tmp_path):
    document = {
        **VALID,
        "data_directory": "/opt/nexdeck/../other-app/data",
    }

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, document))


def test_symlinked_data_directory_rejected(tmp_path):
    actual = tmp_path / "actual-data"
    actual.mkdir()

    link = tmp_path / "linked-data"
    link.symlink_to(actual, target_is_directory=True)

    document = {
        **VALID,
        "data_directory": str(link),
    }

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, document))


def test_intermediate_symlink_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()

    link = tmp_path / "linked"
    link.symlink_to(actual, target_is_directory=True)

    document = {
        **VALID,
        "compose_file": str(link / "docker-compose.yml"),
    }

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(write_manifest(tmp_path, document))


def test_nonexistent_canonical_path_allowed(tmp_path):
    document = {
        **VALID,
        "data_directory": str(tmp_path / "future-data"),
    }

    deployment = manifest.load_manifest(
        write_manifest(tmp_path, document)
    )

    assert deployment.data_directory == tmp_path / "future-data"


def test_missing_container_name_rejected(tmp_path):
    document = {**VALID}
    del document["container_name"]

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(
            write_manifest(tmp_path, document)
        )


@pytest.mark.parametrize(
    "name",
    [
        "../another-container",
        "container/name",
        "container name",
        "",
        "-container",
    ],
)
def test_unsafe_enrolled_container_name_rejected(tmp_path, name):
    document = {
        **VALID,
        "container_name": name,
    }

    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(
            write_manifest(tmp_path, document)
        )


def test_distinct_container_name_accepted(tmp_path):
    document = {
        **VALID,
        "service_name": "nexdeck",
        "container_name": "nexdeck-production",
    }

    deployment = manifest.load_manifest(
        write_manifest(tmp_path, document)
    )

    assert deployment.service_name == "nexdeck"
    assert deployment.container_name == "nexdeck-production"
