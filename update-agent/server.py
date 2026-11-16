"""Read-only NexDeck update agent prototype.

No Docker operations, updates, backups or filesystem mutations
are exposed by this server.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import socketserver
import stat
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from manifest import ManifestError, load_trusted_manifest
from compose_runner import ComposeRunner, UpdateError


class AgentHandler(BaseHTTPRequestHandler):
    """Authenticated host updater endpoints."""

    server_version = "NexDeckUpdateAgent/0.1"

    def log_message(self, format_string, *args):
        """Avoid logging authentication headers or request bodies."""
        return

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/v1/status":
            self._reply(404, {"error": "not_found"})
            return

        expected = self.server.agent_token
        supplied = self.headers.get("Authorization", "")

        if not hmac.compare_digest(
            supplied.encode("utf-8"),
            f"Bearer {expected}".encode("utf-8"),
        ):
            self._reply(403, {"error": "forbidden"})
            return

        try:
            deployment = load_trusted_manifest(self.server.manifest_path)
        except ManifestError:
            self._reply(
                503,
                {
                    "error": "invalid_deployment_manifest",
                },
            )
            return

        self._reply(
            200,
            {
                "deployment_id": deployment.deployment_id,
                "available": True,
                "can_update": self.server.runner.can_update(),
                "stage": self.server.runner.state.stage,
                "error": self.server.runner.state.error,
            },
        )


    def do_POST(self) -> None:
        if self.path != "/v1/install":
            self._reply(404, {"error": "not_found"})
            return

        expected = f"Bearer {self.server.agent_token}"
        supplied = self.headers.get("Authorization", "")

        if not hmac.compare_digest(
            supplied.encode("utf-8"),
            expected.encode("utf-8"),
        ):
            self._reply(403, {"error": "forbidden"})
            return

        try:
            deployment = load_trusted_manifest(
                self.server.manifest_path
            )
        except ManifestError:
            self._reply(503, {"error": "invalid_deployment_manifest"})
            return

        if deployment.deployment_id != self.server.runner.deployment.deployment_id:
            self._reply(409, {"error": "deployment_changed"})
            return

        if self.server.runner.lock.locked():
            self._reply(409, {"error": "update_already_running"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length < 1 or length > 4096:
                raise ValueError("Invalid request length")

            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )

            if not isinstance(payload, dict):
                raise ValueError("Invalid request")

            if payload.get("deployment_id") != deployment.deployment_id:
                self._reply(409, {"error": "deployment_mismatch"})
                return

            backup_filename = payload.get("backup")
            self.server.runner.verify_backup(
                backup_filename
            )

        except (ValueError, UnicodeError, UpdateError):
            self._reply(400, {"error": "invalid_pre_update_backup"})
            return

        if not self.server.runner.reserve():
            self._reply(409, {"error": "update_already_running"})
            return

        def perform_update():
            try:
                self.server.runner.update(
                    backup_filename=backup_filename
                )
            except Exception:
                pass

        try:
            threading.Thread(
                target=perform_update,
                daemon=True,
                name="nexdeck-compose-update",
            ).start()
        except RuntimeError:
            self.server.runner.state.stage = "failed"
            self.server.runner.state.error = "Cannot start update worker"
            self.server.runner.lock.release()
            self._reply(503, {"error": "worker_unavailable"})
            return

        self._reply(202, {"status": "accepted"})


class UnixAgentServer(socketserver.UnixStreamServer):
    """Local-only update agent."""

    allow_reuse_address = False

    def __init__(self, socket_path, manifest_path, token):
        self.manifest_path = manifest_path
        self.agent_token = token
        self.runner = ComposeRunner(
            load_trusted_manifest(manifest_path)
        )
        super().__init__(str(socket_path), AgentHandler)


def load_agent_token(token_file: Path | None = None) -> str:
    """Load a token, refusing insecure or unreadable credential files."""

    if token_file is None:
        token = os.environ.get("NEXDECK_UPDATE_AGENT_TOKEN", "")
    else:
        fd = None
        try:
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
            fd = os.open(token_file, flags)
            info = os.fstat(fd)

            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Credential must be a regular file")

            if info.st_mode & 0o077:
                raise ValueError("Credential permissions are too broad")

            if info.st_nlink != 1:
                raise ValueError("Credential must not have hard links")

            if info.st_uid not in (0, os.geteuid()):
                raise ValueError("Unexpected credential owner")

            with os.fdopen(fd, "rb") as stream:
                fd = None
                content = stream.read(4097)

            if len(content) > 4096:
                raise ValueError("Credential is too large")

            token = content.decode("utf-8").rstrip("\r\n")
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("Cannot securely load agent credential") from exc
        finally:
            if fd is not None:
                os.close(fd)

    if len(token) < 32 or len(token) > 4096:
        raise ValueError("Agent token length is invalid")

    if any(character.isspace() for character in token):
        raise ValueError("Agent token must not contain whitespace")

    return token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--socket-gid",
        type=str,
        default=None,
        help="Optional numeric group ID or 'primary' for the process GID",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help="Protected credential file (takes precedence over environment)",
    )
    args = parser.parse_args()

    if args.socket_gid == "primary":
        socket_gid = os.getgid()
    elif args.socket_gid is None:
        socket_gid = None
    else:
        try:
            socket_gid = int(args.socket_gid)
        except ValueError:
            parser.error("--socket-gid must be a non-negative integer or 'primary'")

        if socket_gid < 0:
            parser.error("--socket-gid must be non-negative")

    try:
        token = load_agent_token(args.token_file)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.socket.exists():
        raise SystemExit("Socket path already exists; refusing to replace it")

    old_umask = os.umask(0o177)

    try:
        with UnixAgentServer(args.socket, args.manifest, token) as server:
            if socket_gid is not None:
                os.chown(args.socket, -1, socket_gid)
                os.chmod(args.socket, 0o660)
            else:
                os.chmod(args.socket, 0o600)

            server.serve_forever()
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    main()
