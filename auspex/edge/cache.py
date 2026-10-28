"""Packages by content hash (D-062): fetched from the edge API, re-hashed with the SDK's
`read_package`, and run only when the hash is the one the job names. A mismatch is
refused naming both hashes; nothing of it is unpacked."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from auspex_sdk.package import read_package

_SAFE = re.compile(r"[^A-Za-z0-9]")


class PackageMismatch(ValueError):
    """The bytes served for a hash do not hash to it."""


def unpack(cache_dir: Path, content_hash: str, data: bytes) -> Path:
    """The package's directory, unpacked only if `data` hashes to `content_hash`."""
    _, actual, files = read_package(data)
    if actual != content_hash:
        raise PackageMismatch(
            f"the package served for {content_hash} hashes to {actual}; not run")
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = cache_dir / _SAFE.sub("_", content_hash)
    if not target.exists():
        staging = target.with_suffix(".partial")
        shutil.rmtree(staging, ignore_errors=True)  # a crash's leftovers never join it
        for name, body in files.items():
            path = staging / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(body)
        staging.rename(target)
    return target


def cached(cache_dir: Path, content_hash: str) -> Path | None:
    target = cache_dir / _SAFE.sub("_", content_hash)
    return target if target.exists() else None
