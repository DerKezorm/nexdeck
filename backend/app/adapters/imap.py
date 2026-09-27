"""IMAP: unread mail and the latest senders and subjects of any mailbox, for services that only speak by mail.

Measured on 27.09.2026 against Dovecot 2.4.5 from the official image
``dovecot/dovecot``, once as it comes (TLS on 993, STARTTLS on 143) and once
with TLS off and plain passwords allowed, and against Stalwart 0.16.23 from
``stalwartlabs/stalwart`` on 993 and on a listener for 143 added by hand.
Made-up mails went in by APPEND, one by SMTP: encoded words in UTF-8 and
ISO-8859-1, a display name in base64, senders with and without a name, a mail
without subject and date, a broken byte, a folded subject, read and unread,
a folder with an umlaut in its name, an empty one. All three cards ran against
both servers. Also measured: a wrong password, an unknown folder, a closed
port, an address nobody answers at, a web server and an SSH server on the
port, TLS against the STARTTLS port and plain against the TLS port, STARTTLS
where the server has none, and the self-signed certificates of both with and
without "Ignore TLS errors". Gmail and Microsoft 365 were not measured.

⚠️ Nothing here changes a mailbox. A folder is opened with ``EXAMINE``, never
``SELECT``, or only asked about with ``STATUS``, and headers are fetched with
``BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]``. Either alone keeps the
``\\Seen`` flag where it is; both are here because a server that treats one
of them loosely must not be able to mark a mail read behind somebody's back.
Measured: Dovecot sets ``\\Seen`` on a plain ``BODY[HEADER.FIELDS ...]`` in a
selected folder and not in an examined one; Stalwart set it in neither, which
is not what RFC 3501 says. The flags of every test mail were the same before
and after all cards had run on both servers. The text of a mail is never asked
for: a board that others look at shows who wrote and about what, not what.

⚠️ Both servers announce ``LOGINDISABLED`` on a port without TLS, and Dovecot
answers a LOGIN sent anyway with an alert that the password was exposed. So
the capability is read first and the password stays at home. The same for
STARTTLS asked of a server that does not offer it: going on without would be
exactly the downgrade somebody in between would try. What a server said
before TLS is thrown away and asked again after it, and bytes sent behind the
OK to STARTTLS are refused rather than read as if they had come encrypted.

⚠️ A wrong password costs time on purpose. Dovecot answered ``NO
[AUTHENTICATIONFAILED]`` after 1.5 s, the next ones in a row after 5.5 and
6 s, and the right password straight after a wrong one waited 4 s as well;
LOGIN gets fifteen seconds for that. Stalwart answered in a fifth of a second. Both say no more than
``AUTHENTICATIONFAILED``.

⚠️ Special folders are known by their SPECIAL-USE attribute (RFC 6154),
never by their name: Stalwart calls them "Deleted Items", "Junk Mail" and
"Sent Items", Dovecot "Trash", "Junk" and "Sent", plus an "Archive" that
Stalwart does not have. Stalwart quotes every name, "INBOX" too; Dovecot
writes atoms where it can.

⚠️ Stalwart 0.16 opens no port 143 at all out of the box, only 993.

⚠️ The age on the list is the arrival, ``INTERNALDATE``, and the Date
header only where that is missing. A mail delivered to Stalwart over SMTP
with a Date of 1 January 2000, the clock of a printer that lost it, arrived
with the minute it came in. Stalwart's own filter put that mail in "Junk
Mail": mail from a service can end up there, and the folder card leaves junk
out unless told otherwise; the unread card can be pointed at it.

⚠️ Folder names go out in modified UTF-7 (RFC 3501), the umlaut folder as
``Pr&APw-fungen``, on both servers, although both offer ``UTF8=ACCEPT``: it is
never enabled. A name that arrives as raw UTF-8 anyway is read as UTF-8.

⚠️ A plain connection to the TLS port and a web server on the port look the
same from here: the connection is taken and nothing comes back, so the card
says so after eight seconds. An SSH server greets with something else and is
named at once; TLS against a port without it fails in the handshake.

⚠️ Both servers have LIST-STATUS (RFC 5819), so the folder card asks about
every folder in one command. A server without it gets one STATUS per folder.

⚠️ No OAuth2. A user name and a password, or an app password where the
provider wants one. Microsoft 365 has mostly switched passwords off for IMAP.
"""

from __future__ import annotations

import asyncio
import base64
import email.utils
import re
import socket
import ssl
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from email.header import decode_header
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    ago,
    guard_outbound,
)

DEFAULT_PORT = {"tls": 993, "starttls": 143, "none": 143}
#: How long the connection, the TLS handshake and each whole answer may take.
#: The collector gives a card twenty seconds in all.
TIMEOUT = 8.0
#: A wrong password costs time on purpose. Dovecot 2.4.5 answered the second
#: one in a row after 5.5 s, and the right one straight after a wrong one after 4 s.
LOGIN_TIMEOUT = 15.0
#: The longest line taken, a SEARCH over a very large folder included.
MAX_LINE = 8 * 1024 * 1024
#: The largest literal taken. Three header fields are a few hundred bytes.
MAX_LITERAL = 1024 * 1024
#: How deep parentheses may nest before an answer counts as garbage.
MAX_DEPTH = 32
#: How many folders the folder card asks about, one STATUS each without LIST-STATUS.
MAX_FOLDERS = 200
#: How many mails the list card shows at most.
MOST = 20
#: The one fetch this adapter makes of a mail: flags, arrival and three header fields.
#: ⚠️ PEEK: a plain ``BODY[...]`` sets \Seen on a folder that was selected.
FETCH_ITEMS = b"(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
PORT_HINT = ("IMAP listens on 993 with TLS and on 143 with STARTTLS or without encryption. "
             "Check that the port and the encryption belong together.")
