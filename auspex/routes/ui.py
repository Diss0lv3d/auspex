"""Minimal dark-first UI shell (S3 step 5).

Serves a single self-contained page that talks to /api/auth/dev-login and the
SSE /api/chat endpoint. Dark-first, Auspex palette (CLAUDE.md brand). The
underlying engine/model is never named in any user-visible string — the UI only
ever says "Auspex" / "Co-analyst".
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["ui"])

_INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_INDEX, media_type="text/html")
