"""The CI set of .github/workflows/ci.yml on this machine, before a tag goes out.

It reads the workflow instead of keeping its own list, so a step added there
runs here as well. The ``tests`` job only; ``uses:`` steps are GitHub's own
setup and are left out. Installs (``pip install``, ``npm ci``, ``npx
playwright install``) run only with ``--install``: ``npm ci`` throws
node_modules away underneath a dev server that may be running.

    python tools/ci_local.py                  # in backend/
    python tools/ci_local.py --tag v0.13.0    # adds the version check
    python tools/ci_local.py --install        # adds the installs

Stops at the first red step and exits with its code.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
INSTALLS = ("pip install", "npm ci", "npx playwright install")
ON_A_TAG = "startsWith(github.ref, 'refs/tags/v')"


@dataclass
class Step:
    name: str
    directory: Path
    script: str
    env: dict[str, str]


def plan(workflow: dict[str, Any], *, tag: str | None, install: bool) -> list[Step]:
    """The steps of the ``tests`` job that run here, in their order."""
    steps: list[Step] = []
    for raw in workflow["jobs"]["tests"]["steps"]:
        if "run" not in raw:
            continue
        name = str(raw.get("name") or str(raw["run"]).splitlines()[0])
        condition = raw.get("if")
        if condition is not None and str(condition).strip() != ON_A_TAG:
            # ⚠️ Refused, not skipped. A condition this script cannot work out
            # would otherwise be a check that quietly never runs here.
            raise ValueError(f"{name}: this script does not know the condition {condition!r}.")
        if condition is not None and not (tag or "").startswith("v"):
            continue
        lines = [line for line in str(raw["run"]).splitlines()
                 if install or not line.strip().startswith(INSTALLS)]
        script = "\n".join(lines).strip()
        if not script:
            continue
        env = {str(key): str(value) for key, value in (raw.get("env") or {}).items()}
        if tag:
            env.update(GITHUB_REF=f"refs/tags/{tag}", GITHUB_REF_NAME=tag)
        steps.append(Step(name, ROOT / str(raw.get("working-directory") or "."), script, env))
    return steps


def bash() -> str:
    """Git's bash on Windows, the system's anywhere else.

    ⚠️ On Windows not simply the first ``bash`` on the PATH: that is often
    WSL's, which runs the step in another system with another Python and
    another node_modules.
    """
    if os.name != "nt":
        found = shutil.which("bash")
        if found:
            return found
        raise SystemExit("No bash found. The workflow's steps are bash scripts.")
    git = shutil.which("git")
    if git:
        # cmd\git.exe on most installs, clangarm64\bin\git.exe on ARM: bash sits one or two folders up.
        for root in Path(git).resolve().parents[:3]:
            for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if candidate.is_file():
                    return str(candidate)
    raise SystemExit("No Git bash found. The workflow's steps are bash scripts; install Git for Windows.")


def run_in_bash(step: Step) -> int:
    env = {**os.environ, **step.env}
    # ``python`` in a step is the Python running this script, the way
    # setup-python makes it in CI. ⚠️ On Windows the first python on the PATH
    # is often the Store's placeholder, which runs nothing.
    env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), env.get("PATH", "")))
    command = [bash(), "--noprofile", "--norc", "-eo", "pipefail", "-c", step.script]
    return subprocess.run(command, cwd=step.directory, env=env, check=False).returncode


def run(steps: list[Step], runner: Callable[[Step], int]) -> int:
    for step in steps:
        print(f"\n== {step.name}", flush=True)
        started = time.monotonic()
        code = runner(step)
        took = time.monotonic() - started
        if code != 0:
            print(f"== {step.name}: red, exit {code}, after {took:.0f} s. Nothing after it ran.", flush=True)
            return code
        print(f"== {step.name}: green in {took:.0f} s", flush=True)
    print(f"\nAll {len(steps)} steps green.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CI set of ci.yml on this machine.")
    parser.add_argument("--tag", help="the tag about to go out, such as v0.13.0; adds the version check")
    parser.add_argument("--install", action="store_true", help="also run pip install, npm ci and the browser install")
    args = parser.parse_args(argv)
    if args.tag and not args.tag.startswith("v"):
        parser.error("a tag starts with v, the way the workflow expects it")
    steps = plan(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")), tag=args.tag, install=args.install)
    if not steps:
        print("The workflow has no step this script can run, and that is not green.", file=sys.stderr)
        return 1
    return run(steps, run_in_bash)


if __name__ == "__main__":
    raise SystemExit(main())
