"""Every pinned dependency against OSV, Python and npm in one run.

No account and no key: OSV answers a batch query with the advisories that
touch exactly the versions installed here. Run it before a release, and after
any upgrade.

    backend/.venv/Scripts/python.exe backend/tools/audit_deps.py

Exits non-zero when anything is found, so it can stand in a pipeline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BATCH = "https://api.osv.dev/v1/querybatch"
DETAIL = "https://api.osv.dev/v1/vulns/"
CHUNK = 200


def python_packages() -> list[tuple[str, str]]:
    answer = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return [(entry["name"], entry["version"]) for entry in json.loads(answer.stdout)]


def npm_packages() -> list[tuple[str, str]]:
    lock = ROOT / "frontend" / "package-lock.json"
    if not lock.exists():
        return []
    found: dict[str, str] = {}
    for path, entry in (json.loads(lock.read_text(encoding="utf-8")).get("packages") or {}).items():
        if path.startswith("node_modules/") and entry.get("version"):
            found[path.split("node_modules/")[-1]] = entry["version"]
    return sorted(found.items())


def query(packages: list[tuple[str, str]], ecosystem: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    with httpx.Client(timeout=60) as client:
        for start in range(0, len(packages), CHUNK):
            batch = packages[start : start + CHUNK]
            answer = client.post(BATCH, json={
                "queries": [{"package": {"name": name, "ecosystem": ecosystem}, "version": version} for name, version in batch],
            })
            answer.raise_for_status()
            for (name, version), result in zip(batch, answer.json().get("results") or [], strict=False):
                ids = [entry["id"] for entry in (result.get("vulns") or [])]
                if ids:
                    hits[f"{name} {version}"] = ids
    return hits


def describe(identifier: str) -> str:
    with httpx.Client(timeout=30) as client:
        answer = client.get(DETAIL + identifier)
        if answer.status_code >= 400:
            return ""
        body = answer.json()
        fixed = sorted({
            event["fixed"]
            for affected in body.get("affected") or []
            for entry in affected.get("ranges") or []
            for event in entry.get("events") or []
            if "fixed" in event
        })
        return f"{(body.get('summary') or '').strip()[:110]}" + (f"  fixed in {', '.join(fixed)}" if fixed else "")


def main() -> int:
    total = 0
    for ecosystem, packages in (("PyPI", python_packages()), ("npm", npm_packages())):
        hits = query(packages, ecosystem)
        print(f"\n{ecosystem}: {len(packages)} packages, {len(hits)} with an advisory")
        for where, ids in sorted(hits.items()):
            total += len(ids)
            print(f"  {where}")
            for identifier in ids:
                print(f"      {identifier}  {describe(identifier)}")
    print(f"\n{total} advisories.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
