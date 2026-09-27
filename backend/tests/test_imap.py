"""IMAP, against what Dovecot 2.4.5 and Stalwart 0.16.23 answered on 27.09.2026.

IMAP is a raw socket, so the servers here are small asyncio servers on
127.0.0.1 that answer the way the live ones did, with the same greetings,
capabilities, folder lists and header blocks. They keep flags like a real
server, so a fetch that would mark a mail read shows up as a changed flag.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import socket
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.adapters import get_adapter, imap
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

ADAPTER = get_adapter("imap")
USER = "cards@example.com"
PASSWORD = "imap-test-password-for-the-cards"
#: "Pruefungen" with a u-umlaut, as a person reads it and as IMAP4rev1 writes it.
CHECKS = "Pr\u00fcfungen"
CHECKS_WIRE = b"Pr&APw-fungen"

DOVECOT_GREETING = (b"* OK [CAPABILITY IMAP4rev1 IMAP4rev2 LOGIN-REFERRALS ID ENABLE IDLE SASL-IR LITERAL+ "
                    b"AUTH=PLAIN] Dovecot ready.")
DOVECOT_143 = (b"* OK [CAPABILITY IMAP4rev1 IMAP4rev2 LOGIN-REFERRALS ID ENABLE IDLE SASL-IR LITERAL+ STARTTLS "
               b"LOGINDISABLED] Dovecot ready.")
DOVECOT_AFTER_TLS = b"IMAP4rev1 IMAP4rev2 LOGIN-REFERRALS ID ENABLE IDLE SASL-IR LITERAL+ AUTH=PLAIN"
DOVECOT_SIGNED_IN = (b"IMAP4rev1 IMAP4rev2 SASL-IR LOGIN-REFERRALS ID ENABLE IDLE SORT UNSELECT CHILDREN NAMESPACE "
                     b"UIDPLUS LIST-EXTENDED CONDSTORE ESEARCH LIST-STATUS BINARY MOVE SPECIAL-USE LITERAL+ UTF8=ACCEPT")
STALWART_GREETING = (b"* OK [CAPABILITY IMAP4rev2 IMAP4rev1 ENABLE SASL-IR LITERAL+ ID UTF8=ACCEPT AUTH=PLAIN "
                     b"AUTH=OAUTHBEARER AUTH=XOAUTH2] Stalwart IMAP4rev2 at your service.")
STALWART_143 = (b"* OK [CAPABILITY IMAP4rev2 IMAP4rev1 ENABLE SASL-IR LITERAL+ ID UTF8=ACCEPT LOGINDISABLED "
                b"STARTTLS] Stalwart IMAP4rev2 at your service.")
STALWART_SIGNED_IN = (b"IMAP4rev2 IMAP4rev1 ENABLE SASL-IR LITERAL+ ID UTF8=ACCEPT IDLE NAMESPACE CHILDREN UNSELECT "
                      b"UIDPLUS ESEARCH LIST-EXTENDED LIST-STATUS SPECIAL-USE CREATE-SPECIAL-USE MOVE CONDSTORE")
#: A server of the old kind: no LITERAL+, no LIST-STATUS, no SPECIAL-USE.
OLD_GREETING = b"* OK IMAP4rev1 server ready"
OLD_CAPABILITIES = b"IMAP4rev1 IDLE"

FIELDS = b"BODY[HEADER.FIELDS (FROM SUBJECT DATE)]"


def header(*lines: str) -> bytes:
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") if lines else b"\r\n"


@dataclass
class FakeMail:
    uid: int
    flags: set[str]
    arrived: str | None
    header: bytes


@dataclass
class FakeFolder:
    wire: bytes
    attributes: tuple[str, ...] = ()
    mails: list[FakeMail] = field(default_factory=list)


def inbox_mails() -> list[FakeMail]:
    """The six mails as both servers handed them back, byte for byte, arrival a minute apart."""
    return [
        FakeMail(1, set(), "27-Sep-2026 11:20:00 +0000", header(
            'From: "Backup Server" <backups@nas.example.com>',
            "Subject: =?UTF-8?Q?Backup_f=C3=BCr_Pr=C3=BCfstand_fertig?=",
            "Date: Sun, 27 Sep 2026 09:15:00 +0200")),
        FakeMail(2, {"\\Seen"}, "27-Sep-2026 11:21:00 +0000", header(
            "From: alerts@ups.example.com",
            "Subject: =?ISO-8859-1?Q?Stromausfall_=FCberbr=FCckt?=",
            "Date: Sun, 27 Sep 2026 08:00:00 +0000")),
        FakeMail(3, set(), "27-Sep-2026 11:22:00 +0000", header(
            "From: =?UTF-8?B?WsOkaGxlcnN0YW5kIEJvdA==?= <meter@home.example.com>",
            "Subject: Monthly reading",
            "Date: Sat, 26 Sep 2026 22:30:00 +0200")),
        FakeMail(4, set(), "27-Sep-2026 11:23:00 +0000", header(
            "From: <printer@office.example.com>",
            "Subject: =?UTF-8?Q?Broken_=FF_byte?=",
            "Date: not a date at all")),
        FakeMail(5, set(), "27-Sep-2026 11:24:00 +0000", header("From: nobody@example.com")),
        FakeMail(6, {"\\Flagged", "\\Seen"}, "27-Sep-2026 11:25:00 +0000", header(
            'From: "Watchdog" <watchdog@example.com>',
            "Subject: =?UTF-8?Q?A_rather_long_subject_that_the_server_may_fold_over_?=",
            " =?UTF-8?Q?two_lines_=E2=9C=93?=",
            "Date: Sun, 27 Sep 2026 10:05:00 +0200")),
    ]


def dovecot_folders() -> list[FakeFolder]:
    return [
        FakeFolder(b"Empty", ("\\HasNoChildren",)),
        FakeFolder(CHECKS_WIRE, ("\\HasNoChildren",), [
            FakeMail(1, {"\\Seen"}, "27-Sep-2026 11:26:00 +0000", header("From: checks@example.com", "Subject: Check passed")),
            FakeMail(2, set(), "27-Sep-2026 11:27:00 +0000", header("From: checks@example.com", "Subject: Check failed")),
        ]),
        FakeFolder(b"Reports", ("\\HasChildren",), [
            FakeMail(1, set(), "27-Sep-2026 11:19:00 +0000", header("From: reports@example.com", "Subject: Weekly disk report"))]),
        FakeFolder(b"Reports/Daily", ("\\HasNoChildren",)),
        FakeFolder(b"Drafts", ("\\HasNoChildren", "\\Drafts")),
        FakeFolder(b"Junk", ("\\HasNoChildren", "\\Junk")),
        FakeFolder(b"Sent", ("\\HasNoChildren", "\\Sent")),
        FakeFolder(b"Trash", ("\\HasNoChildren", "\\Trash")),
        FakeFolder(b"Archive", ("\\HasNoChildren", "\\Archive")),
        FakeFolder(b"INBOX", ("\\HasNoChildren",), inbox_mails()),
    ]


def stalwart_folders() -> list[FakeFolder]:
    """⚠️ Stalwart names its special folders the Outlook way; only the attribute says what they are."""
    by_name = {one.wire: one for one in dovecot_folders()}
    return [
        FakeFolder(b"Deleted Items", ("\\Trash",)),
        FakeFolder(b"Drafts", ("\\Drafts",)),
        by_name[b"Empty"], by_name[b"INBOX"],
        FakeFolder(b"Junk Mail", ("\\Junk",)),
        by_name[CHECKS_WIRE], by_name[b"Reports"], by_name[b"Reports/Daily"],
        FakeFolder(b"Sent Items", ("\\Sent",)),
    ]


class FakeImap:
    """Answers the way the live servers did; keeps flags and writes down every command it got."""

    def __init__(self, *, greeting: bytes = DOVECOT_GREETING, signed_in: bytes = DOVECOT_SIGNED_IN,
                 folders: list[FakeFolder] | None = None, quote_all: bool = False, flags_last: bool = False,
                 starttls: ssl.SSLContext | None = None, after_tls: bytes = DOVECOT_AFTER_TLS,
                 login_reply: bytes = b"", capability: bytes | None = None) -> None:
        self.greeting = greeting
        self.signed_in = signed_in
        self.folders = folders if folders is not None else dovecot_folders()
        self.quote_all = quote_all
        self.flags_last = flags_last
        self.starttls = starttls
        self.after_tls = after_tls
        self.login_reply = login_reply
        self.capability = capability
        self.seen: list[bytes] = []
        self.selected: FakeFolder | None = None
        self.writable = False

    def flags(self) -> dict[bytes, list[tuple[int, frozenset[str]]]]:
        return {one.wire: [(mail.uid, frozenset(mail.flags)) for mail in one.mails] for one in self.folders}

    def name(self, folder: FakeFolder) -> bytes:
        if self.quote_all or b" " in folder.wire:
            return b'"' + folder.wire + b'"'
        return folder.wire

    def find(self, raw: bytes) -> FakeFolder | None:
        wanted = raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\") if raw.startswith(b'"') else raw
        return next((one for one in self.folders if one.wire == wanted
                     or (wanted.upper() == b"INBOX" and one.wire == b"INBOX")), None)

    async def read_command(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bytes:
        line = await reader.readuntil(b"\r\n")
        whole = b""
        while True:
            literal = re.search(rb"\{(\d+)(\+?)\}\r\n$", line)
            if not literal:
                whole += line[:-2]
                return whole
            if not literal.group(2):
                writer.write(b"+ OK\r\n")
                await writer.drain()
            whole += line[: literal.start()] + b"{" + await reader.readexactly(int(literal.group(1))) + b"}"
            line = await reader.readuntil(b"\r\n")

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(self.greeting + b"\r\n")
        await writer.drain()
        while True:
            command = await self.read_command(reader, writer)
            self.seen.append(command)
            tag, _, rest = command.partition(b" ")
            verb = rest.split(b" ", 1)[0].upper()
            if verb == b"UID":
                verb = b"UID " + rest.split(b" ", 2)[1].upper()
            answer = await self.answer(tag, verb, rest, writer)
            if answer is None:
                return
            writer.write(answer)
            await writer.drain()

    async def answer(self, tag: bytes, verb: bytes, rest: bytes, writer: asyncio.StreamWriter) -> bytes | None:
        if verb == b"CAPABILITY":
            listed = self.capability or re.search(rb"\[CAPABILITY ([^\]]+)\]", self.greeting + b"[CAPABILITY ]")[1]
            return b"* CAPABILITY " + listed + b"\r\n" + tag + b" OK Capability completed.\r\n"
        if verb == b"STARTTLS":
            if self.starttls is None:
                return tag + b" BAD Error in IMAP command STARTTLS: Unknown command.\r\n"
            writer.write(tag + b" OK Begin TLS negotiation now.\r\n")
            await writer.drain()
            await writer.start_tls(self.starttls)
            self.capability = self.after_tls
            return b""
        if verb == b"LOGIN":
            if self.login_reply:
                return tag + b" " + self.login_reply + b"\r\n"
            if rest in (b'LOGIN "%s" "%s"' % (USER.encode(), PASSWORD.encode()),):
                return tag + b" OK [CAPABILITY " + self.signed_in + b"] Logged in\r\n"
            return tag + b" NO [AUTHENTICATIONFAILED] Authentication failed.\r\n"
        if verb == b"LOGOUT":
            writer.write(b"* BYE Logging out\r\n" + tag + b" OK Logout completed.\r\n")
            await writer.drain()
            writer.close()
            return None
        if verb == b"LIST":
            counted = b"RETURN" in rest
            lines = b""
            for one in self.folders:
                lines += b"* LIST (" + b" ".join(a.encode() for a in one.attributes) + b') "/" ' + self.name(one) + b"\r\n"
                if counted and b"\\Noselect" not in one.attributes:
                    lines += b"* STATUS " + self.name(one) + b" (MESSAGES %d UNSEEN %d)\r\n" % self.numbers(one)
            return lines + tag + b" OK List completed.\r\n"
        if verb == b"STATUS":
            folder = self.find(self.argument(rest))
            if folder is None:
                return tag + b" NO [NONEXISTENT] Mailbox doesn't exist.\r\n"
            return (b"* STATUS " + self.name(folder) + b" (MESSAGES %d UNSEEN %d)\r\n" % self.numbers(folder)
                    + tag + b" OK Status completed.\r\n")
        if verb in (b"EXAMINE", b"SELECT"):
            folder = self.find(self.argument(rest))
            if folder is None:
                return tag + b" NO [NONEXISTENT] Mailbox doesn't exist.\r\n"
            self.selected, self.writable = folder, verb == b"SELECT"
            state = b"READ-WRITE" if self.writable else b"READ-ONLY"
            return (b"* FLAGS (\\Answered \\Flagged \\Deleted \\Seen \\Draft)\r\n* %d EXISTS\r\n* 0 RECENT\r\n"
                    b"* OK [UIDVALIDITY 1790500001] UIDs valid\r\n" % len(folder.mails)
                    + tag + b" OK [" + state + b"] Done.\r\n")
        if verb == b"UID SEARCH" and self.selected is not None:
            unseen = [mail.uid for mail in self.selected.mails if "\\Seen" not in mail.flags]
            return b"* SEARCH" + b"".join(b" %d" % uid for uid in unseen) + b"\r\n" + tag + b" OK Search completed.\r\n"
        if verb in (b"FETCH", b"UID FETCH") and self.selected is not None:
            return self.fetch(tag, verb, rest)
        return tag + b" BAD Unknown command.\r\n"

    @staticmethod
    def argument(rest: bytes) -> bytes:
        match = re.match(rb'\S+ ("(?:[^"\\]|\\.)*"|\S+)', rest)
        return match[1] if match else b""

    @staticmethod
    def numbers(folder: FakeFolder) -> tuple[int, int]:
        return len(folder.mails), sum(1 for mail in folder.mails if "\\Seen" not in mail.flags)

    def fetch(self, tag: bytes, verb: bytes, rest: bytes) -> bytes:
        assert self.selected is not None
        words = rest.split(b" ", 3 if verb == b"UID FETCH" else 2)
        wanted, items = (words[2], words[3]) if verb == b"UID FETCH" else (words[1], words[2])
        mails = self.selected.mails
        if verb == b"UID FETCH":
            uids = {int(one) for one in wanted.split(b",")}
            picked = [(index, mail) for index, mail in enumerate(mails, start=1) if mail.uid in uids]
        else:
            low, _, high = wanted.partition(b":")
            picked = [(index, mail) for index, mail in enumerate(mails, start=1) if int(low) <= index <= int(high or low)]
        out = b""
        for index, mail in picked:
            if FIELDS in items and self.writable:
                # ⚠️ What Dovecot does: BODY[...] without PEEK on a selected folder marks the mail read.
                mail.flags.add("\\Seen")
            flags = b"FLAGS (" + b" ".join(flag.encode() for flag in sorted(mail.flags)) + b")"
            parts = [b"UID %d" % mail.uid]
            if not self.flags_last:
                parts.append(flags)
            if mail.arrived:
                parts.append(b'INTERNALDATE "' + mail.arrived.encode() + b'"')
            parts.append(FIELDS + b" {%d}\r\n" % len(mail.header) + mail.header)
            if self.flags_last:
                parts.append(flags)
            out += b"* %d FETCH (" % index + b" ".join(parts) + b")\r\n"
        return out + tag + b" OK Fetch completed.\r\n"


Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


class Listening:
    """A TCP server on 127.0.0.1 for as long as the block runs, with TLS from the first byte when given."""

    def __init__(self, handler: Handler, tls: ssl.SSLContext | None = None) -> None:
        self.handler = handler
        self.tls = tls
        self.port = 0

    async def __aenter__(self) -> Listening:
        async def guarded(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await self.handler(reader, writer)
            except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError, asyncio.LimitOverrunError):
                pass

        self.server = await asyncio.start_server(guarded, "127.0.0.1", 0, ssl=self.tls)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.server.close()


def config(port: int, security: str = "none", **more: Any) -> dict[str, Any]:
    return {"host": "127.0.0.1", "port": port, "security": security, "username": USER, "password": PASSWORD, **more}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imap, "TIMEOUT", 0.4)
    monkeypatch.setattr(imap, "LOGIN_TIMEOUT", 0.4)


@pytest.fixture(scope="session")
def certificate(tmp_path_factory: pytest.TempPathFactory) -> ssl.SSLContext:
    """A self-signed certificate for 127.0.0.1, made for this run, never written into the repository."""
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "imap.example.com")])
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    folder: Path = tmp_path_factory.mktemp("imap-tls")
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "cert.pem", folder / "key.pem")
    return context


def rows(card: Any) -> list[tuple[Any, ...]]:
    return [(row["title"], row.get("subtitle"), row.get("value"), row.get("status")) for row in card.items]


# -- the cards -------------------------------------------------------------------------


@pytest.mark.parametrize("flavour", ["dovecot", "stalwart"])
async def test_the_unread_card_counts_the_inbox_by_default(ctx: Context, flavour: str) -> None:
    server = FakeImap(greeting=STALWART_GREETING, signed_in=STALWART_SIGNED_IN, folders=stalwart_folders(),
                      quote_all=True) if flavour == "stalwart" else FakeImap()
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("unread", config(listening.port), {}, ctx)
    assert card.status == "ok"
    assert card.primary == {"label": "Unread", "value": 4}
    assert rows(card) == [("Inbox", "6 messages", 4, "ok")]
    assert card.metrics == {"unread": 4.0} and card.meta["headline"] is True
    # ⚠️ STATUS asks without opening the folder at all.
    assert [one.split(b" ", 1)[1] for one in server.seen if b"STATUS" in one] == [b"STATUS INBOX (MESSAGES UNSEEN)"]


async def test_the_unread_card_with_picked_folders_and_one_gone(ctx: Context) -> None:
    server = FakeImap()
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("unread", config(listening.port), {"folders": ["INBOX", CHECKS, "Empty", "Nowhere"]}, ctx)
    assert rows(card) == [
        ("Inbox", "6 messages", 4, "ok"),
        (CHECKS, "2 messages", 1, "ok"),
        ("Empty", "0 messages", 0, "ok"),
        ("Nowhere", "Not found on the server", 0, "bad"),
    ]
    assert card.primary["value"] == 5 and card.status == "warn" and card.meta["notice"]
    # ⚠️ The umlaut goes out in modified UTF-7, not in UTF-8.
    assert any(b'STATUS "Pr&APw-fungen" (MESSAGES UNSEEN)' in one for one in server.seen)


@pytest.mark.parametrize("flavour", ["dovecot", "stalwart"])
async def test_the_latest_card_decodes_every_header(ctx: Context, flavour: str) -> None:
    # Stalwart quotes every name; FLAGS after the literal tries the parser on the other order.
    server = FakeImap(greeting=STALWART_GREETING, signed_in=STALWART_SIGNED_IN, folders=stalwart_folders(),
                      quote_all=True, flags_last=True) if flavour == "stalwart" else FakeImap()
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("latest", config(listening.port), {"limit": 10}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row["emphasis"]) for row in card.items] == [
        ("Watchdog", "A rather long subject that the server may fold over two lines \u2713", "unknown", False),
        # No subject at all, and a From with nothing but an address.
        ("nobody@example.com", "(no subject)", "ok", True),
        # ⚠️ A byte that is no UTF-8 inside an encoded word: replaced, the rest kept.
        ("printer@office.example.com", "Broken \ufffd byte", "ok", True),
        # The display name itself base64 encoded.
        ("Z\u00e4hlerstand Bot", "Monthly reading", "ok", True),
        # ISO-8859-1 in the subject.
        ("alerts@ups.example.com", "Stromausfall \u00fcberbr\u00fcckt", "unknown", False),
        ("Backup Server", "Backup f\u00fcr Pr\u00fcfstand fertig", "ok", True),
    ]
    assert all(re.fullmatch(r"\d+ (min|h|d)", row["value"]) for row in card.items)
    assert card.meta["empty"] == "No mail in the folder."


async def test_only_unread_takes_the_newest_unread_by_uid(ctx: Context) -> None:
    server = FakeImap()
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("latest", config(listening.port), {"limit": 2, "unread_only": True}, ctx)
    assert [row["title"] for row in card.items] == ["nobody@example.com", "printer@office.example.com"]
    fetches = [one.split(b" ", 1)[1] for one in server.seen if b"FETCH" in one]
    assert fetches == [b"UID FETCH 4,5 " + imap.FETCH_ITEMS]
    assert any(one.endswith(b"UID SEARCH UNSEEN") for one in server.seen)


async def test_the_newest_mails_are_the_last_sequence_numbers(ctx: Context) -> None:
    server = FakeImap()
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("latest", config(listening.port), {"limit": 3}, ctx)
    assert [row["title"] for row in card.items] == ["Watchdog", "nobody@example.com", "printer@office.example.com"]
    assert [one.split(b" ", 1)[1] for one in server.seen if b"FETCH" in one] == [b"FETCH 4:6 " + imap.FETCH_ITEMS]


async def test_several_folders_mix_by_arrival_and_name_the_folder(ctx: Context) -> None:
    server = FakeImap()
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("latest", config(listening.port),
                                   {"folders": ["INBOX", CHECKS, "Reports", "Nowhere"], "limit": 4}, ctx)
    assert [row["subtitle"] for row in card.items] == [
        f"Check failed \u00b7 {CHECKS}", f"Check passed \u00b7 {CHECKS}",
        "A rather long subject that the server may fold over two lines \u2713 \u00b7 Inbox", "(no subject) \u00b7 Inbox"]
    # One of four is gone: said, and the others still shown.
    assert card.status == "warn" and card.meta["notice"]


async def test_a_folder_that_is_gone_or_empty(ctx: Context) -> None:
    server = FakeImap()
    async with Listening(server) as listening:
        empty = await ADAPTER.fetch("latest", config(listening.port), {"folders": ["Empty"]}, ctx)
        unread = await ADAPTER.fetch("latest", config(listening.port), {"folders": ["Empty"], "unread_only": True}, ctx)
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.fetch("latest", config(listening.port), {"folders": ["Nowhere"]}, ctx)
    assert empty.items == [] and empty.meta["empty"] == "No mail in the folder."
    assert unread.items == [] and unread.meta["empty"] == "No unread mail."
    assert caught.value.code == "imap_no_folder" and "Nowhere" in caught.value.message


async def test_nothing_is_ever_marked_read(ctx: Context) -> None:
    """⚠️ EXAMINE and BODY.PEEK, and no command that could change anything."""
    server = FakeImap()
    before = server.flags()
    async with Listening(server) as listening:
        for kind, options in (("unread", {"folders": ["INBOX", CHECKS]}), ("latest", {"limit": 20}),
                              ("latest", {"unread_only": True, "folders": ["INBOX", CHECKS, "Reports"]}),
                              ("folders", {"special": True})):
            await ADAPTER.fetch(kind, config(listening.port), options, ctx)
        await ADAPTER.test(config(listening.port), ctx)
    assert server.flags() == before
    verbs = {one.split(b" ")[1].upper() for one in server.seen}
    assert b"SELECT" not in verbs and b"EXAMINE" in verbs
    assert verbs <= {b"CAPABILITY", b"LOGIN", b"LIST", b"STATUS", b"EXAMINE", b"UID", b"FETCH", b"LOGOUT"}
    fetches = [one for one in server.seen if b"FETCH" in one]
    assert fetches and all(one.endswith(b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])") for one in fetches)
    everything = b"\n".join(server.seen).upper()
    for changing in (b" BODY[", b"RFC822", b"STORE", b"EXPUNGE", b"COPY", b"MOVE", b"APPEND", b"CREATE", b"DELETE"):
        assert changing not in everything, changing


async def test_the_fake_would_notice_a_fetch_that_marks_read(ctx: Context) -> None:
    """The counter-proof of the one above: Dovecot sets \\Seen on BODY[...] in a selected folder."""
    server = FakeImap()
    async with Listening(server) as listening:
        reader, writer = await asyncio.open_connection("127.0.0.1", listening.port)
        await reader.readline()
        for line in (b'a1 LOGIN "%s" "%s"' % (USER.encode(), PASSWORD.encode()), b"a2 SELECT INBOX",
                     b"a3 FETCH 1 (" + FIELDS + b")"):
            writer.write(line + b"\r\n")
            await writer.drain()
            while not (await reader.readline()).startswith(line[:3]):
                pass
        writer.close()
    assert "\\Seen" in server.folders[-1].mails[0].flags


@pytest.mark.parametrize("flavour", ["dovecot", "stalwart"])
async def test_the_folder_card_knows_special_folders_by_their_attribute(ctx: Context, flavour: str) -> None:
    server = FakeImap(greeting=STALWART_GREETING, signed_in=STALWART_SIGNED_IN, folders=stalwart_folders(),
                      quote_all=True) if flavour == "stalwart" else FakeImap()
    async with Listening(server) as listening:
        plain = await ADAPTER.fetch("folders", config(listening.port), {}, ctx)
        special = await ADAPTER.fetch("folders", config(listening.port), {"special": True}, ctx)
        unread = await ADAPTER.fetch("folders", config(listening.port), {"only_unread": True}, ctx)
    assert rows(plain) == [
        ("Inbox", "6 messages", 4, "ok"), ("Empty", "0 messages", 0, "ok"), (CHECKS, "2 messages", 1, "ok"),
        ("Reports", "1 message", 1, "ok"), ("Reports/Daily", "0 messages", 0, "ok")]
    words = {row["title"]: row["subtitle"] for row in special.items}
    if flavour == "stalwart":
        # ⚠️ "Deleted Items", "Junk Mail" and "Sent Items": recognised by \Trash, \Junk and \Sent.
        assert words["Deleted Items"] == "Trash \u00b7 0 messages" and words["Junk Mail"] == "Junk \u00b7 0 messages"
        assert words["Sent Items"] == "Sent \u00b7 0 messages"
    else:
        assert words["Archive"] == "Archive \u00b7 0 messages" and words["Trash"] == "Trash \u00b7 0 messages"
    assert [row["title"] for row in unread.items] == ["Inbox", CHECKS, "Reports"]
    # With LIST-STATUS one command answers for every folder.
    assert not [one for one in server.seen if one.split(b" ")[1] == b"STATUS"]
    assert [one for one in server.seen if b"LIST" in one][-1].endswith(b"RETURN (SPECIAL-USE STATUS (MESSAGES UNSEEN))")


async def test_a_server_without_list_status_is_asked_folder_by_folder(ctx: Context) -> None:
    folders = [*dovecot_folders(), FakeFolder(b"[Gmail]", ("\\Noselect", "\\HasChildren"))]
    server = FakeImap(greeting=OLD_GREETING, capability=OLD_CAPABILITIES, signed_in=OLD_CAPABILITIES, folders=folders)
    async with Listening(server) as listening:
        card = await ADAPTER.fetch("folders", config(listening.port), {"special": True}, ctx)
        choices = await ADAPTER.choices("folders", config(listening.port), ctx)
    statuses = [one for one in server.seen if one.split(b" ")[1] == b"STATUS"]
    # One STATUS per folder that can be opened; [Gmail] is \Noselect and asked about by nobody.
    assert len(statuses) == 10 and not any(b"Gmail" in one for one in statuses)
    assert "[Gmail]" not in {row["title"] for row in card.items}
    assert choices[0] == ("INBOX", "Inbox") and (CHECKS, CHECKS) in choices and len(choices) == 10


async def test_the_test_button(ctx: Context) -> None:
    async with Listening(FakeImap()) as listening:
        said = await ADAPTER.test(config(listening.port, "none"), ctx)
    assert said.startswith("Signed in. The inbox holds 6 messages, 4 of them unread.")
    # ⚠️ Said out loud, every time the button is pressed.
    assert "The password crossed the network unencrypted." in said


# -- signing in ------------------------------------------------------------------------


@pytest.mark.parametrize("reply, message", [
    (b"NO [AUTHENTICATIONFAILED] Authentication failed.", "The server rejected the user name or the password."),
    (b"NO LOGIN failed.", "The server rejected the user name or the password."),
    # Made up in the shape Gmail uses: an ALERT is meant for a person, so it is passed on.
    (b"NO [ALERT] Application-specific password required (Failure)",
     "The server rejected the sign-in: Application-specific password required (Failure)"),
])
async def test_a_rejected_password_names_app_passwords(ctx: Context, reply: bytes, message: str) -> None:
    async with Listening(FakeImap(login_reply=reply)) as listening:
        with pytest.raises(AuthFailed) as caught:
            await ADAPTER.fetch("unread", config(listening.port), {}, ctx)
    assert caught.value.code == "auth_failed" and caught.value.message == message
    assert "app password" in caught.value.hint and "Microsoft 365" in caught.value.hint


async def test_a_slow_refusal_is_still_a_refusal(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Dovecot answered the second wrong password in a row after 5.5 s: LOGIN waits longer than the rest."""
    monkeypatch.setattr(imap, "TIMEOUT", 0.3)
    monkeypatch.setattr(imap, "LOGIN_TIMEOUT", 3.0)

    async def slow(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(DOVECOT_GREETING + b"\r\n")
        await writer.drain()
        tag = (await reader.readline()).split(b" ")[0]
        await asyncio.sleep(0.8)
        writer.write(tag + b" NO [AUTHENTICATIONFAILED] Authentication failed.\r\n")
        await writer.drain()
        await asyncio.sleep(0.5)

    async with Listening(slow) as listening:
        with pytest.raises(AuthFailed):
            await ADAPTER.test(config(listening.port), ctx)


async def test_the_wrong_password_against_the_fake(ctx: Context) -> None:
    async with Listening(FakeImap()) as listening:
        with pytest.raises(AuthFailed):
            await ADAPTER.test({**config(listening.port), "password": "wrong-password-for-the-test"}, ctx)


@pytest.mark.parametrize("greeting", [DOVECOT_143, STALWART_143])
async def test_logindisabled_keeps_the_password_at_home(ctx: Context, greeting: bytes) -> None:
    """⚠️ Dovecot answers a LOGIN sent anyway with "the password was exposed"."""
    server = FakeImap(greeting=greeting)
    async with Listening(server) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port, "none"), ctx)
    assert caught.value.code == "imap_login_disabled"
    assert not any(b"LOGIN" in one or PASSWORD.encode() in one for one in server.seen)