PASSWORD_HINT = ("Gmail and many other providers want an app password here, not the account password. "
                 "Microsoft 365 has mostly switched passwords off for IMAP and wants OAuth2, which this card does not speak.")
INBOX = "INBOX"
#: What a folder is for, by its SPECIAL-USE attribute (RFC 6154), not by its name.
SPECIAL = {"\\drafts": "Drafts", "\\sent": "Sent", "\\trash": "Trash", "\\junk": "Junk",
           "\\archive": "Archive", "\\all": "All mail", "\\flagged": "Flagged"}
MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


class Offline(Exception):
    """Nothing took the connection."""


class Silent(Exception):
    """The port took the connection and sent no greeting."""


class NotImap(Exception):
    """Something answered, but not the way an IMAP server does."""


class Closed(Exception):
    """The server hung up in the middle, with BYE or without a word."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.text = text


class Stalled(Exception):
    """The server stopped answering after the greeting."""


class TooLarge(Exception):
    """An answer beyond anything a card reads."""


class TlsFailed(Exception):
    def __init__(self, reason: str, untrusted: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.untrusted = untrusted


# -- folder names: modified UTF-7 (RFC 3501, 5.1.3) ---------------------------


def encode_folder(name: str) -> bytes:
    """A folder name as IMAP4rev1 writes it: printable ASCII as is, ``&`` as ``&-``, the rest as base64 of UTF-16."""
    out = bytearray()
    pending = ""

    def flush() -> None:
        nonlocal pending
        if pending:
            packed = base64.b64encode(pending.encode("utf-16-be")).rstrip(b"=").replace(b"/", b",")
            out.extend(b"&" + packed + b"-")
            pending = ""

    for char in name:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            out.extend(b"&-" if char == "&" else char.encode("ascii"))
        else:
            pending += char
    flush()
    return bytes(out)


def decode_folder(raw: bytes) -> str:
    """The name a person reads. Tolerant: a broken shift stays as it came, raw UTF-8 is taken as UTF-8."""
    if any(byte > 0x7F for byte in raw):
        # ⚠️ Not what RFC 3501 allows, but a server that enabled UTF8=ACCEPT on
        # its own sends names like that.
        return raw.decode("utf-8", "replace")
    text = raw.decode("ascii")
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        end = text.find("-", index + 1) if char == "&" else -1
        if char != "&" or end < 0:
            out.append(char)
            index += 1
            continue
        chunk = text[index + 1:end]
        if not chunk:
            out.append("&")
        else:
            try:
                packed = chunk.replace(",", "/")
                decoded = base64.b64decode(packed + "=" * (-len(packed) % 4), validate=True).decode("utf-16-be")
            except (ValueError, UnicodeDecodeError):
                decoded = text[index:end + 1]
            out.append(decoded)
        index = end + 1
    return "".join(out)


def _quoted(raw: bytes) -> bytes:
    return b'"' + raw.replace(b"\\", b"\\\\").replace(b'"', b'\\"') + b'"'


def folder_argument(name: str) -> bytes:
    """A folder name as the argument of a command, or an error for one no server can have."""
    if not name or len(name) > 1000 or any(char in name for char in "\r\n\x00"):
        raise AdapterError("That is not a folder name.", code="imap_no_folder",
                           hint="Pick the folders again in the card's settings.")
    if name.upper() == INBOX:
        return b"INBOX"
    return _quoted(encode_folder(name))


# -- headers ----------------------------------------------------------------------


CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _text(raw: bytes) -> str:
    """Raw header bytes as text: UTF-8 when it is, Windows-1252 when it is not."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def _one_line(text: str, most: int = 300) -> str:
    flat = " ".join(CONTROL.sub(" ", text).split())
    return flat if len(flat) <= most else flat[: most - 1].rstrip() + "…"


def decode_words(value: str) -> str:
    """RFC 2047 encoded words in a header, in whatever character set they name, broken ones tolerated."""
    if "=?" not in value:
        return _one_line(value)
    try:
        pieces = decode_header(value)
    except Exception:  # noqa: BLE001 - a header nobody can decode is shown as it came
        return _one_line(value)
    out: list[str] = []
    for chunk, charset in pieces:
        if isinstance(chunk, str):
            out.append(chunk)
            continue
        name = (charset or "").lower()
        if name in ("", "unknown-8bit", "x-unknown"):
            out.append(_text(chunk))
            continue
        try:
            out.append(chunk.decode(name, "replace"))
        except LookupError:
            # A character set Python has never heard of: UTF-8 if it is, else a guess.
            out.append(_text(chunk))
    # An encoded word that decodes to nothing at all was no encoded word.
    return _one_line("".join(out)) or _one_line(value)


def header_fields(block: bytes) -> dict[str, str]:
    """The first value of each header field in a block, unfolded, as text still to be decoded."""
    fields: dict[str, str] = {}
    current = ""
    for line in block.replace(b"\r\n", b"\n").split(b"\n"):
        if line[:1] in (b" ", b"\t") and current:
            fields[current] += " " + _text(line).strip()
            continue
        name, colon, value = line.partition(b":")
        current = ""
        if colon and name.strip() and b" " not in name.strip():
            key = name.strip().decode("ascii", "replace").lower()
            if key not in fields:
                fields[key] = _text(value).strip()
                current = key
    return fields


def sender(raw: str) -> str:
    """The display name of a From field, or the address when there is none."""
    name, address = email.utils.parseaddr(raw)
    name = decode_words(name)
    if name:
        return name
    if address:
        return _one_line(address)
    return decode_words(raw) or "?"


