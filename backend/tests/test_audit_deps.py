"""The dependency audit lets an accepted advisory through, and only that one, only until its day."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_deps", BACKEND / "tools" / "audit_deps.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass looks its module up in sys.modules while it is being built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _script()
    monkeypatch.setattr(module, "python_packages", lambda: [("httpx", "0.28.1")])
    monkeypatch.setattr(module, "npm_packages", lambda: [("deepmerge", "4.3.1"), ("left-pad", "1.0.0")])
    monkeypatch.setattr(module, "describe", lambda identifier: "")
    return module


def _answers(module: ModuleType, monkeypatch: pytest.MonkeyPatch, hits: dict[str, dict[str, list[str]]]) -> None:
    monkeypatch.setattr(module, "query", lambda packages, ecosystem: hits.get(ecosystem, {}))


def test_every_accepted_advisory_names_its_package_a_reason_and_an_end() -> None:
    module = _script()
    for identifier, entry in module.ACCEPTED.items():
        assert identifier.startswith(("GHSA-", "PYSEC-", "CVE-")), identifier
        assert entry.ecosystem in ("npm", "PyPI") and entry.package and len(entry.reason) > 20
        # An acceptance without an end is a switch somebody forgets: at most half a year.
        assert (entry.until - date(2026, 10, 28)).days <= 183, f"{identifier} is accepted for too long"


def test_the_accepted_advisory_lets_the_run_stay_green(audit: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _answers(audit, monkeypatch, {"npm": {"deepmerge 4.3.1": ["GHSA-gcqx-w48m-w2h4"]}})
    assert audit.main(date(2026, 11, 1)) == 0
    assert "accepted until 2026-12-31" in capsys.readouterr().out


def test_after_its_day_the_same_advisory_is_red_again(audit: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(audit, monkeypatch, {"npm": {"deepmerge 4.3.1": ["GHSA-gcqx-w48m-w2h4"]}})
    assert audit.main(date(2027, 1, 1)) == 1


def test_the_same_id_on_another_package_still_counts(audit: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(audit, monkeypatch, {"npm": {"left-pad 1.0.0": ["GHSA-gcqx-w48m-w2h4"]}})
    assert audit.main(date(2026, 11, 1)) == 1


def test_any_other_advisory_beside_it_is_red(audit: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(audit, monkeypatch, {"npm": {"deepmerge 4.3.1": ["GHSA-gcqx-w48m-w2h4", "GHSA-xxxx-yyyy-zzzz"]}})
    assert audit.main(date(2026, 11, 1)) == 1
