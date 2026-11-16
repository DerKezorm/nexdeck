"""Tests for the shared recovery attachment path policy."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from recovery_paths import valid_attachment_path


@pytest.mark.parametrize(
    "value",
    [
        "avatars/example.png",
        "uploads/document.pdf",
        "brand/logo.svg",
        "avatars/a file with spaces.png",
        "uploads/report-2026_11.pdf",
    ],
)
def test_accepts_valid_attachment_paths(value):
    assert valid_attachment_path(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        123,
        "nexdeck.db",
        "secret.key",
        "../secret.key",
        "avatars/../secret.key",
        "avatars/nested/example.png",
        "avatars/",
        "avatars/.",
        "avatars/..",
        "avatars/example:alternate.png",
        "avatars\\example.png",
        "avatars/example\x00.png",
        "avatars/example\n.png",
        "/avatars/example.png",
        "other/example.png",
    ],
)
def test_rejects_unsafe_attachment_paths(value):
    assert not valid_attachment_path(value)
