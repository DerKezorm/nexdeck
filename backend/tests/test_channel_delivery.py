"""Do the notification channels really send, and what exactly?

Local catchers stand in for the services: a small SMTP server and a small HTTP
server, both on a port the operating system picks. A test that only checks
``ok: true`` would pass on a channel that posts an empty body to the wrong
address, so every case looks at what arrived.

Telegram is missing on purpose: its address is api.telegram.org and cannot be
pointed elsewhere, and a test suite has no business calling the internet. Web
Push needs a browser subscription and a real push service.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF, setup_admin


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class SmtpCatcher:
    """Enough SMTP to take one message: greet, envelope, body, hang up."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.mails: list[dict] = []
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", self.port))
        self._socket.listen(5)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(client,), daemon=True).start()

    def _session(self, client: socket.socket) -> None:
        mail: dict = {"from": "", "to": [], "body": ""}
        stream = client.makefile("rwb")
        stream.write(b"220 catcher\r\n")
        stream.flush()
        while True:
            line = stream.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            upper = text.upper()
            if upper.startswith(("EHLO", "HELO")):
                stream.write(b"250-catcher\r\n250 OK\r\n")
            elif upper.startswith("MAIL FROM"):
                mail["from"] = text.split(":", 1)[1].strip()
                stream.write(b"250 OK\r\n")
            elif upper.startswith("RCPT TO"):
                mail["to"].append(text.split(":", 1)[1].strip())
                stream.write(b"250 OK\r\n")
            elif upper.startswith("DATA"):
                stream.write(b"354 go ahead\r\n")
                stream.flush()
                parts: list[str] = []
                while True:
                    part = stream.readline()
                    if not part or part.strip() == b".":
                        break
                    parts.append(part.decode("utf-8", "replace"))
                mail["body"] = "".join(parts)
                self.mails.append(mail)
                stream.write(b"250 queued\r\n")
            elif upper.startswith("QUIT"):
                stream.write(b"221 bye\r\n")
                stream.flush()
                break
            else:
                stream.write(b"250 OK\r\n")
            stream.flush()
        client.close()

    def close(self) -> None:
        self._socket.close()


class HttpCatcher:
    """Records method, path, headers and body, and answers 200 with JSON."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        recorded = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                recorded.append({
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": self.rfile.read(length).decode("utf-8", "replace"),
                })
                payload = json.dumps({"id": 1}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", _free_port()), Handler)
        self.port = self._server.server_port
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()


@pytest.fixture
def smtp() -> Iterator[SmtpCatcher]:
    catcher = SmtpCatcher()
    yield catcher
    catcher.close()


@pytest.fixture
def http() -> Iterator[HttpCatcher]:
    catcher = HttpCatcher()
    yield catcher
    catcher.close()


def send_through(client: TestClient, kind: str, config: dict) -> dict:
    created = client.post("/api/v1/channels", json={"kind": kind, "name": f"probe {kind}", "config": config}, headers=CSRF)
    assert created.status_code == 201, created.text
    answer = client.post(f"/api/v1/channels/{created.json()['id']}/test", headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_mail_channel_delivers_a_message(client: TestClient, smtp: SmtpCatcher) -> None:
    """Through the installation's own mail server, not one per channel.

    ⚠️ This test used to give the channel a host, a port and a sender of its
    own. It stopped being possible on 06.09.2026: the same mail account typed
    out again per channel, password included, is a place nobody remembers to
    update. The server is set up once, here as anywhere.
    """
    setup_admin(client)
    stored = client.put("/api/v1/settings/mail", json={
        "host": "127.0.0.1", "port": smtp.port, "security": "none",
        "from_address": "deck@example.com", "from_name": "nexdeck",
    }, headers=CSRF)
    assert stored.status_code == 200, stored.text
    result = send_through(client, "email", {"to_address": "you@example.com"})
    assert result["ok"] is True, result
    assert len(smtp.mails) == 1
    mail = smtp.mails[0]
    assert mail["from"] == "<deck@example.com>"
    assert mail["to"] == ["<you@example.com>"]
    assert "Subject: [nexdeck] nexdeck test message" in mail["body"]
    assert "the channel works" in mail["body"]


def test_ntfy_posts_to_the_topic_with_its_headers(client: TestClient, http: HttpCatcher) -> None:
    setup_admin(client)
    result = send_through(client, "ntfy", {"url": f"http://127.0.0.1:{http.port}", "topic": "probe", "token": "tk_probe"})
    assert result["ok"] is True, result
    assert len(http.requests) == 1
    request = http.requests[0]
    assert request["path"] == "/probe"
    assert "the channel works" in request["body"]
    assert request["headers"]["title"] == "nexdeck test message"
    # Without the header a protected topic answers 403, and the message is gone.
    assert request["headers"]["authorization"] == "Bearer tk_probe"


def test_gotify_posts_a_message_with_its_token(client: TestClient, http: HttpCatcher) -> None:
    setup_admin(client)
    result = send_through(client, "gotify", {"url": f"http://127.0.0.1:{http.port}", "token": "probe-token"})
    assert result["ok"] is True, result
    request = http.requests[0]
    assert request["path"].startswith("/message")
    assert "token=probe-token" in request["path"]
    body = json.loads(request["body"])
    assert body["title"] == "nexdeck test message"
    assert "the channel works" in body["message"]


def test_discord_posts_an_embed(client: TestClient, http: HttpCatcher) -> None:
    setup_admin(client)
    result = send_through(client, "discord", {"webhook": f"http://127.0.0.1:{http.port}/webhook"})
    assert result["ok"] is True, result
    body = json.loads(http.requests[0]["body"])
    assert body["username"] == "nexdeck"
    assert body["embeds"][0]["title"] == "nexdeck test message"


def test_slack_posts_plain_text(client: TestClient, http: HttpCatcher) -> None:
    setup_admin(client)
    result = send_through(client, "slack", {"webhook": f"http://127.0.0.1:{http.port}/webhook"})
    assert result["ok"] is True, result
    body = json.loads(http.requests[0]["body"])
    assert "nexdeck test message" in body["text"]


def test_apprise_hands_the_message_to_the_library(client: TestClient, http: HttpCatcher) -> None:
    """``json://`` is Apprise's own way of posting; if it arrives, the library
    took the URL, built a message and sent it."""
    setup_admin(client)
    result = send_through(client, "apprise", {"urls": f"json://127.0.0.1:{http.port}/apprise"})
    assert result["ok"] is True, result
    body = json.loads(http.requests[0]["body"])
    assert body["title"] == "nexdeck test message"


def test_a_service_that_refuses_is_reported_and_remembered(client: TestClient) -> None:
    """A closed port is the everyday case: the answer says so, and the channel
    carries the reason until the next attempt."""
    setup_admin(client)
    result = send_through(client, "ntfy", {"url": f"http://127.0.0.1:{_free_port()}", "topic": "nobody"})
    assert result["ok"] is False
    assert result["message"]
    listed = client.get("/api/v1/channels").json()[0]
    assert listed["last_error"], "the tile must be able to show why"
