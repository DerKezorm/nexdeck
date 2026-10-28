"""Every adapter is imported while the server starts, not by the first request that needs one."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_the_registry_is_full_before_the_first_request(data_dir: Path) -> None:
    from app.adapters import REGISTRY
    from app.main import app

    # ⚠️ Emptied first: other tests in the same run have long filled it, and
    # a full registry here would prove nothing about the start.
    REGISTRY.clear()
    with TestClient(app):
        assert len(REGISTRY) > 200, "the first start would pay for importing every adapter in its first request"
