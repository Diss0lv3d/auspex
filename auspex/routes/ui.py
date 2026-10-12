"""Minimal dark-first UI shell (S3 step 5).

Serves the chat page (its markup, plus its CSS and two ES modules from an
allow-list, TD-045) and the timeline page. The chat page talks to
/api/auth/dev-login and the SSE /api/chat endpoint. Dark-first, Auspex palette
(CLAUDE.md brand). The underlying engine/model is never named in any
user-visible string — the UI only ever says "Auspex" / "Co-analyst".
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["ui"])

_STATIC = Path(__file__).resolve().parent.parent / "static"
_INDEX = _STATIC / "index.html"
_TIMELINE = _STATIC / "timeline.html"
# B-003: with only `last-modified`, a browser caches the page on heuristic
# freshness and keeps running the old one after a deploy. `no-cache` makes every
# load ask first. FileResponse answers a matching ETag in full, not with a 304
# (measured in F1), so each load costs the page's ~17 KB.
_REVALIDATE = {"Cache-Control": "no-cache"}
# TD-045: the chat page's own files, by name. An allow-list, so no name a
# request can make reaches anything else on disk.
_ASSETS = {
    "css/chat.css": ("text/css", _STATIC / "css" / "chat.css"),
    "js/page-logic.js": ("text/javascript", _STATIC / "js" / "page-logic.js"),
    "js/chat.js": ("text/javascript", _STATIC / "js" / "chat.js"),
}


def _asset(key: str) -> FileResponse:
    entry = _ASSETS.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not Found")
    media_type, path = entry
    return FileResponse(path, media_type=media_type, headers=_REVALIDATE)


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_INDEX, media_type="text/html", headers=_REVALIDATE)


@router.get("/timeline", include_in_schema=False)
async def timeline() -> FileResponse:
    """S16 — a verdict's life in one place, and the "your past got re-scored"
    digest. Reads /api/timeline only; the page holds no decay arithmetic of its
    own, so a band means the same thing on screen as it does in the payload."""
    return FileResponse(_TIMELINE, media_type="text/html", headers=_REVALIDATE)


@router.get("/css/{name}", include_in_schema=False)
async def stylesheet(name: str) -> FileResponse:
    return _asset(f"css/{name}")


@router.get("/js/{name}", include_in_schema=False)
async def script(name: str) -> FileResponse:
    return _asset(f"js/{name}")
