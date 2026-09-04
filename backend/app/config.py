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
    #: Path prefix when nexdeck runs below a sub path of a domain.
    url_base: str = ""
    #: ``auto`` sets the Secure cookie flag when the request came over HTTPS
    #: (directly or via ``X-Forwarded-Proto``); ``always``/``never`` force it.
    cookie_secure: Literal["auto", "always", "never"] = "auto"
    #: Days a browser session stays valid without activity.
    session_days: int = 30
    bcrypt_rounds: int = 12
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
        """The configured secret, or the generated one from the data directory."""
        if self.secret_key:
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated, encoding="utf-8")
        return generated


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests change the environment; they call this afterwards."""
    get_settings.cache_clear()
