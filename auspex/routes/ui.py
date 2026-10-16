"""Minimal dark-first UI shell (S3 step 5).

Serves the pages (their markup, plus the CSS and ES modules each loads, from an
allow-list, TD-045) — chat and the timeline. Dark-first, Auspex palette
(CLAUDE.md brand). The underlying engine/model is never named in any
user-visible string — the UI only ever says "Auspex" / "Co-analyst".
"""

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, Response

router = APIRouter(tags=["ui"])

_STATIC = Path(__file__).resolve().parent.parent / "static"
_INDEX = _STATIC / "index.html"
_TIMELINE = _STATIC / "timeline.html"
# B-003: with only `last-modified`, a browser caches the page on heuristic
# freshness and keeps running the old one after a deploy. `no-cache` makes every
# load ask first; TD-047: a matching ETag is answered 304, not the file again.
_REVALIDATE = {"Cache-Control": "no-cache"}
# D-057: each page runs only its own scripts and talks only to its own origin;
# TD-045 (chat) and TD-051 (timeline) moved every script and style rule out of
# the pages to make that possible without 'unsafe-inline'.
_CHAT_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "connect-src 'self'",
    "img-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
])
_PAGE_HEADERS = {**_REVALIDATE, "Content-Security-Policy": _CHAT_CSP}
# TD-045, TD-051: each page's own files, by name. An allow-list, so no name a
# request can make reaches anything else on disk.
_ASSETS = {
    "css/chat.css": ("text/css", _STATIC / "css" / "chat.css"),
    "js/page-logic.js": ("text/javascript", _STATIC / "js" / "page-logic.js"),
    "js/chat.js": ("text/javascript", _STATIC / "js" / "chat.js"),
    "css/timeline.css": ("text/css", _STATIC / "css" / "timeline.css"),
    "js/timeline-logic.js": ("text/javascript", _STATIC / "js" / "timeline-logic.js"),
    "js/timeline.js": ("text/javascript", _STATIC / "js" / "timeline.js"),
    "js/shell-logic.js": ("text/javascript", _STATIC / "js" / "shell-logic.js"),
}

# A declared header, not the raw request mapping: the tenancy walk forbids reading
# raw input in a route file (tests/test_tenancy_roles.py).
IfNoneMatch = Annotated[str | None, Header()]


def _matches(if_none_match: str | None, etag: str) -> bool:
    """RFC 9110's weak comparison for If-None-Match: any listed tag, `W/` or
    not, or `*`."""
    if not if_none_match:
        return False
    tags = {t.strip().removeprefix("W/") for t in if_none_match.split(",")}
    return "*" in tags or etag in tags


def _serve(path: Path, media_type: str, headers: dict[str, str],
           if_none_match: str | None) -> Response:
    """The file, or a 304 when the browser already holds this version (TD-047).
    The stat is read first so the ETag is known before answering; the 304
    carries the same headers a 200 would, so a page's policy is never missing."""
    resp = FileResponse(path, media_type=media_type, headers=headers, stat_result=os.stat(path))
    etag = resp.headers["etag"]
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers={**headers, "ETag": etag})
    return resp


def _asset(key: str, if_none_match: str | None) -> Response:
    entry = _ASSETS.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not Found")
    media_type, path = entry
    return _serve(path, media_type, _REVALIDATE, if_none_match)


@router.get("/", include_in_schema=False)
async def index(if_none_match: IfNoneMatch = None) -> Response:
    return _serve(_INDEX, "text/html", _PAGE_HEADERS, if_none_match)


@router.get("/timeline", include_in_schema=False)
async def timeline(if_none_match: IfNoneMatch = None) -> Response:
    """S16 — a verdict's life in one place, and the "your past got re-scored"
    digest. Reads /api/timeline only; the page holds no decay arithmetic of its
    own, so a band means the same thing on screen as it does in the payload."""
    return _serve(_TIMELINE, "text/html", _PAGE_HEADERS, if_none_match)


@router.get("/css/{name}", include_in_schema=False)
async def stylesheet(name: str, if_none_match: IfNoneMatch = None) -> Response:
    return _asset(f"css/{name}", if_none_match)


@router.get("/js/{name}", include_in_schema=False)
async def script(name: str, if_none_match: IfNoneMatch = None) -> Response:
    return _asset(f"js/{name}", if_none_match)
