"""POST and GET /api/connectors (S32, spec decision 3): the workspace's catalogue.

Register is admin-only and always lands in the caller's ACTIVE workspace, registered by
the caller; neither id, nor `first_party`, is read from the request (D-064, D-061). The
body is read with a hard cap while it streams, so an oversize upload is refused before
it is buffered whole or parsed (the multipart parser is the first thing to cost memory).
Listing is any role: a listing is code, not access to a client's data (D-071).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Annotated, Protocol

from auspex_sdk.package import MAX_PACKAGE_BYTES
from fastapi import APIRouter, Header, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.requests import ClientDisconnect

from auspex.auth import Admin, AnyRole
from auspex.connectors.catalogue import CatalogueEntry, RegistrationRefused, available, register

logger = logging.getLogger("auspex.connectors")

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

# The multipart envelope (boundaries, part headers, the one form field) around a package.
ENVELOPE_BYTES = 64 * 1024
MAX_BODY_BYTES = MAX_PACKAGE_BYTES + ENVELOPE_BYTES


class _Streams(Protocol):
    def stream(self) -> AsyncIterator[bytes]: ...


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"the upload is over the {MAX_BODY_BYTES} byte limit"
        f" (a package is at most {MAX_PACKAGE_BYTES} bytes)",
    )


async def read_capped(request: _Streams, limit: int = MAX_BODY_BYTES) -> bytes:
    """The request body, refused with 413 the moment it passes `limit`: the stream is
    abandoned at that chunk, so a client that lies about (or omits) Content-Length still
    cannot make us hold more than `limit` plus one chunk."""
    body = BytesIO()
    async for chunk in request.stream():
        if body.tell() + len(chunk) > limit:
            raise _too_large()
        body.write(chunk)
    return body.getvalue()


def _flag(value: str | bytes | UploadFile | None) -> bool:
    text = value.strip().lower() if isinstance(value, str) else ""
    if text in ("", "false", "0"):
        return False
    if text in ("true", "1"):
        return True
    raise HTTPException(status_code=422, detail="offered_to_clients must be true or false")


def present(entry: CatalogueEntry) -> dict:
    """A catalogue row as the caller's workspace may see it. Who registered a package, and
    in which workspace, is the owner's business: a provider's or first-party row exposes
    neither (Review Focus: no cross-tenant identifiers in a listing)."""
    row = {
        "id": str(entry.id),
        "connector_id": entry.connector_id,
        "version": entry.version,
        "content_hash": entry.content_hash,
        "manifest": entry.manifest,
        "first_party": entry.first_party,
        "offered_to_clients": entry.offered_to_clients,
        "created_at": entry.created_at.isoformat(),
        "source": entry.source,
    }
    if entry.source == "own":
        row["workspace_id"] = str(entry.workspace_id)
        row["registered_by"] = str(entry.registered_by) if entry.registered_by else None
    return row


@router.post("", status_code=201)
async def register_connector(
    request: Request,
    auth: Admin,
    content_length: Annotated[int | None, Header()] = None,
) -> dict:
    """Register a package (multipart: `package` file, `offered_to_clients` field) in the
    caller's workspace. The role check ran before this body: a non-admin never reaches
    the read."""
    if content_length is not None and content_length > MAX_BODY_BYTES:
        raise _too_large()
    try:
        body = await read_capped(request)
    except ClientDisconnect as err:
        raise HTTPException(status_code=400, detail="the upload was cut off") from err
    # Parse the bounded bytes with the stock parser by replaying them as the request body.
    sent = False

    async def replay():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    bounded = Request(request.scope, replay)
    try:
        form = await bounded.form(max_files=1, max_fields=4)
    except Exception as err:  # malformed multipart or a non-multipart content type
        raise HTTPException(
            status_code=422, detail="send multipart/form-data with a `package` file"
        ) from err
    try:
        upload = form.get("package")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail="a `package` file is required")
        data = await upload.read()
        offered = _flag(form.get("offered_to_clients"))
    finally:
        await form.close()
    try:
        entry = await register(
            request.app.state.pool,
            workspace_id=auth.workspace_id,
            data=data,
            registered_by=auth.user_id,
            offered_to_clients=offered,
            first_party=False,
        )
    except RegistrationRefused as err:
        raise HTTPException(status_code=422, detail=err.reason) from err
    return present(entry)


@router.get("")
async def list_connectors(request: Request, auth: AnyRole) -> dict:
    """What this workspace may use: own, its provider's offered, and first-party."""
    entries = await available(request.app.state.pool, workspace_id=auth.workspace_id)
    return {"connectors": [present(e) for e in entries]}