async def test_logindisabled_asked_for_when_the_greeting_does_not_say(ctx: Context) -> None:
    server = FakeImap(greeting=OLD_GREETING, capability=b"IMAP4rev1 STARTTLS LOGINDISABLED")
    async with Listening(server) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port, "none"), ctx)
    assert caught.value.code == "imap_login_disabled"
    assert [one.split(b" ", 1)[1] for one in server.seen] == [b"CAPABILITY"]


async def test_starttls_that_is_not_offered_keeps_the_password_at_home(ctx: Context) -> None:
    # The unencrypted Dovecot: no STARTTLS in the greeting.
    server = FakeImap()
    async with Listening(server) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port, "starttls"), ctx)
    assert caught.value.code == "imap_no_starttls"
    assert server.seen == []


async def test_starttls_then_the_capabilities_again(ctx: Context, certificate: ssl.SSLContext) -> None:
    server = FakeImap(greeting=DOVECOT_143, starttls=certificate)
    async with Listening(server) as listening:
        said = await ADAPTER.test(config(listening.port, "starttls", insecure=True), ctx)
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port, "starttls", insecure=False), ctx)
    assert said == "Signed in. The inbox holds 6 messages, 4 of them unread."
    verbs = [one.split(b" ", 1)[1].split(b" ")[0] for one in server.seen]
    # What was said before TLS counts for nothing after it: LOGINDISABLED was in it.
    assert verbs[:4] == [b"STARTTLS", b"CAPABILITY", b"LOGIN", b"STATUS"]
    assert caught.value.code == "tls_untrusted" and "self-signed" in caught.value.message


