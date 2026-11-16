from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from compose_runner import ComposeRunner
from latest_release import parse_latest_release


def test_production_target():
    runner = ComposeRunner(SimpleNamespace(
        deployment_id="nexdeck-production",
        project_directory=Path("/srv/nexdeck"),
    ))

    release = parse_latest_release({
        "tag_name": "v1.8.0",
        "draft": False,
        "prerelease": False,
    })

    with patch(
        "compose_runner.resolve_latest_release",
        return_value=release,
    ):
        target = runner._resolve_update_target()

    assert target.image_reference == (
        "ghcr.io/derkezorm/nexdeck:1.8.0"
    )


def test_isolated_target():
    runner = ComposeRunner(SimpleNamespace(
        deployment_id="nexdeck-updater-realtest",
        project_directory=Path("/srv/nexdeck-test"),
    ))

    release = parse_latest_release({
        "tag_name": "v1.8.0",
        "draft": False,
        "prerelease": False,
    })

    with patch(
        "compose_runner.resolve_latest_release",
        return_value=release,
    ):
        target = runner._resolve_update_target()

    assert target.image_reference == (
        "nexdeck-updater-realtest:1.8.0"
    )
