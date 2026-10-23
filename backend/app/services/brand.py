"""The name and the logo of the installation.

An operator who hangs nexdeck on a wall, or hands it to a household, wants it
to carry their own name: in the browser tab, in the bar, on the sign-in page
and under the icon of the installed app. "About nexdeck" and the update
notices keep saying nexdeck, so nobody wonders what is running.

⚠️ The sign-in page shows both, so both are public: anyone who reaches the
address sees them, signed in or not. The settings page says so.

The files live in ``brand/`` beside the database and go into every backup.
The logo is checked like an uploaded icon. The two app icons are drawn by the
browser that uploads the logo (it can draw an SVG, the server cannot), and the
server checks that they are PNGs of the right size before it keeps them.
"""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DbSessionType

from ..config import get_settings
from ..models import Setting

KEY = "brand"
FOLDER = "brand"
#: Long enough for "Familie Beispiel, Haus am See", short enough for a bar.
MAX_NAME = 40
#: A logo is drawn at 26 pixels and at 512 at most; half a megabyte is plenty.
MAX_BYTES = 512 * 1024
#: The two sizes an installed app asks for, as drawn by the browser.
ICON_SIZES = (192, 512)
#: ``logo`` uses the logo, ``nexdeck`` keeps nexdeck's own mark.
SOURCES = ("logo", "nexdeck")
DEFAULTS: dict[str, Any] = {"name": "", "logo": "", "stamp": "", "favicon": "logo", "app_icon": "logo", "board_in_title": True}
#: Control characters and line breaks have no place in a title.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
#: The names a logo is kept under.
_LOGO_NAME = re.compile(r"^logo\.(svg|png|webp)$")


class BrandError(Exception):
    def __init__(self, message: str, code: str = "bad_brand") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def folder() -> Path:
    path = get_settings().data_dir / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def stored(db: DbSessionType) -> dict[str, Any]:
    row = db.get(Setting, KEY)
    value = {**DEFAULTS, **(dict(row.value) if row is not None else {})}
    logo = str(value.get("logo") or "")
    # Only a name this module writes: a restored or edited setting cannot point elsewhere.
    if not _LOGO_NAME.match(logo):
        logo = ""
    # A file the setting names but the disk lost (a restore from before the
    # folder was backed up) is no logo, rather than a broken picture everywhere.
    if logo and not (folder() / logo).is_file():
        logo = ""
    return {
        "name": str(value.get("name") or ""),
        "logo": logo,
        "stamp": str(value.get("stamp") or ""),
        "favicon": value["favicon"] if value.get("favicon") in SOURCES else "logo",
        "app_icon": value["app_icon"] if value.get("app_icon") in SOURCES else "logo",
        "board_in_title": value.get("board_in_title") is not False,
    }


def public(db: DbSessionType) -> dict[str, Any]:
    """What every page needs, signed in or not: addresses, never file names."""
    config = stored(db)
    logo = config["logo"]
    icons = logo and all((folder() / f"icon-{size}.png").is_file() for size in ICON_SIZES)
    version = f"?v={config['stamp']}" if config["stamp"] else ""
    return {
        "name": config["name"],
        "logo": f"/api/v1/brand/logo{version}" if logo else None,
        "favicon": f"/api/v1/brand/logo{version}" if logo and config["favicon"] == "logo" else None,
        "app_icons": (
            {str(size): f"/api/v1/brand/icon-{size}.png{version}" for size in ICON_SIZES}
            if icons and config["app_icon"] == "logo" else None
        ),
        "board_in_title": config["board_in_title"],
    }


def _write(db: DbSessionType, value: dict[str, Any]) -> None:
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()


def clean_name(name: Any) -> str:
    text = _CONTROL.sub("", str(name or "")).strip()
    if len(text) > MAX_NAME:
        raise BrandError(f"The name is longer than {MAX_NAME} characters.", "name_too_long")
    return text


