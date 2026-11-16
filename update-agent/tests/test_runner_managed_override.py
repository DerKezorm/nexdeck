from pathlib import Path
from types import SimpleNamespace

from compose_runner import ComposeRunner


def test_managed_override_path():
    deployment = SimpleNamespace(
        project_directory=Path("/srv/nexdeck"),
    )

    runner = ComposeRunner(deployment)

    assert runner._managed_image_override() == Path(
        "/srv/nexdeck/.nexdeck-updater/image.override.yaml"
    )