def parse_date(raw: str) -> float | None:
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.timestamp()


def internal_date(raw: bytes) -> float | None:
    """``27-Sep-2026 09:15:00 +0200``, read without the locale: ``%b`` would follow it."""
    match = re.fullmatch(rb"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)\s*", raw)
    if not match:
        return None
    day, month, year, hour, minute, second, sign, zone_hours, zone_minutes = match.groups()
    number = MONTHS.get(month.decode().lower())
    if number is None:
        return None
    offset = timedelta(hours=int(zone_hours), minutes=int(zone_minutes)) * (-1 if sign == b"-" else 1)
    try:
        when = datetime(int(year), number, int(day), int(hour), int(minute), int(second), tzinfo=timezone(offset))
    except ValueError:
        return None
    return when.timestamp()


# -- the protocol -------------------------------------------------------------------


STATUS_LINE = re.compile(rb"^(OK|NO|BAD|BYE|PREAUTH)(?: \[([^\]]*)\])? ?(.*)$", re.IGNORECASE | re.DOTALL)
LITERAL_AT_END = re.compile(rb"\{(\d{1,12})\+?\}\r?\n?$")


def tokens(line: bytes, literals: list[bytes]) -> list[Any]:
    """One response as nested lists of bytes: atoms, strings and literals alike, NIL as ``None``.

    Literals stand in the line as ``\\0<index>\\0``; NUL never occurs in an
    IMAP line, and the reader takes out any that a server sends anyway.
    """
    stack: list[list[Any]] = [[]]
    index, size = 0, len(line)
    while index < size:
        char = line[index]
        if char == 0x20:
            index += 1
        elif char == 0x28:
            if len(stack) > MAX_DEPTH:
                raise NotImap
            stack.append([])
            index += 1
        elif char == 0x29:
            if len(stack) > 1:
                done = stack.pop()
                stack[-1].append(done)
            index += 1
        elif char == 0x22:
            end = index + 1
            buffer = bytearray()
            while end < size and line[end] != 0x22:
                if line[end] == 0x5C and end + 1 < size:
                    end += 1
                buffer.append(line[end])
                end += 1
            stack[-1].append(bytes(buffer))
            index = end + 1
        elif char == 0x00:
            end = line.find(b"\x00", index + 1)
            try:
                stack[-1].append(literals[int(line[index + 1:end])])
            except (ValueError, IndexError) as error:
                raise NotImap from error
            index = end + 1
        else:
            # An atom. Brackets belong to it with everything inside them:
            # ``BODY[HEADER.FIELDS (FROM SUBJECT DATE)]`` is one item.
            end, depth = index, 0
            while end < size:
                here = line[end]
                if here == 0x5B:
                    depth += 1
                elif here == 0x5D and depth:
                    depth -= 1
                elif here == 0x00 or (not depth and here in b" ()"):
                    break
                end += 1
            atom = line[index:end]
            stack[-1].append(None if atom.upper() == b"NIL" else atom)
            index = max(end, index + 1)
    while len(stack) > 1:
        done = stack.pop()
        stack[-1].append(done)
    return stack[0]


@dataclass
class Reply:
    state: str
    code: str
    text: str
    #: Every untagged response on the way, as ``tokens`` gives them.
    data: list[list[Any]] = field(default_factory=list)


def _status(rest: bytes) -> tuple[str, str, str]:
    match = STATUS_LINE.match(rest)
    if not match:
        raise NotImap
    state, code, text = match.groups()
    return state.decode().upper(), (code or b"").decode("utf-8", "replace"), _one_line(_text(text), 200)


def _upper(value: Any) -> str:
    return value.decode("ascii", "replace").upper() if isinstance(value, bytes) else ""


#: What OpenSSL says when the other side answers a TLS hello with something else.
NOT_TLS = {"WRONG_VERSION_NUMBER", "RECORD_LAYER_FAILURE", "PACKET_LENGTH_TOO_LONG", "HTTP_REQUEST",
           "UNEXPECTED_RECORD", "UNKNOWN_PROTOCOL"}


def _readable(error: ssl.SSLError) -> str:
    reason = str(error.reason or "")
    if reason.upper() in NOT_TLS:
        return "the other side does not speak TLS"
    return reason.replace("_", " ").lower() or "the handshake failed"


@dataclass(frozen=True)
class Literal:
    value: bytes