async def test_tls_from_the_first_byte(ctx: Context, certificate: ssl.SSLContext) -> None:
    async with Listening(FakeImap(), tls=certificate) as listening:
        card = await ADAPTER.fetch("unread", config(listening.port, "tls", insecure=True), {}, ctx)
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.fetch("unread", config(listening.port, "tls"), {}, ctx)
    assert card.primary["value"] == 4
    assert caught.value.code == "tls_untrusted"
    assert "Ignore TLS errors" in caught.value.hint


async def test_tls_against_a_port_without_it(ctx: Context) -> None:
    async with Listening(FakeImap(greeting=DOVECOT_143)) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port, "tls"), ctx)
    assert caught.value.code == "tls_failed" and "does not speak TLS" in caught.value.message


async def test_a_starttls_answer_with_something_behind_it_is_refused(ctx: Context) -> None:
    """⚠️ STARTTLS response injection: bytes sent before the handshake must not count as encrypted."""

    async def injecting(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(DOVECOT_143 + b"\r\n")
        await writer.drain()
        line = await reader.readline()
        tag = line.split(b" ")[0]
        writer.write(tag + b" OK Begin TLS negotiation now.\r\n* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n")
        await writer.drain()
        await asyncio.sleep(1)

    async with Listening(injecting) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port, "starttls"), ctx)
    assert caught.value.code == "tls_failed" and "before the handshake" in caught.value.message


