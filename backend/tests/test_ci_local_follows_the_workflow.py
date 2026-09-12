"""The whole CI set runs on this machine, read from the workflow and not from a copy of it.

⚠️ Coverage, the OSV check and the version check ran in GitHub's CI and nowhere
else. Locally the steps were run by hand, one at a time, and a forgotten one
turned up red after the tag was already out. A script with its own list of
steps would fall behind the first time the workflow gains one, so it reads
ci.yml. Still open in the check of 12.09.2026.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
INSTALLS = ("pip install", "npm ci", "npx playwright install")


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_local", BACKEND / "tools" / "ci_local.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass looks its module up in sys.modules while it is being built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workflow() -> dict[str, Any]:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _planned(**choices: Any) -> dict[str, Any]:
    return {step.name: step for step in _script().plan(_workflow(), **choices)}


def test_every_check_of_the_workflow_is_planned() -> None:
    lines = {line.strip() for step in _planned(tag=None, install=False).values() for line in step.script.splitlines()}
    for check in ("python -m ruff check app tests", "python -m coverage run -m pytest -q", "python -m coverage report",
                  "python tools/audit_deps.py", "npm run build", "npm run lint", "npm run weight",
                  "npm run coverage", "npm run e2e"):
        assert check in lines, f"{check!r} is in the workflow and would not run here"


def test_nothing_but_installs_is_left_out() -> None:
    planned = _planned(tag="v0.0.0", install=False)
    run_steps = [step for step in _workflow()["jobs"]["tests"]["steps"] if "run" in step]
    assert len(run_steps) >= 8, "the workflow lost its steps, so this test looks at nothing"
    for step in run_steps:
        lines = [line.strip() for line in step["run"].splitlines() if line.strip()]
        if all(line.startswith(INSTALLS) for line in lines):
            assert step["name"] not in planned, step["name"]
        else:
            assert step["name"] in planned, step["name"]


def test_installs_run_only_when_asked() -> None:
    assert _planned(tag=None, install=False)["Build frontend"].script.split() == ["npm", "run", "build"]
    with_installs = _planned(tag=None, install=True)
    assert "npm ci" in with_installs["Build frontend"].script
    assert "Install backend dependencies" in with_installs


def test_the_version_check_runs_for_a_tag_and_is_told_its_name() -> None:
    assert "Version matches tag" not in _planned(tag=None, install=False)
    step = _planned(tag="v1.2.3", install=False)["Version matches tag"]
    assert step.env["GITHUB_REF_NAME"] == "v1.2.3"
    assert step.directory == BACKEND


def test_a_step_keeps_its_environment_and_its_folder() -> None:
    e2e = _planned(tag=None, install=False)["End-to-end test"]
    assert e2e.env.get("NEXDECK_E2E_PYTHON")
    assert e2e.directory == ROOT / "frontend"


def test_a_condition_it_does_not_understand_stops_it() -> None:
    """Skipping it would be a check that silently never runs here."""
    workflow = {"jobs": {"tests": {"steps": [
        {"name": "Only sometimes", "if": "github.event_name == 'schedule'", "run": "echo hi"}]}}}
    with pytest.raises(ValueError, match="Only sometimes"):
        _script().plan(workflow, tag=None, install=False)


def test_the_first_red_step_ends_the_run() -> None:
    module = _script()
    steps = [module.Step(name, ROOT, "true", {}) for name in ("one", "two", "three")]
    ran: list[str] = []

    def runner(step: Any) -> int:
        ran.append(step.name)
        return 3 if step.name == "two" else 0

    assert module.run(steps, runner) == 3
    assert ran == ["one", "two"]
