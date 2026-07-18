"""MITRE ATT&CK Enterprise STIX feed — probe-pinned
(docs/probes/2026-07-18-attack-stix.md).

The version INDEX (31 KB) is the cursor; the 53 MB bundle (9 MB wire)
downloads only on a version change (~2 majors/year + point releases).
Reality bites encoded here:
- raw.githubusercontent DOES honor If-None-Match (unlike CISA's CDN), but
  version comparison against the index is simpler and sufficient.
- 858 attack-patterns → 697 live: `revoked` (149) and `x_mitre_deprecated`
  (12) must be filtered; no live∩dead external-id collisions.
- Sub-technique parentage is encoded in the id itself (T1055.011 → T1055) —
  the existing ID-rail prefix behavior needs nothing new.
- Descriptions are markdown with `(Citation: …)` markers; max 4,680 chars.
"""

import re
from dataclasses import dataclass

import httpx

from auspex import __version__
from auspex.kb.seed import MAX_DESCRIPTION_CHARS
from auspex.kb.types import KBDoc

INDEX_URL = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/index.json"
COLLECTION_NAME = "Enterprise ATT&CK"
# Bundle URLs come from the index (same repo) — pin the prefix so a poisoned
# index can't redirect the 53 MB fetch anywhere else.
BUNDLE_URL_PREFIX = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/"
INDEX_TIMEOUT_SECONDS = 30.0
BUNDLE_TIMEOUT_SECONDS = 180.0  # 53 MB (9 MB wire) measured at 5.7 s — leave slack

_CITATION_RE = re.compile(r"\s*\(Citation: [^)]*\)")
_TECHNIQUE_ID_RE = re.compile(r"T\d{4}(\.\d{3})?")
_TACTIC_ID_RE = re.compile(r"TA\d{4}")


class ATTACKError(Exception):
    """Non-retryable ATT&CK feed error; the caller must NOT advance its cursor."""


@dataclass(frozen=True)
class ATTACKVersion:
    version: str  # "19.1"
    modified: str  # index `modified` timestamp
    url: str  # per-version bundle URL


def _version_key(version: str) -> tuple[int, ...]:
    parts = version.split(".")
    return tuple(int(p) for p in parts if p.isdigit()) or (0,)


def _ext_id(obj: dict) -> str | None:
    for ref in obj.get("external_references", ()):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def bundle_to_docs(objects: list[dict]) -> list[KBDoc]:
    """Live techniques + tactics from a bundle's objects — pure, no I/O.
    Provenance is honest: these are excerpts of ATT&CK content derived from
    the STIX bundle, labeled with the collection version, never presented as
    Auspex-authored summaries. Ids are shape-validated (untrusted input —
    same rail as the NVD feed, S8 review)."""
    version = next(
        (o.get("x_mitre_version", "") for o in objects if o.get("type") == "x-mitre-collection"),
        "",
    )
    docs: list[KBDoc] = []
    for obj in objects:
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        kind = obj.get("type")
        if kind == "attack-pattern":
            ext = _ext_id(obj)
            if not ext or not _TECHNIQUE_ID_RE.fullmatch(ext):
                continue
            slug = ext.replace(".", "/")
            docs.append(
                _doc(
                    obj,
                    ext,
                    doc_type="technique",
                    version=version,
                    ref=f"https://attack.mitre.org/techniques/{slug}/ (ATT&CK v{version})",
                    extras=_technique_extras(obj),
                )
            )
        elif kind == "x-mitre-tactic":
            ext = _ext_id(obj)
            if not ext or not _TACTIC_ID_RE.fullmatch(ext):
                continue
            docs.append(
                _doc(
                    obj,
                    ext,
                    doc_type="tactic",
                    version=version,
                    ref=f"https://attack.mitre.org/tactics/{ext}/ (ATT&CK v{version})",
                    extras="",
                )
            )
    return docs


def _technique_extras(obj: dict) -> str:
    parts: list[str] = []
    tactics = [
        p.get("phase_name", "").replace("-", " ")
        for p in obj.get("kill_chain_phases", ())
        if p.get("kill_chain_name") == "mitre-attack"
    ]
    if tactics:
        parts.append("Tactics: " + ", ".join(t for t in tactics if t) + ".")
    platforms = [p for p in obj.get("x_mitre_platforms", ()) if isinstance(p, str)]
    if platforms:
        parts.append("Platforms: " + ", ".join(platforms) + ".")
    return " ".join(parts)


def _doc(
    obj: dict, ext: str, *, doc_type: str, version: str, ref: str, extras: str
) -> KBDoc:
    description = _CITATION_RE.sub("", obj.get("description", "")).strip()
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS] + " […]"
    content = f"{description}\n\n{extras}" if extras else description
    return KBDoc(
        doc_id=ext,
        title=f"{ext}: {obj.get('name', '')}",
        content=content,
        doc_type=doc_type,
        source="mitre-attack-stix",
        source_ref=ref,
        ids=(ext,),
    )


class ATTACKFeed:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": f"Auspex/{__version__}"},
                timeout=INDEX_TIMEOUT_SECONDS,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def latest_version(self) -> ATTACKVersion:
        """Newest Enterprise ATT&CK version from the index — by parsed
        version, not list order (the order is not contractual)."""
        resp = await self._get_client().get(INDEX_URL, timeout=INDEX_TIMEOUT_SECONDS)
        resp.raise_for_status()
        collections = resp.json().get("collections", ())
        enterprise = next((c for c in collections if c.get("name") == COLLECTION_NAME), None)
        if not enterprise or not enterprise.get("versions"):
            raise ATTACKError("Enterprise ATT&CK collection missing from the version index")
        best = max(enterprise["versions"], key=lambda v: _version_key(str(v.get("version", ""))))
        url = str(best.get("url", ""))
        if not url.startswith(BUNDLE_URL_PREFIX):
            raise ATTACKError(f"bundle URL escaped the pinned repo prefix: {url[:80]}")
        return ATTACKVersion(
            version=str(best.get("version", "")), modified=str(best.get("modified", "")), url=url
        )

    async def fetch_objects(self, url: str) -> list[dict]:
        if not url.startswith(BUNDLE_URL_PREFIX):
            raise ATTACKError(f"refusing bundle fetch outside the pinned repo: {url[:80]}")
        resp = await self._get_client().get(url, timeout=BUNDLE_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json().get("objects", [])