async def test_awkward_passwords_travel_whole(ctx: Context) -> None:
    """Quotes and backslashes quoted; non-ASCII as a literal, waiting for "+" where LITERAL+ is missing."""
    seen: list[bytes] = []
    for password, greeting in (('pass "with" \\ quotes', DOVECOT_GREETING), ("p\u00e4ss-w\u00f6rd", OLD_GREETING),
                               ("p\u00e4ss-w\u00f6rd", DOVECOT_GREETING)):
        server = FakeImap(greeting=greeting, capability=OLD_CAPABILITIES if greeting == OLD_GREETING else None,
                          login_reply=b"NO [AUTHENTICATIONFAILED] Authentication failed.")
        async with Listening(server) as listening:
            with pytest.raises(AuthFailed):
                await ADAPTER.test({**config(listening.port), "password": password}, ctx)
        seen += [one for one in server.seen if b"LOGIN" in one]
    assert seen[0].endswith(b'LOGIN "cards@example.com" "pass \\"with\\" \\\\ quotes"')
    assert seen[1].endswith(b'LOGIN "cards@example.com" {' + "p\u00e4ss-w\u00f6rd".encode() + b"}")
    assert seen[2].split(b" ", 1)[1] == seen[1].split(b" ", 1)[1]


# -- when it does not work -------------------------------------------------------------


