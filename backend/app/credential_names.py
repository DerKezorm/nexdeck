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


#: A parameter of an address, with the name captured: ``?name=`` or ``&name=``.
QUERY_PARAMETER = re.compile(r"([?&])([A-Za-z0-9_.\-%]+)(=)([^&\s\"']*)")
