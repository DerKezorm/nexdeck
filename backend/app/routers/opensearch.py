"""nexdeck as a search engine of the browser (OpenSearch), with suggestions while somebody types.

The search itself is ``/go?q=`` (``routers/go.py``): a short name opens its
tile, anything else nexdeck's search bar with the words in it. Safari does not
read OpenSearch; there a bookmark of ``/go/<short name>`` does the same.
"""

from __future__ import annotations

from typing import Annotated
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ..deps import DbSession
from ..services import aliases
from ..services import brand as brand_service
from ..services.home_network import public_base
from ..services.public_url import public_url
from .go import MOST_WORDS, viewer

router = APIRouter(tags=["go"])

#: OpenSearch allows sixteen characters for the name a browser lists.
SHORT_NAME = 16


@router.get("/api/v1/go/suggestions", summary="What the address bar offers while somebody types")
def suggest(request: Request, db: DbSession, q: Annotated[str, Query(max_length=MOST_WORDS)] = "") -> Response:
    """OpenSearch suggestions: ``[words, [completions], [descriptions]]``.

    ⚠️ Always an answer and never an error with something in it: without a
    session, held at the door or asked for nothing, the list is empty. A
    browser asks this with every key pressed.
    """
    words = q.strip()
    found: list[tuple[str, str]] = []
    # Held at the door counts as nobody: ``viewer`` hands back neither an account nor a display then.
    user, kiosk, _held = viewer(request, db)
    if words and (user is not None or kiosk is not None):
        found = aliases.suggestions(db, aliases.seen_cards(db, user, kiosk), words)
    return JSONResponse([words, [text for text, _ in found], [about for _, about in found]],
                        media_type="application/x-suggestions+json", headers={"Cache-Control": "no-store"})


def _base(request: Request, db: DbSession) -> str:
    return (public_url(db) or public_base(request)).rstrip("/")


@router.get("/opensearch.xml", include_in_schema=False)
def opensearch(request: Request, db: DbSession) -> Response:
    """The description that lets a browser add nexdeck as a search engine, under the installation's own name and logo."""
    base = _base(request, db)
    brand = brand_service.public(db)
    name = brand["name"] or "nexdeck"
    if brand["app_icons"]:
        image, kind = brand["app_icons"]["192"], "image/png"
    else:
        image, kind = "/icon-192.png", "image/png"
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/" '
        'xmlns:moz="http://www.mozilla.org/2006/browser/search/">\n'
        f"  <ShortName>{escape(name[:SHORT_NAME])}</ShortName>\n"
        f"  <Description>{escape(f'Open the apps and cards of {name}')}</Description>\n"
        "  <InputEncoding>UTF-8</InputEncoding>\n"
        f'  <Image width="192" height="192" type="{kind}">{escape(base + image)}</Image>\n'
        f'  <Url type="text/html" method="get" template={quoteattr(base + "/go?q={searchTerms}")}/>\n'
        f'  <Url type="application/x-suggestions+json" method="get" '
        f"template={quoteattr(base + '/api/v1/go/suggestions?q={searchTerms}')}/>\n"
        f"  <moz:SearchForm>{escape(base + '/')}</moz:SearchForm>\n"
        "</OpenSearchDescription>\n"
    )
    return Response(body, media_type="application/opensearchdescription+xml", headers={"Cache-Control": "no-cache"})