async def test_nothing_on_the_port(ctx: Context) -> None:
    with pytest.raises(Unreachable, match="Nothing answers"):
        await ADAPTER.test(config(free_port()), ctx)


async def test_an_address_nobody_answers_at(ctx: Context, quick: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(5)

    monkeypatch.setattr(imap.asyncio, "open_connection", never)
    with pytest.raises(Unreachable):
        await asyncio.wait_for(ADAPTER.fetch("unread", config(993), {}, ctx), 3)


async def test_a_port_that_says_nothing(ctx: Context, quick: None) -> None:
    # A web server waits for a request: no greeting ever comes.
    async def mute(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(3)

    async def hang_up(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    for handler in (mute, hang_up):
        async with Listening(handler) as listening:
            with pytest.raises(AdapterError) as caught:
                await asyncio.wait_for(ADAPTER.test(config(listening.port), ctx), 3)
        assert caught.value.code == "imap_no_greeting"


@pytest.mark.parametrize("reply", [
    b"SSH-2.0-OpenSSH_9.2p1\r\n",
    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n",
    b"* NO not ready\r\n",
    b"+OK POP3 server ready\r\n",
])
async def test_another_service_on_the_port(ctx: Context, reply: bytes) -> None:
    async def other(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(reply)
        await writer.drain()
        await asyncio.sleep(0.5)

    async with Listening(other) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port), ctx)
    assert caught.value.code == "not_imap"


async def test_a_server_that_stops_answering_after_the_greeting(ctx: Context, quick: None) -> None:
    async def greets(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(DOVECOT_GREETING + b"\r\n")
        await writer.drain()
        await asyncio.sleep(3)

    async with Listening(greets) as listening:
        with pytest.raises(AdapterError) as caught:
            await asyncio.wait_for(ADAPTER.test(config(listening.port), ctx), 3)
    assert caught.value.code == "imap_timeout"


async def test_a_trickle_does_not_stretch_the_deadline(ctx: Context, quick: None) -> None:
    """One byte at a time keeps a per-read timeout alive for ever; the deadline is per answer."""

    async def trickle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(DOVECOT_GREETING + b"\r\n")
        await writer.drain()
        tag = (await reader.readline()).split(b" ")[0]
        for byte in b"* CAPABILITY " + b"X" * 40:
            writer.write(bytes([byte]))
            await writer.drain()
            await asyncio.sleep(0.05)
        writer.write(b"\r\n" + tag + b" OK done\r\n")

    async with Listening(trickle) as listening:
        with pytest.raises(AdapterError) as caught:
            await asyncio.wait_for(ADAPTER.test(config(listening.port), ctx), 4)
    assert caught.value.code == "imap_timeout"


async def test_bye_in_the_middle(ctx: Context) -> None:
    async def leaves(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(DOVECOT_GREETING + b"\r\n")
        await writer.drain()
        await reader.readline()
        writer.write(b"* BYE Server shutting down.\r\n")
        await writer.drain()
        writer.close()

    async with Listening(leaves) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port), ctx)
    assert caught.value.code == "imap_closed" and caught.value.hint == "Server shutting down."


async def test_a_literal_beyond_reason_is_refused(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imap, "MAX_LITERAL", 64)

    async def huge(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(DOVECOT_GREETING + b"\r\n")
        await writer.drain()
        tag = (await reader.readline()).split(b" ")[0]
        writer.write(b"* CAPABILITY {100}\r\n" + b"X" * 100 + b"\r\n" + tag + b" OK\r\n")
        await writer.drain()
        await asyncio.sleep(0.5)

    async with Listening(huge) as listening:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(config(listening.port), ctx)
    assert caught.value.code == "answer_too_large"


# -- the pieces ------------------------------------------------------------------------


@pytest.mark.parametrize("name, wire", [
    ("INBOX", b"INBOX"),
    (CHECKS, CHECKS_WIRE),
    ("Entw\u00fcrfe", b"Entw&APw-rfe"),
    ("Tom & Jerry", b"Tom &- Jerry"),
    ("\u65e5\u672c\u8a9e", b"&ZeVnLIqe-"),
    ("R\u00e9sum\u00e9s/\u00c9t\u00e9", b"R&AOk-sum&AOk-s/&AMk-t&AOk-"),
    ("Mail \U0001F4EC", b"Mail &2D3c7A-"),
    ("~peter/mail/&stuff", b"~peter/mail/&-stuff"),
    # A comma where base64 has a slash.
    ("\u00ff\u00fe", b"&AP8A,g-"),
])
def test_folder_names_in_modified_utf7(name: str, wire: bytes) -> None:
    assert imap.encode_folder(name) == wire
    assert imap.decode_folder(wire) == name


def test_broken_folder_names_are_shown_as_they_came() -> None:
    assert imap.decode_folder(b"Odd&-name") == "Odd&name"
    # An unfinished shift, and one that is no base64 of UTF-16.
    assert imap.decode_folder(b"Half&APw") == "Half&APw"
    assert imap.decode_folder(b"Bad&!!-x") == "Bad&!!-x"
    # ⚠️ Raw UTF-8 from a server that switched on UTF8=ACCEPT by itself.
    assert imap.decode_folder("Entw\u00fcrfe".encode()) == "Entw\u00fcrfe"
    assert imap.folder_argument("inbox") == b"INBOX"
    assert imap.folder_argument('A "quoted" name') == b'"A \\"quoted\\" name"'
    for broken in ("", "two\r\nlines", "x" * 1001):
        with pytest.raises(AdapterError):
            imap.folder_argument(broken)


@pytest.mark.parametrize("raw, text", [
    ("=?UTF-8?Q?Backup_f=C3=BCr_Pr=C3=BCfstand_fertig?=", "Backup f\u00fcr Pr\u00fcfstand fertig"),
    ("=?ISO-8859-1?Q?Stromausfall_=FCberbr=FCckt?=", "Stromausfall \u00fcberbr\u00fcckt"),
    ("=?utf-8?b?WsOkaGxlcnN0YW5kIEJvdA==?=", "Z\u00e4hlerstand Bot"),
    ("=?windows-1252?Q?=80_100?=", "\u20ac 100"),
    ("Re: =?UTF-8?Q?Caf=C3=A9?= news", "Re: Caf\u00e9 news"),
    ("=?UTF-8?Q?one_?= =?UTF-8?Q?two?=", "one two"),
    ("=?UTF-8?Q?Broken_=FF_byte?=", "Broken \ufffd byte"),
    ("=?x-no-such-charset?Q?plain_text?=", "plain text"),
    ("=?UTF-8?B?!!!!?=", "=?UTF-8?B?!!!!?="),
    ("tabs\tand\r\n  folds", "tabs and folds"),
    ("plain", "plain"),
])
def test_encoded_words(raw: str, text: str) -> None:
    assert imap.decode_words(raw) == text


def test_header_blocks_raw_eight_bit_and_long_lines() -> None:
    block = ("Subject: Stra\u00dfe gesperrt\r\nFrom: a@example.com\r\n").encode() + b"Date: x\r\nX-Junk: \xff\r\n\r\n"
    fields = imap.header_fields(block)
    assert fields["subject"] == "Stra\u00dfe gesperrt" and fields["from"] == "a@example.com"
    # Not UTF-8: taken as Windows-1252.
    assert imap.header_fields(b"Subject: Caf\xe9\r\n")["subject"] == "Caf\u00e9"
    # Folded, and a second Subject ignored.
    assert imap.header_fields(b"Subject: one\r\n two\r\nSubject: other\r\n")["subject"] == "one two"
    assert imap.decode_words("x" * 400).endswith("\u2026") and len(imap.decode_words("x" * 400)) == 300


@pytest.mark.parametrize("raw, shown", [
    ('"Backup Server" <backups@nas.example.com>', "Backup Server"),
    ("=?UTF-8?B?WsOkaGxlcnN0YW5kIEJvdA==?= <meter@home.example.com>", "Z\u00e4hlerstand Bot"),
    ('"=?UTF-8?Q?M=C3=BCller=2C_Heizung?=" <heat@example.com>', "M\u00fcller, Heizung"),
    ("<printer@office.example.com>", "printer@office.example.com"),
    ("alerts@ups.example.com", "alerts@ups.example.com"),
    ("Undisclosed", "Undisclosed"),
])
def test_senders(raw: str, shown: str) -> None:
    assert imap.sender(raw) == shown


def test_dates() -> None:
    when = dt.datetime(2026, 9, 27, 9, 15, tzinfo=dt.UTC).timestamp()
    assert imap.internal_date(b"27-Sep-2026 11:15:00 +0200") == when
    assert imap.internal_date(b" 7-Sep-2026 09:15:00 +0000") == dt.datetime(2026, 9, 7, 9, 15, tzinfo=dt.UTC).timestamp()
    # ⚠️ The month by a table of its own, never by the locale.
    assert imap.internal_date(b"27-sep-2026 09:15:00 -0100") == when + 3600
    for broken in (b"27-Okt-2026 09:15:00 +0000", b"31-Feb-2026 09:15:00 +0000", b"yesterday"):
        assert imap.internal_date(broken) is None
    assert imap.parse_date("Sun, 27 Sep 2026 11:15:00 +0200") == when
    assert imap.parse_date("not a date at all") is None and imap.parse_date("") is None


def test_arrival_before_the_date_header() -> None:
    """⚠️ Delivered to Stalwart over SMTP: Date said 2000, INTERNALDATE said the minute it came."""
    old_clock = [b"1", b"FETCH", [b"UID", b"7", b"FLAGS", [b"$Junk"], b"INTERNALDATE", b"27-Sep-2026 11:39:00 +0000",
                                   FIELDS, b"Date: Sat, 01 Jan 2000 00:00:00 +0000\r\n\r\n"]]
    mail = imap._mail("INBOX", old_clock)
    assert mail is not None and mail.when == dt.datetime(2026, 9, 27, 11, 39, tzinfo=dt.UTC).timestamp()
    assert mail.unread and mail.sender == "?" and mail.subject == ""
    without = [b"1", b"FETCH", [b"UID", b"7", b"FLAGS", [b"\\Seen"], FIELDS, b"Date: Sat, 01 Jan 2000 00:00:00 +0000\r\n\r\n"]]
    fallback = imap._mail("INBOX", without)
    assert fallback is not None and fallback.when == dt.datetime(2000, 1, 1, tzinfo=dt.UTC).timestamp()
    assert not fallback.unread


def test_the_response_parser() -> None:
    line = b'1 FETCH (UID 1 FLAGS (\\Seen) BODY[HEADER.FIELDS (FROM SUBJECT DATE)] \x000\x00 X NIL "a \\"b\\"")'
    assert imap.tokens(line, [b"From: x\r\n"]) == [
        b"1", b"FETCH", [b"UID", b"1", b"FLAGS", [b"\\Seen"], FIELDS, b"From: x\r\n", b"X", None, b'a "b"']]
    assert imap.tokens(b'LIST () "/" "Deleted Items"', []) == [b"LIST", [], b"/", b"Deleted Items"]
    assert imap.tokens(b"LIST (\\HasNoChildren) NIL Empty", []) == [b"LIST", [b"\\HasNoChildren"], None, b"Empty"]
    # Unbalanced brackets end with the line rather than running on.
    assert imap.tokens(b"A (B C", []) == [b"A", [b"B", b"C"]]
    with pytest.raises(imap.NotImap):
        imap.tokens(b"(" * (imap.MAX_DEPTH + 2), [])
    with pytest.raises(imap.NotImap):
        imap.tokens(b"X \x007\x00", [])


def test_settings_as_people_type_them() -> None:
    assert (imap.settings({"host": "mail.example.com"}).port, imap.settings({"host": "mail.example.com"}).security) == (993, "tls")
    assert imap.settings({"host": "mail.example.com", "security": "starttls"}).port == 143
    assert imap.settings({"host": "mail.example.com", "security": "none"}).port == 143
    assert imap.settings({"host": "imaps://mail.example.com:1993/"}).port == 1993
    assert imap.settings({"host": "mail.example.com:1", "port": 994}).port == 994
    ipv6 = imap.settings({"host": "[2001:db8::7]:993"})
    assert (ipv6.host, ipv6.port) == ("2001:db8::7", 993)
    assert imap.settings({"host": "mail.example.com", "security": "sometimes"}).security == "tls"
    for broken in ({"host": ""}, {"host": "mail.example.com", "port": 70000}, {"host": "mail.example.com", "port": "x"}):
        with pytest.raises(AdapterError):
            imap.settings(broken)
    # The same barred addresses as every other connection.
    with pytest.raises(AdapterError) as caught:
        imap.settings({"host": "169.254.169.254"})
    assert caught.value.code == "forbidden_host"


def test_the_password_field_is_secret_and_no_oauth() -> None:
    fields = {one.name: one for one in ADAPTER.fields}
    assert fields["password"].secret and fields["password"].type == "password"
    assert "Gmail" in fields["password"].help and "Microsoft 365" in fields["password"].help
    assert [value for value, _label in fields["security"].options] == ["tls", "starttls", "none"]
    assert fields["security"].default == "tls" and "in the clear" in fields["security"].help


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for options in ({}, {"folders": ["INBOX", "Alerts", "Gone"], "unread_only": True, "special": True, "only_unread": True}):
        for tick in (0, 7, 300, 3600):
            card = ADAPTER.demo(kind, dict(options), tick)
            assert card.items or card.primary or card.meta.get("empty")
    assert [label for _value, label in ADAPTER.demo_choices("folders")][0] == "Inbox"
