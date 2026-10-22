"""Connector packages and their content hash (S32, D-064).

A package is the zip `auspex-sdk build` writes: `manifest.json` at the root plus the
connector's Python and data files. This module only ever READS bytes: the core calls
`read_package` on an admin's upload and S33's Edge Agent recomputes the same hash before it
runs anything, and neither imports or executes a member here. Pure: stdlib plus
`auspex_sdk.manifest`.

The content hash is a tree hash, not the zip's bytes: SHA-256 over the lines
`"<posix path>\\0<sha256 hex of the file>\\n"`, sorted by path, written `sha256:<hex>`. Zip
quirks (timestamps, compression, ordering) cannot change a connector's identity.

`read_package` raises `PackageError` and nothing else, whatever the bytes hold. Sizes are
checked from the zip's declared sizes BEFORE a member is inflated (a zip bomb is refused
without being expanded), and a member that inflates past its declared size is refused too.
"""

import hashlib
import io
import json
import lzma
import stat
import unicodedata
import zipfile
import zlib

from auspex_sdk.manifest import Manifest, ManifestError, parse_manifest, validate_manifest

# Caps are code constants (D-026, spec "What a package's content hash covers").
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILES = 500

MANIFEST_NAME = "manifest.json"

# The build compiles the YAML into manifest.json, so a package that still carries it, or
# tests, caches and dotfiles, was not built by `auspex-sdk build`.
_EXCLUDED_DIRS = frozenset({"tests", "test", "__pycache__"})

# Windows device names: a file called `con.txt` cannot be extracted there as itself.
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

# A member must unpack to the same bytes on any host, so only these methods are read.
_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


class PackageError(ValueError):
    """A package the platform refuses. `member` names the offending zip member, if any."""

    def __init__(self, message: str, member: str | None = None):
        super().__init__(message if member is None else f"{member}: {message}")
        self.member = member


def tree_hash(files: dict[str, bytes]) -> str:
    """The content hash of exactly the files given (the caller applies the exclusions)."""
    lines = b"".join(
        p.encode("utf-8") + b"\0" + hashlib.sha256(files[p]).hexdigest().encode("ascii") + b"\n"
        for p in sorted(files, key=lambda p: p.encode("utf-8"))
    )
    return "sha256:" + hashlib.sha256(lines).hexdigest()


def build_zip(files: dict[str, bytes]) -> bytes:
    """Deterministic zip: sorted, fixed 1980 timestamps, deflate, no extras, fixed host system."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # unix, so external_attr means what we set
            info.external_attr = 0o644 << 16
            info.extra = b""
            info.comment = b""
            z.writestr(info, files[path])
    return buf.getvalue()


def _check_path(name: str) -> str:
    """Return the normalized member path, or refuse it. A leading `./` is tolerated and dropped.

    The rules hold on a case-insensitive, NTFS or normalizing filesystem too, so the files that
    run are the files that were hashed.
    """
    path = name
    while path.startswith("./"):
        path = path[2:]
    if not path or "\0" in path or "\\" in path or path.startswith("/"):
        raise PackageError("not a relative posix path", name)
    if unicodedata.normalize("NFC", path) != path:
        raise PackageError("path is not NFC-normalized", name)
    segments = path.split("/")
    if any(s in ("", ".", "..") for s in segments):
        raise PackageError("empty, '.' or '..' path segment", name)
    if any(":" in s for s in segments):
        raise PackageError("':' in a path (drive letter or NTFS stream)", name)
    if any(s != s.strip() or s.endswith(".") for s in segments):
        raise PackageError("segment with surrounding whitespace or a trailing dot", name)
    if any(s.split(".", 1)[0].lower() in _RESERVED for s in segments):
        raise PackageError("Windows reserved device name", name)
    if any(s.startswith(".") for s in segments):
        raise PackageError("dotfiles are not part of a package", name)
    lowered = [s.lower() for s in segments]
    if any(s in _EXCLUDED_DIRS for s in lowered[:-1]) or lowered[-1] == "__pycache__":
        raise PackageError("tests and caches are not part of a package", name)
    leaf = lowered[-1]
    if leaf.endswith((".pyc", ".yaml", ".yml")) or (
        leaf.startswith("test_") and leaf.endswith(".py")
    ):
        raise PackageError("tests, caches and the YAML source are not part of a package", name)
    return path


def _parse_manifest(raw: bytes) -> Manifest:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise PackageError(f"is not valid JSON: {e}", MANIFEST_NAME) from e
    if not isinstance(data, dict):
        raise PackageError("must be a JSON object", MANIFEST_NAME)
    try:
        m = parse_manifest(data)
        validate_manifest(m)
    except ManifestError as e:
        raise PackageError(f"invalid ({e.rule} at {e.path or '<root>'}): {e}", MANIFEST_NAME) from e
    except ValueError as e:  # e.g. urlsplit on a malformed IPv6 url default
        raise PackageError(f"invalid: {e}", MANIFEST_NAME) from e
    return m


def read_package(data: bytes) -> tuple[Manifest, str, dict[str, bytes]]:
    """Validate a package's bytes; return (manifest, content hash, files). Never executes."""
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackageError(f"package is larger than {MAX_PACKAGE_BYTES} bytes")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError, EOFError) as e:
        raise PackageError(f"not a readable zip: {e}") from e
    with z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            raise PackageError(f"more than {MAX_FILES} files")
        chosen: list[tuple[zipfile.ZipInfo, str]] = []
        seen: set[str] = set()
        declared_total = 0
        for info in infos:
            name = info.filename
            if name.endswith("/") and "\\" not in name:
                if info.file_size:
                    raise PackageError("a directory entry carries data", name)
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise PackageError("symlinks are not allowed", name)
            path = _check_path(name)
            if info.flag_bits & 0x1:
                raise PackageError("encrypted members are not allowed", name)
            if info.compress_type not in _METHODS:
                raise PackageError(f"compression method {info.compress_type} not allowed", name)
            key = path.casefold()
            if key in seen:
                raise PackageError("duplicate member (case or normalization)", name)
            seen.add(key)
            limit = MAX_MANIFEST_BYTES if path == MANIFEST_NAME else MAX_PACKAGE_BYTES
            if info.file_size > limit:
                raise PackageError(f"declares more than {limit} bytes", name)
            declared_total += info.file_size
            if declared_total > MAX_PACKAGE_BYTES:
                raise PackageError(
                    f"package would decompress to more than {MAX_PACKAGE_BYTES} bytes"
                )
            chosen.append((info, path))
        files: dict[str, bytes] = {}
        for info, path in chosen:
            try:
                with z.open(info) as f:
                    body = f.read(info.file_size + 1)
            except (
                zipfile.BadZipFile,
                RuntimeError,
                NotImplementedError,
                zlib.error,
                lzma.LZMAError,
                OSError,
                EOFError,
            ) as e:
                raise PackageError(f"unreadable member: {e}", info.filename) from e
            if len(body) > info.file_size:
                raise PackageError("decompresses past its declared size", info.filename)
            files[path] = body
    if MANIFEST_NAME not in files:
        raise PackageError("a package needs manifest.json at its root", MANIFEST_NAME)
    manifest = _parse_manifest(files[MANIFEST_NAME])
    return manifest, tree_hash(files), files
