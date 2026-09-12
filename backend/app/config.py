"""Runtime settings, read once from the environment.

Everything is prefixed ``NEXDECK_``. The data directory holds the database,
the encryption key, uploads and caches; it is the only thing that needs to
persist between container restarts.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXDECK_", extra="ignore")

    #: Where the database, key file, uploads and caches live.
    data_dir: Path = Path("data")
    #: The built frontend. Empty means "not served" (development mode).
    static_dir: Path | None = None
    #: Secret used for session signing and secret encryption. When empty a
    #: random key is generated once and stored in ``data/secret.key``.
    secret_key: str = ""
    #: Public URL as seen by browsers, e.g. ``https://deck.example.com``.
    #: Needed for OIDC return addresses and Web Push.
    public_url: str = ""
    #: ``auto`` sets the Secure cookie flag when the request came over HTTPS
    #: (directly or via ``X-Forwarded-Proto``); ``always``/``never`` force it.
    cookie_secure: Literal["auto", "always", "never"] = "auto"
    #: Days a browser session stays valid without activity.
    session_days: int = 30
    bcrypt_rounds: int = 12
    #: How many database connections the pool holds, and how many more it may
    #: open under load. Both used to be SQLAlchemy's defaults, 5 and 10, and
    #: nothing anywhere said so: not the settings, not the README, not a
    #: comment. A ceiling that decides when the server stops answering should
    #: be a decision, not a default nobody knows about.
    #:
    #: ⚠️ ``request_threads`` must stay below ``db_pool_size + db_max_overflow``.
    #: Most routes are synchronous, so each one occupies a worker thread and a
    #: connection at the same time; more threads than connections only moves the
    #: queue from one place to the other, and the background services need a few
    #: connections of their own on top.
    db_pool_size: int = 20
    db_max_overflow: int = 20
    #: Worker threads for synchronous routes (anyio's default is 40).
    request_threads: int = 24
    #: Start with every integration in demo mode: fake, moving data.
    demo: bool = False
    log_level: str = "INFO"
    #: Raw samples are kept this many hours, minute averages this many hours.
    history_raw_hours: int = 1
    history_minute_hours: int = 24
    #: Container log lines are kept this many hours.
    log_history_hours: int = 6
    #: Default interval for reachability checks, in seconds.
    health_interval_seconds: int = 30
    #: A target must be down this long before an outage is announced.
    outage_threshold_seconds: int = 120
    #: Icon proxy cache lifetime in days.
    icon_cache_days: int = 30
    #: Check GitHub for a newer nexdeck release. Off by default: it is an
    #: outbound call that the operator has to opt into.
    update_check: bool = False
    #: Allowed origins for API calls from other origins. Empty means only the
    #: dashboard itself may call the API from a browser.
    cors_origins: str = ""
    #: How often a snapshot is written by itself, in hours. ``0`` switches it
    #: off.
    #:
    #: ⚠️ Until 07.09.2026 there was no such thing. The code knew the kind
    #: "automatic", swept the old ones and the interface said "the last five
    #: automatic ones are kept", and not one was ever written: the only
    #: snapshot that ever happened by itself was the one before a restore. A
    #: sweeper without a writer is a promise with nothing behind it.
    backup_every_hours: int = 24
    #: How long the rows nobody reads again are kept. ``0`` switches a sweep
    #: off and lets that table grow, which is what all three did until now.
    #:
    #: ⚠️ Three numbers, not one, because they are three different promises.
    #: The action log is the record of who pressed what and belongs to the
    #: operator. The notice centre is an inbox: a message nobody opened in
    #: three months is not going to be opened. An outage is a fact about a
    #: service, worth keeping for a year, and one that has not ended yet is
    #: never swept whatever its age, because it is the reason a card is red.
    keep_action_log_days: int = 90
    keep_notices_days: int = 90
    keep_outages_days: int = 365
    #: What one account may have lying in the uploads directory, in megabytes.
    #: ``0`` means no ceiling.
    #:
    #: ⚠️ There was none. Every member could write next to the database until
    #: the disk was full, and nothing swept a file that no board pointed at any
    #: more. 200 MB is roughly seventeen backgrounds at the largest size the
    #: upload allows.
    upload_quota_mb: int = 200
    #: Let outbound calls reach 127.0.0.1 and the link-local range.
    #:
    #: ⚠️ Off, and it should stay off. The server sits inside the network and
    #: reaches what a member's browser cannot: nexdeck's own API, the router,
    #: the hypervisor. A notification channel takes an address and reports back
    #: what the answer was, which turns that field into a way of asking what
    #: else is listening. ``169.254.169.254`` hands out the host's credentials
    #: on every cloud. Set this only when a service really does live on
    #: localhost next to nexdeck.
    allow_loopback_targets: bool = False
    #: Filled on the first read of the generated key file; not a setting.
    _remembered_key: str = ""

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nexdeck.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def boards_dir(self) -> Path:
        """Provisioned boards: YAML files that override the database."""
        return self.data_dir / "boards"

    def resolved_secret_key(self) -> str:
        """The configured secret, or the generated one from the data directory.

        ⚠️ Remembered after the first read. Every signed cookie, every session
        check and every stored secret goes through here, so this ran on every
        single request: a ``mkdir`` and a read from disk, for a value that
        cannot change while the process is alive.
        """
        if self.secret_key:
            return self.secret_key
        if self._remembered_key:
            return self._remembered_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            # ⚠️ A file from before 07.09.2026 was written with whatever the
            # umask allowed and has only been read since, so it kept 0644.
            # Narrowed here on the first read; a volume that refuses is no
            # reason not to start.
            if key_file.stat().st_mode & 0o077:
                try:
                    key_file.chmod(0o600)
                except OSError:
                    pass
            self._remembered_key = key_file.read_text(encoding="utf-8").strip()
            return self._remembered_key
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated, encoding="utf-8")
        # ⚠️ This one file makes every stored API key readable. It used to be
        # written with whatever the umask allowed, which under Docker is 0644:
        # readable by every account on the host that can see the data volume.
        # Windows has no mode bits, so a failure here is not one.
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        self._remembered_key = generated
        return generated


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests change the environment; they call this afterwards."""
    get_settings.cache_clear()
