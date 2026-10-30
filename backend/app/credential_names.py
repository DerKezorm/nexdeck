"""Which names of parameters carry a credential: one list for what a card copies and what a log leaves out.

Two lists used to say it twice, differently: the one that decides what a custom card carries from the connection's own request
(``key|token|...`` found anywhere in a name, so that ``keyword``, ``author`` and ``users`` were taken along) and the one that
blanks an address in the log (a handful of exact names, so ``_sid``, ``X-Plex-Token`` and ``ticket`` stayed readable). A name is
now cut into its words (at every sign that is no letter or digit and at camel case) and a credential is a name with one of
these words in it.
"""

from __future__ import annotations

import re

#: The words that make a name a credential. ``apikey`` and ``sessionid`` are words of their own because they are written as one.
CREDENTIAL_WORDS = frozenset({
    "key", "apikey", "token", "accesstoken", "authtoken", "apitoken", "secret", "clientsecret",
    "pass", "passwd", "password", "passphrase", "pwd", "sid", "sessid", "sessionid", "session", "ses",
    "auth", "authorization", "ticket", "signature", "sig", "credential", "credentials", "jwt", "bearer", "cookie",
    "user", "username", "login",
})


def words_of(name: str) -> list[str]:
    """``X-Plex-Token`` is x, plex, token; ``apiKey`` is api, key; ``keyword`` stays one word."""
    return [word.lower() for word in re.split(r"[^A-Za-z0-9]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)) if word]


def is_credential_name(name: str) -> bool:
    found = words_of(name)
    return any(word in CREDENTIAL_WORDS for word in found) or "".join(found) in CREDENTIAL_WORDS


#: Words of a name that say who asks, not what proves it: a login name is no secret.
ONLY_WHO = frozenset({"user", "username", "login"})
#: Parts of a name that make its value grant access wherever they stand, also inside one word (``xapikey``, ``db_passwd``).
ACCESS_PARTS = (
    "apikey", "api_key", "token", "secret", "password", "passwd", "authorization", "cookie", "session", "private_key",
    "client_secret", "access_key",
)  # fmt: skip


def is_access_name(name: str) -> bool:
    """Whether the value under this name grants access: what demo data and the values sent to a provider must not carry.

    A credential by its words in every spelling (``X-Api-Key``, ``privateKey``, ``accessKey``, ``passphrase``, ``pwd``,
    ``auth``), not by a word that only says who asks (``userName``, ``login``), or a name with one of :data:`ACCESS_PARTS` in it.
    ⚠️ One rule for nexdeck's demo data, the card help and the Workshop's check: each had a list of its own, and
    ``X-Api-Key`` or ``privateKey`` went past the list of the demo data (found in a real run on 1.0.1).
    """
    found = words_of(name)
    proving = CREDENTIAL_WORDS - ONLY_WHO
    lowered = name.lower()
    return any(word in proving for word in found) or "".join(found) in proving or any(part in lowered for part in ACCESS_PARTS)


#: A parameter of an address, with the name captured: ``?name=`` or ``&name=``.
QUERY_PARAMETER = re.compile(r"([?&])([A-Za-z0-9_.\-%]+)(=)([^&\s\"']*)")