class Client:
    """One IMAP conversation over an asyncio stream: commands out, whole answers back."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.capabilities: set[str] = set()
        self.counter = 0
        self.preauth = False

    async def _line(self) -> bytes:
        try:
            line = await self.reader.readuntil(b"\n")
        except asyncio.IncompleteReadError as error:
            raise Closed() from error
        except asyncio.LimitOverrunError as error:
            raise TooLarge from error
        except (ConnectionError, OSError) as error:
            raise Closed() from error
        return line.replace(b"\x00", b"")

    async def _response(self) -> tuple[bytes, list[bytes]]:
        """One response, literals read in between, as a line with markers and the literals."""
        parts: list[bytes] = []
        literals: list[bytes] = []
        while True:
            line = await self._line()
            match = LITERAL_AT_END.search(line)
            if not match:
                parts.append(line.rstrip(b"\r\n"))
                break
            length = int(match.group(1))
            if length > MAX_LITERAL:
                raise TooLarge
            parts.append(line[: match.start()] + b"\x00%d\x00" % len(literals))
            try:
                literals.append(await self.reader.readexactly(length))
            except (asyncio.IncompleteReadError, ConnectionError, OSError) as error:
                raise Closed() from error
        return b"".join(parts), literals

    async def greeting(self) -> None:
        try:
            async with asyncio.timeout(TIMEOUT):
                line, literals = await self._response()
        except (TimeoutError, Closed) as error:
            raise Silent from error
        except TooLarge as error:
            raise NotImap from error
        if not line.startswith(b"* "):
            raise NotImap
        state, code, text = _status(line[2:])
        if state == "BYE":
            raise Closed(text)
        if state not in ("OK", "PREAUTH"):
            raise NotImap
        self.preauth = state == "PREAUTH"
        self._take_capabilities(code)

    def _take_capabilities(self, code: str) -> None:
        if code.upper().startswith("CAPABILITY "):
            self.capabilities = set(code.upper().split()[1:])

    async def command(self, *parts: bytes | Literal, timeout: float | None = None) -> Reply:
        """Send one command and read until its tagged answer. Literals go the way the server allows."""
        self.counter += 1
        tag = b"nd%d" % self.counter
        try:
            async with asyncio.timeout(timeout or TIMEOUT):
                reply = await self._send(tag, parts)
                if reply is not None:
                    return reply
                return await self._until(tag)
        except TimeoutError as error:
            raise Stalled from error

    async def _send(self, tag: bytes, parts: tuple[bytes | Literal, ...]) -> Reply | None:
        pending = tag
        for part in parts:
            if isinstance(part, Literal):
                plus = "LITERAL+" in self.capabilities
                pending += b" {%d%s}\r\n" % (len(part.value), b"+" if plus else b"")
                self._write(pending)
                if not plus:
                    await self._drain()
                    line, literals = await self._response()
                    if not line.startswith(b"+"):
                        return self._tagged(tag, line, [])
                pending = part.value
            else:
                pending += b" " + part
        self._write(pending + b"\r\n")
        await self._drain()
        return None

    def _write(self, data: bytes) -> None:
        try:
            self.writer.write(data)
        except (ConnectionError, OSError) as error:
            raise Closed() from error

    async def _drain(self) -> None:
        try:
            await self.writer.drain()
        except (ConnectionError, OSError) as error:
            raise Closed() from error

    async def _until(self, tag: bytes) -> Reply:
        data: list[list[Any]] = []
        while True:
            line, literals = await self._response()
            if line.startswith(b"* "):
                rest = line[2:]
                if rest[:4].upper() == b"BYE " or rest.upper() == b"BYE":
                    raise Closed(_status(rest)[2])
                data.append(tokens(rest, literals))
            elif line.startswith(tag + b" "):
                return self._tagged(tag, line, data)
            elif line.startswith(b"+"):
                # Nothing here asks for a continuation outside a literal.
                raise NotImap

    def _tagged(self, tag: bytes, line: bytes, data: list[list[Any]]) -> Reply:
        if not line.startswith(tag + b" "):
            raise NotImap
        state, code, text = _status(line[len(tag) + 1:])
        if state not in ("OK", "NO", "BAD"):
            raise NotImap
        return Reply(state, code, text, data)

    async def start_tls(self, where: Settings) -> None:
        """TLS over the open connection: from the first byte on 993, after STARTTLS on 143."""
        # ⚠️ Anything the server sent before the handshake would be read after
        # it as if it had come encrypted: the STARTTLS response injection that
        # several mail clients were found open to. Such a server is refused.
        if getattr(self.reader, "_buffer", b""):
            raise TlsFailed("the server sent data before the handshake", untrusted=False)
        try:
            await self.writer.start_tls(_tls(where.insecure), server_hostname=where.host,
                                        ssl_handshake_timeout=TIMEOUT)
        except ssl.SSLCertVerificationError as error:
            raise TlsFailed(str(error.verify_message or error.reason or "not trusted"), untrusted=True) from error
        except ssl.SSLError as error:
            raise TlsFailed(_readable(error), untrusted=False) from error
        except (TimeoutError, ConnectionError, OSError) as error:
            # ⚠️ Plain HTTP and SSH servers drop a TLS hello without a word, or
            # keep quiet until the handshake gives up.
            raise TlsFailed("the handshake did not finish", untrusted=False) from error

    async def ask_capabilities(self) -> None:
        reply = await self.command(b"CAPABILITY")
        for item in reply.data:
            if item and _upper(item[0]) == "CAPABILITY":
                self.capabilities = {_upper(one) for one in item[1:] if isinstance(one, bytes)}
        self._take_capabilities(reply.code)

    async def logout(self) -> None:
        with suppress(Exception):
            async with asyncio.timeout(2):
                self.counter += 1
                self._write(b"nd%d LOGOUT\r\n" % self.counter)
                await self._drain()
                await self._until(b"nd%d" % self.counter)

    def close(self) -> None:
        with suppress(Exception):
            self.writer.close()


def _astring(value: str) -> bytes | Literal:
    """A user name or password: quoted when it is plain ASCII, a literal when it is not."""
    raw = value.encode("utf-8")
    if all(0x20 <= byte <= 0x7E for byte in raw):
        return _quoted(raw)
    return Literal(raw)


# -- one session ----------------------------------------------------------------------


@dataclass
class Settings:
    host: str
    port: int
    security: str
    username: str
    password: str
    insecure: bool


def settings(config: dict[str, Any]) -> Settings:
    security = str(config.get("security") or "tls").lower()
    if security not in DEFAULT_PORT:
        security = "tls"
    host = str(config.get("host") or "").strip()
    for scheme in ("imaps://", "imap://", "https://", "http://"):
        if host.lower().startswith(scheme):
            host = host[len(scheme):]
    host = host.strip("/").strip()
    port_text = str(config.get("port") or "").strip()
    if host.startswith("[") and "]:" in host:
        host, _, typed = host.rpartition(":")
        port_text = port_text or typed
    elif host.count(":") == 1:
        host, _, typed = host.partition(":")
        port_text = port_text or typed
    host = host.strip("[]")
    if not host:
        raise AdapterError("This connection names no server.", code="bad_url",
                           hint="Enter the name or the address of the mail server.")
    try:
        port = int(port_text) if port_text else DEFAULT_PORT[security]
    except ValueError:
        port = 0
    if not 0 < port < 65536:
        raise AdapterError("That is not a port number.", code="bad_url", hint=PORT_HINT)
    # ⚠️ Not HTTP, and still the same rule as every other connection:
    # link-local and the cloud metadata service are barred, by name.
    guard_outbound(f"http://{_bracketed(host)}:{port}")
    return Settings(host=host, port=port, security=security, username=str(config.get("username") or ""),
                    password=str(config.get("password") or ""), insecure=bool(config.get("insecure")))


def _bracketed(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _tls(insecure: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


async def _connect(where: Settings) -> Client:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(where.host, where.port, limit=MAX_LINE), TIMEOUT)
    except socket.gaierror as error:
        raise AdapterError(f"The name {where.host} does not resolve.", code="unreachable",
                           hint="Check the name of the mail server.") from error
    except (TimeoutError, OSError) as error:
        raise Offline from error
    client = Client(reader, writer)
    if where.security == "tls":
        try:
            await client.start_tls(where)
        except BaseException:
            client.close()
            raise
    return client


async def _sign_in(client: Client, where: Settings) -> None:
    await client.greeting()
    if where.security == "starttls":
        if client.preauth:
            raise AdapterError("The server signs in before STARTTLS could start.", code="imap_no_starttls",
                               hint="Choose TLS on port 993.")
        if not client.capabilities:
            await client.ask_capabilities()
        if "STARTTLS" not in client.capabilities:
            # ⚠️ Never on to LOGIN without it: that is exactly the downgrade
            # somebody in between would try, by taking the word out.
            raise AdapterError("The server does not offer STARTTLS, so the password was not sent.",
                               code="imap_no_starttls",
                               hint="Choose TLS on port 993 if the server has it. Without encryption the "
                                    "password would cross the network in the clear.")
        reply = await client.command(b"STARTTLS")
        if reply.state != "OK":
            raise AdapterError("The server refused to start TLS, so the password was not sent.",
                               code="imap_no_starttls", hint=reply.text)
        await client.start_tls(where)
        # What the server said before TLS may have been changed on the way.
        client.capabilities = set()
    if client.preauth:
        return
    if not client.capabilities:
        await client.ask_capabilities()
    if "LOGINDISABLED" in client.capabilities:
        # ⚠️ Dovecot and Stalwart both say so on a port without TLS. Dovecot
        # answers a LOGIN sent anyway with "If anyone was listening, the
        # password was exposed": the check has to come before, not after.
        raise AdapterError("The server takes no password without encryption, so the password was not sent.",
                           code="imap_login_disabled", hint="Choose TLS on port 993 or STARTTLS on port 143.")
    reply = await client.command(b"LOGIN", _astring(where.username), _astring(where.password),
                                 timeout=LOGIN_TIMEOUT)
    if reply.state == "OK":
        client._take_capabilities(reply.code)
        return
    code = reply.code.split(" ", 1)[0].upper()
    if code == "PRIVACYREQUIRED":
        raise AdapterError("The server takes no password without encryption.", code="imap_login_disabled",
                           hint="Choose TLS on port 993 or STARTTLS on port 143.")
    if code == "UNAVAILABLE":
        raise AdapterError("The server cannot sign anybody in right now.", code="imap_unavailable", hint=reply.text)
    if code in ("AUTHENTICATIONFAILED", "AUTHORIZATIONFAILED", ""):
        failed = AuthFailed("The server rejected the user name or the password.")
    else:
        # An [ALERT] is meant for a person: Gmail names the app password in it.
        failed = AuthFailed(f"The server rejected the sign-in: {reply.text}")
    failed.hint = PASSWORD_HINT
    raise failed


@asynccontextmanager
async def session(config: dict[str, Any]) -> AsyncIterator[Client]:
    """A signed-in conversation, said goodbye to and closed however the block ends."""
    where = settings(config)
    client = await _connect(where)
    try:
        await _sign_in(client, where)
        yield client
        await client.logout()
    finally:
        client.close()


# -- what a card asks -------------------------------------------------------------------


@dataclass
class Folder:
    name: str
    flags: frozenset[str]
    messages: int | None = None
    unseen: int | None = None

    @property
    def special(self) -> str:
        return next((SPECIAL[flag] for flag in SPECIAL if flag in self.flags), "")

    @property
    def selectable(self) -> bool:
        return not self.flags & {"\\noselect", "\\nonexistent"}


@dataclass
class Mail:
    folder: str
    uid: int
    unread: bool
    sender: str
    subject: str
    when: float | None


def _number(value: Any) -> int | None:
    try:
        return int(value) if isinstance(value, bytes) else None
    except ValueError:
        return None


def _status_numbers(items: Any) -> tuple[int | None, int | None]:
    if not isinstance(items, list):
        return None, None
    found = {_upper(items[index]): _number(items[index + 1]) for index in range(0, len(items) - 1, 2)}
    return found.get("MESSAGES"), found.get("UNSEEN")


def _folders_from(reply: Reply) -> list[Folder]:
    folders: dict[str, Folder] = {}
    numbers: dict[str, tuple[int | None, int | None]] = {}
    for item in reply.data:
        if len(item) >= 4 and _upper(item[0]) == "LIST" and isinstance(item[1], list) and isinstance(item[3], bytes):
            name = INBOX if item[3].upper() == b"INBOX" else decode_folder(item[3])
            flags = frozenset(one.decode("ascii", "replace").lower() for one in item[1] if isinstance(one, bytes))
            folders[name] = Folder(name, flags)
        elif len(item) >= 3 and _upper(item[0]) == "STATUS" and isinstance(item[1], bytes):
            name = INBOX if item[1].upper() == b"INBOX" else decode_folder(item[1])
            numbers[name] = _status_numbers(item[2])
    for name, (messages, unseen) in numbers.items():
        if name in folders:
            folders[name].messages, folders[name].unseen = messages, unseen
    return list(folders.values())[:MAX_FOLDERS]


async def list_folders(client: Client, *, counted: bool) -> list[Folder]:
    """Every folder, with its numbers when asked: in one command where LIST-STATUS allows, else one STATUS each."""
    if counted and "LIST-STATUS" in client.capabilities:
        reply = await client.command(b'LIST "" "*" RETURN (SPECIAL-USE STATUS (MESSAGES UNSEEN))')
    else:
        reply = await client.command(b'LIST "" "*"')
    if reply.state != "OK":
        raise AdapterError(f"The server refused to list the folders: {reply.text}", code="imap_refused")
    folders = [one for one in _folders_from(reply) if one.selectable]
    if counted:
        for folder in folders:
            if folder.messages is None:
                folder.messages, folder.unseen = await status(client, folder.name)
    return folders


async def status(client: Client, name: str) -> tuple[int | None, int | None]:
    """How many mails a folder holds and how many are unread, or ``(None, None)`` when it does not exist."""
    reply = await client.command(b"STATUS", folder_argument(name), b"(MESSAGES UNSEEN)")
    if reply.state != "OK":
        return None, None
    for item in reply.data:
        if len(item) >= 3 and _upper(item[0]) == "STATUS":
            return _status_numbers(item[2])
    return None, None


async def latest(client: Client, name: str, limit: int, unread_only: bool) -> list[Mail] | None:
    """The newest mails of one folder, newest first, or ``None`` when the folder does not exist."""
    # ⚠️ EXAMINE: read-only. SELECT would allow a fetch to set \Seen.
    reply = await client.command(b"EXAMINE", folder_argument(name))
    if reply.state != "OK":
        return None
    exists = 0
    for item in reply.data:
        if len(item) >= 2 and _upper(item[1]) == "EXISTS":
            exists = _number(item[0]) or 0
    if not exists:
        return []
    if unread_only:
        found = await client.command(b"UID SEARCH UNSEEN")
        uids = sorted({number for item in found.data if item and _upper(item[0]) == "SEARCH"
                       for number in (_number(one) for one in item[1:]) if number})
        if not uids:
            return []
        reply = await client.command(b"UID FETCH", ",".join(str(one) for one in uids[-limit:]).encode(), FETCH_ITEMS)
    else:
        reply = await client.command(b"FETCH", b"%d:%d" % (max(1, exists - limit + 1), exists), FETCH_ITEMS)
    mails = [mail for item in reply.data if (mail := _mail(name, item)) is not None]
    return sorted(mails, key=lambda one: one.uid, reverse=True)[:limit]


def _mail(folder: str, item: list[Any]) -> Mail | None:
    if len(item) < 3 or _upper(item[1]) != "FETCH" or not isinstance(item[2], list):
        return None
    pairs = item[2]
    values = {_upper(pairs[index]): pairs[index + 1] for index in range(0, len(pairs) - 1, 2)}
    header = next((value for key, value in values.items() if key.startswith("BODY[")), None)
    fields = header_fields(header) if isinstance(header, bytes) else {}
    flags = values.get("FLAGS")
    seen = isinstance(flags, list) and any(_upper(one) == "\\SEEN" for one in flags)
    arrived = values.get("INTERNALDATE")
    # ⚠️ Arrival first: a printer or a NAS with its clock at 2000 writes that
    # into Date, and the server's own stamp is when the mail really came in.
    when = internal_date(arrived) if isinstance(arrived, bytes) else None
    if when is None and fields.get("date"):
        when = parse_date(fields["date"])
    return Mail(folder=folder, uid=_number(values.get("UID")) or 0, unread=not seen,
                sender=sender(fields.get("from", "")) if fields.get("from") else "?",
                subject=decode_words(fields.get("subject", "")), when=when)


# -- the adapter ------------------------------------------------------------------------


def _picked(options: dict[str, Any]) -> list[str]:
    raw = options.get("folders")
    picked = [str(one) for one in raw if str(one).strip()] if isinstance(raw, list) else []
    return picked or [INBOX]


def _limit(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("limit") or 5)
    except (TypeError, ValueError):
        wanted = 5
    return max(1, min(MOST, wanted))


def _shown(name: str) -> str:
    return "Inbox" if name == INBOX else name


def _count(messages: int | None) -> str:
    return "1 message" if messages == 1 else f"{messages or 0} messages"


def _mail_row(mail: Mail, several: bool) -> dict[str, Any]:
    subject = mail.subject or "(no subject)"
    return {
        "id": f"{mail.folder}:{mail.uid}",
        "title": mail.sender or "?",
        # With one folder its name on every row says nothing.
        "subtitle": f"{subject} · {_shown(mail.folder)}" if several else subject,
        "value": ago(mail.when) if mail.when is not None else "",
        "status": "ok" if mail.unread else "unknown",
        "emphasis": mail.unread,
    }


def _unread_data(rows: list[tuple[str, int | None, int | None]]) -> WidgetData:
    found = [row for row in rows if row[1] is not None]
    missing = [row[0] for row in rows if row[1] is None]
    unread = sum(unseen or 0 for _name, _messages, unseen in found)
    items: list[dict[str, Any]] = []
    for name, messages, unseen in rows:
        if messages is None:
            items.append({"id": name, "title": _shown(name), "value": 0, "status": "bad",
                          "subtitle": "Not found on the server"})
        else:
            items.append({"id": name, "title": _shown(name), "value": unseen or 0, "status": "ok",
                          "subtitle": _count(messages)})
    meta: dict[str, Any] = {"headline": True, "empty": "No folder picked."}
    if missing:
        meta["status_reason"] = "A picked folder does not exist on the server"
        meta["notice"] = "A folder picked on this card does not exist on the server any more. Pick the folders again."
    return WidgetData(status="warn" if missing else "ok", primary={"label": "Unread", "value": unread},
                      items=items, metrics={"unread": float(unread)}, meta=meta)


def _folders_data(folders: list[Folder], options: dict[str, Any]) -> WidgetData:
    shown = [one for one in folders if one.name == INBOX or options.get("special") or not one.special]
    if options.get("only_unread"):
        shown = [one for one in shown if one.unseen]
    shown.sort(key=lambda one: (one.name != INBOX, one.name.casefold()))
    items = [{"id": one.name, "title": _shown(one.name), "value": one.unseen or 0,
              "subtitle": " · ".join(part for part in (one.special, _count(one.messages)) if part),
              "status": "ok", "emphasis": bool(one.unseen)} for one in shown]
    return WidgetData(status="ok", items=items,
                      meta={"empty": "No folder has unread mail." if options.get("only_unread") else "No folders."})


class ImapAdapter(Adapter):
    kind = "imap"
    label = "IMAP"
    category = "monitoring"
    description = ("Unread mail and the latest senders and subjects of any mailbox over IMAP, read-only and "
                   "without the text of a mail.")
    icon = "lucide:mail"
    # Every card ran against Dovecot 2.4.5 and Stalwart 0.16.23 on 2026-09-27.
    beta = False
    docs_url = "https://www.rfc-editor.org/rfc/rfc9051"
    keywords = ("Mail", "E-mail", "Dovecot", "Stalwart", "Gmail", "Microsoft 365", "Postfix", "Mailcow")
    fields = (
        Field("host", "Server", required=True, placeholder="mail.example.com",
              help="The name or the address of the IMAP server."),
        Field("security", "Encryption", type="select", default="tls",
              options=(("tls", "TLS (port 993)"), ("starttls", "STARTTLS (port 143)"),
                       ("none", "No encryption (port 143)")),
              help="TLS is the usual. Without encryption the password and every sender and subject cross the "
                   "network in the clear: only for a server on the same machine or on a network you trust."),
        Field("port", "Port", type="number", help="Empty means the usual one: 993 for TLS, 143 otherwise."),
        Field("username", "User name", required=True, placeholder="alerts@example.com",
              help="Usually the whole e-mail address."),
        Field("password", "Password", type="password", secret=True, required=True,
              help="The password of the mailbox, or an app password. " + PASSWORD_HINT),
        Field("insecure", "Ignore TLS errors", type="bool", default=False,
              help="For a server with a self-signed certificate."),
    )
    widgets = (
        WidgetType(
            kind="unread", label="Unread mail",
            description="Unread mail in the picked folders, in total and for each folder.",
            renderer="list", default_size=(2, 2), refresh_seconds=60, metrics=("unread",),
            options=(Field("folders", "Folders", type="choices", default=[],
                           help="Nothing picked means the inbox."),),
        ),
        WidgetType(
            kind="latest", label="Latest mail",
            description="Sender and subject of the newest mail, unread ones highlighted. The text of a mail is never read.",
            renderer="list", default_size=(3, 3), refresh_seconds=60,
            options=(
                Field("folders", "Folders", type="choices", default=[], help="Nothing picked means the inbox."),
                Field("limit", "Entries", type="number", default=5, help="Between 1 and 20."),
                Field("unread_only", "Only unread mail", type="bool", default=False),
            ),
        ),
        WidgetType(
            kind="folders", bars=True, label="Folders",
            description="Every folder of the mailbox with its unread and all its mail.",
            renderer="list", default_size=(3, 3), refresh_seconds=300,
            options=(
                Field("special", "Special folders", type="bool", default=False,
                      help="Drafts, sent mail, junk, trash and archive, as the server marks them."),
                Field("only_unread", "Only folders with unread mail", type="bool", default=False),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        # A mail server has no page of its own to open.
        return ""

    async def _run(self, config: dict[str, Any], job: Any) -> Any:
        where = settings(config)
        try:
            async with session(config) as client:
                return await job(client)
        except Offline as error:
            unreachable = Unreachable(f"Nothing answers on {where.host}:{where.port}.")
            unreachable.hint = "Check the name of the server and the port."
            raise unreachable from error
        except Silent as error:
            raise AdapterError(f"{where.host}:{where.port} takes the connection but sends no IMAP greeting.",
                               code="imap_no_greeting", hint=PORT_HINT) from error
        except NotImap as error:
            raise AdapterError(f"Something answers on {where.host}:{where.port}, but not an IMAP server.",
                               code="not_imap", hint=PORT_HINT) from error
        except TlsFailed as error:
            if error.untrusted:
                raise AdapterError(f"The server's certificate is not trusted: {error.reason}.", code="tls_untrusted",
                                   hint="A self-signed certificate needs “Ignore TLS errors”. Otherwise check that "
                                        "the server name is the one in the certificate.") from error
            raise AdapterError(f"No TLS handshake with {where.host}:{where.port}: {error.reason}.", code="tls_failed",
                               hint="Port 993 speaks TLS from the first byte; port 143 starts without it and "
                                    "needs STARTTLS.") from error
        except Stalled as error:
            raise AdapterError("The mail server stopped answering.", code="imap_timeout",
                               hint="It may be busy. The card asks again at the next refresh.") from error
        except Closed as error:
            raise AdapterError("The mail server closed the connection.", code="imap_closed", hint=error.text) from error
        except TooLarge as error:
            raise AdapterError("The mail server sent more than a card reads.", code="answer_too_large") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        where = settings(config)

        async def job(client: Client) -> str:
            messages, unseen = await status(client, INBOX)
            said = f"Signed in. The inbox holds {_count(messages)}, {unseen or 0} of them unread."
            if where.security == "none":
                offered = " The server offers STARTTLS; choose it." if "STARTTLS" in client.capabilities else ""
                said += " The password crossed the network unencrypted." + offered
            return said

        return await self._run(config, job)

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field == "folders":
            folders = await self._run(config, lambda client: list_folders(client, counted=False))
            folders.sort(key=lambda one: (one.name != INBOX, one.name.casefold()))
            return [(one.name, _shown(one.name)) for one in folders]
        return await super().choices(field, config, ctx)

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field == "folders":
            return [(one.name, _shown(one.name)) for one in DEMO_FOLDERS]
        return super().demo_choices(field)

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "unread":
            return await self._run(config, lambda client: self._unread(client, options))
        if widget_kind == "latest":
            return await self._run(config, lambda client: self._latest(client, options))
        if widget_kind == "folders":
            return await self._run(config, lambda client: self._folders(client, options))
        raise AdapterError("This adapter has no such widget.", code="no_such_widget")

    @staticmethod
    async def _unread(client: Client, options: dict[str, Any]) -> WidgetData:
        rows = []
        for name in _picked(options):
            messages, unseen = await status(client, name)
            rows.append((name, messages, unseen))
        return _unread_data(rows)

    @staticmethod
    async def _latest(client: Client, options: dict[str, Any]) -> WidgetData:
        picked = _picked(options)
        limit = _limit(options)
        unread_only = bool(options.get("unread_only"))
        mails: list[Mail] = []
        missing: list[str] = []
        for name in picked:
            found = await latest(client, name, limit, unread_only)
            if found is None:
                missing.append(name)
            else:
                mails += found
        if missing and len(missing) == len(picked):
            raise AdapterError(f"The folder {_shown(missing[0])} does not exist on the server.", code="imap_no_folder",
                               hint="Pick the folders again in the card's settings.")
        mails.sort(key=lambda one: (one.when if one.when is not None else 0.0, one.uid), reverse=True)
        meta: dict[str, Any] = {"empty": "No unread mail." if unread_only else "No mail in the folder."}
        if missing:
            meta["notice"] = "A folder picked on this card does not exist on the server any more. Pick the folders again."
        return WidgetData(status="warn" if missing else "ok",
                          items=[_mail_row(one, len(picked) > 1) for one in mails[:limit]], meta=meta)

    @staticmethod
    async def _folders(client: Client, options: dict[str, Any]) -> WidgetData:
        return _folders_data(await list_folders(client, counted=True), options)

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        folders = [Folder(one.name, one.flags, one.messages, (one.unseen or 0) + (tick // 120) % 3 if one.unseen else 0)
                   for one in DEMO_FOLDERS]
        if widget_kind == "folders":
            return _folders_data(folders, options)
        by_name = {one.name: one for one in folders}
        picked = _picked(options)
        if widget_kind == "unread":
            return _unread_data([(name, by_name[name].messages, by_name[name].unseen) if name in by_name
                                 else (name, None, None) for name in picked])
        now = time.time()
        # Ages rather than dates, so the demo never turns into last month.
        mails = [Mail(folder=folder, uid=uid, unread=unread, sender=who, subject=subject, when=now - minutes * 60)
                 for uid, (folder, who, subject, minutes, unread) in enumerate(DEMO_MAILS, start=1)
                 if folder in picked]
        if fake.flicker("imap-new", tick, 0.2):
            mails.insert(0, Mail(folder=INBOX, uid=99, unread=True, sender="Uptime monitor",
                                 subject="Service back up: wiki", when=now - 30))
        if options.get("unread_only"):
            mails = [one for one in mails if one.unread]
        return WidgetData(status="ok", items=[_mail_row(one, len(picked) > 1) for one in mails[: _limit(options)]],
                          meta={"empty": "No unread mail." if options.get("unread_only") else "No mail in the folder."})


DEMO_FOLDERS = [
    Folder(INBOX, frozenset(), 214, 3),
    Folder("Alerts", frozenset(), 88, 5),
    Folder("Backups", frozenset(), 412, 1),
    Folder("Reports/Daily", frozenset(), 31, 0),
    Folder("Drafts", frozenset({"\\drafts"}), 2, 0),
    Folder("Sent", frozenset({"\\sent"}), 57, 0),
    Folder("Junk", frozenset({"\\junk"}), 19, 4),
    Folder("Trash", frozenset({"\\trash"}), 12, 0),
]
DEMO_MAILS = [
    (INBOX, "Backup Server", "Nightly backup finished", 7, True),
    (INBOX, "ups@example.com", "Power restored, running on mains again", 45, True),
    (INBOX, "Certificate watch", "Certificate for wiki.example.com expires in 14 days", 180, False),
    (INBOX, "Router", "Firmware update available", 1500, False),
    (INBOX, "Printer", "Toner low", 2900, False),
]


ADAPTER = ImapAdapter()
