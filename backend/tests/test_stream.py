"""The live stream against a real server process.

Server-Sent Events are the piece the interface depends on most, and the test
client cannot close a streaming response cleanly, so this test starts uvicorn
on a free port, sets up a demo installation over HTTP and reads the stream
with a read timeout that ends the wait.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[str]:
    port = _free_port()
    env = {**os.environ, "NEXDECK_DATA_DIR": str(tmp_path / "data"), "NEXDECK_SECRET_KEY": "stream-test-secret", "NEXDECK_LOG_LEVEL": "WARNING"}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
                raise RuntimeError(f"the server did not come up:\n{stderr[-2000:]}")
            time.sleep(0.2)
        yield base
    finally:
        process.kill()
        process.wait(timeout=10)


def _events(client: httpx.Client, path: str, headers: dict | None = None, wanted: str = "event: widget", seconds: float = 15) -> list[str]:
    seen: list[str] = []
    deadline = time.monotonic() + seconds
    try:
        with client.stream("GET", path, headers=headers or {}, timeout=httpx.Timeout(5, read=seconds)) as response:
            assert response.status_code == 200, response.read()[:300]
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("event:"):
                    seen.append(line)
                if wanted in seen or time.monotonic() > deadline:
                    break
    except httpx.ReadTimeout:
        pass
    return seen


def test_stream_delivers_widget_events(live_server: str) -> None:
    with httpx.Client(base_url=live_server) as client:
        setup = client.post("/api/v1/setup", json={"username": "admin", "password": "correct-horse-battery", "demo": True})
        assert setup.status_code == 201, setup.text
        board = client.get("/api/v1/boards").json()[0]
        seen = _events(client, f"/api/v1/stream?board={board['slug']}")
        assert seen and seen[0] == "event: hello"
        assert "event: widget" in seen, f"no widget event within the wait: {seen}"

        # A kiosk display without a session gets the same stream; a stranger does not.
        token = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "wall"}, headers={"X-Nexdeck-Request": "1"}).json()["token"]
        with httpx.Client(base_url=live_server) as display:
            assert display.get(f"/api/v1/stream?board={board['slug']}").status_code == 401
            assert "event: widget" in _events(display, f"/api/v1/stream?board={board['slug']}", headers={"X-Kiosk-Token": token})

        # A second subscriber next to the first: the hub keeps both.
        with httpx.Client(base_url=live_server) as other:
            other.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse-battery"})
            assert "event: widget" in _events(other, f"/api/v1/stream?board={board['slug']}", seconds=10)