def save(db: DbSessionType, incoming: dict[str, Any]) -> dict[str, Any]:
    current = stored(db)
    for field in ("favicon", "app_icon"):
        if incoming.get(field, "logo") not in SOURCES:
            raise BrandError(f"{field} is logo or nexdeck.", f"bad_{field}")
    board_in_title = incoming.get("board_in_title", True)
    if not isinstance(board_in_title, bool):
        raise BrandError("Whether the board stands in the tab is yes or no.", "bad_board_in_title")
    value = {
        **current,
        "name": clean_name(incoming.get("name")),
        "favicon": incoming.get("favicon", "logo"),
        "app_icon": incoming.get("app_icon", "logo"),
        "board_in_title": board_in_title,
    }
    _write(db, value)
    return stored(db)


def logo_type(data: bytes, content_type: str) -> str:
    """The extension the logo is stored under, or a refusal.

    The bytes decide, not the name a browser sends. SVG has no signature of
    its own, so it is taken only when the browser calls it SVG and it reads
    like one, and then it is checked like an uploaded icon.
    """
    from ..routers.assets import unsafe_svg

    if not data:
        raise BrandError("The file is empty.", "empty")
    if len(data) > MAX_BYTES:
        raise BrandError(f"The logo is larger than {MAX_BYTES // 1024} KB.", "too_large")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if content_type == "image/svg+xml" and b"<svg" in data[:4096].lower():
        refused = unsafe_svg(data)
        if refused:
            raise BrandError(f"The SVG was refused: {refused}.", "bad_svg")
        return "svg"
    raise BrandError("A logo is an SVG, a PNG or a WebP picture.", "bad_type")


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from a PNG's header, or None for anything else."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def save_logo(db: DbSessionType, logo: bytes, content_type: str, icons: dict[int, bytes]) -> dict[str, Any]:
    """Keep a new logo and the app icons drawn from it; the old files go."""
    suffix = logo_type(logo, content_type)
    for size in ICON_SIZES:
        icon = icons.get(size) or b""
        if len(icon) > MAX_BYTES:
            raise BrandError(f"The {size} pixel icon is larger than {MAX_BYTES // 1024} KB.", "too_large")
        if png_size(icon) != (size, size):
            raise BrandError(f"The app icon has to be a PNG of {size} by {size} pixels.", "bad_icon")
    remove_files()
    place = folder()
    (place / f"logo.{suffix}").write_bytes(logo)
    for size in ICON_SIZES:
        (place / f"icon-{size}.png").write_bytes(icons[size])
    # A new address for every new logo, so no browser and no proxy keeps the old one.
    stamp = hashlib.sha256(logo).hexdigest()[:12]
    _write(db, {**stored(db), "logo": f"logo.{suffix}", "stamp": stamp})
    return stored(db)


def remove_files() -> None:
    for path in folder().iterdir():
        if path.is_file() and (path.name.startswith("logo.") or path.name.startswith("icon-")):
            path.unlink(missing_ok=True)


def remove_logo(db: DbSessionType) -> dict[str, Any]:
    remove_files()
    _write(db, {**stored(db), "logo": "", "stamp": ""})
    return stored(db)


CONTENT_TYPES = {"svg": "image/svg+xml", "png": "image/png", "webp": "image/webp"}


def logo_file(db: DbSessionType) -> tuple[Path, str] | None:
    logo = stored(db)["logo"]
    if not logo:
        return None
    return folder() / logo, CONTENT_TYPES[logo.rsplit(".", 1)[-1]]


def icon_file(db: DbSessionType, size: int) -> Path | None:
    if size not in ICON_SIZES or not stored(db)["logo"]:
        return None
    path = folder() / f"icon-{size}.png"
    return path if path.is_file() else None


def manifest(db: DbSessionType, built: dict[str, Any]) -> dict[str, Any]:
    """The app manifest the build wrote, with the name and the icons of the installation."""
    brand = public(db)
    patched = dict(built)
    if brand["name"]:
        patched["name"] = brand["name"]
        patched["short_name"] = brand["name"]
    if brand["app_icons"]:
        icons = brand["app_icons"]
        patched["icons"] = [
            {"src": icons["192"], "sizes": "192x192", "type": "image/png"},
            {"src": icons["512"], "sizes": "512x512", "type": "image/png"},
            {"src": icons["512"], "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
    return patched
