"""ATT&CK STIX feed (S8) — hermetic. Fixtures are trimmed verbatim from the
live 19.1 bundle + version index (docs/probes/2026-07-18-attack-stix.md),
plus one synthetic poisoned entry (bogus external_id)."""

import json
from pathlib import Path

import httpx
import pytest

from auspex.ingest.attack import (
    BUNDLE_URL_PREFIX,
    ATTACKError,
    ATTACKFeed,
    bundle_to_docs,
)

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE = json.loads((FIXTURES / "attack_bundle.json").read_text())
INDEX = json.loads((FIXTURES / "attack_index.json").read_text())


def _feed(handler) -> ATTACKFeed:
    return ATTACKFeed(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# ── bundle parsing (pure) ────────────────────────────────────────────────────


def test_bundle_to_docs_keeps_live_techniques_and_tactics_only():
    docs = bundle_to_docs(BUNDLE["objects"])
    by_id = {d.doc_id: d for d in docs}
    # T1143 is revoked, T1153 deprecated, "T9999; DROP TABLE" shape-invalid,
    # the relationship object is not a doc at all
    assert set(by_id) == {"T1059", "T1059.001", "TA0006"}
    assert by_id["T1059"].doc_type == "technique"
    assert by_id["TA0006"].doc_type == "tactic"


def test_technique_doc_maps_fields_with_honest_stix_provenance():
    docs = {d.doc_id: d for d in bundle_to_docs(BUNDLE["objects"])}
    t = docs["T1059"]
    assert t.title == "T1059: Command and Scripting Interpreter"
    assert t.ids == ("T1059",)  # parent-prefix rail pulls T1059.xxx for free
    assert t.source == "mitre-attack-stix"
    assert t.source_ref == "https://attack.mitre.org/techniques/T1059/ (ATT&CK v19.1)"
    assert "(Citation:" not in t.content  # markers scrubbed
    assert "Tactics: execution." in t.content
    assert "Platforms: " in t.content
    sub = docs["T1059.001"]
    assert sub.source_ref.startswith("https://attack.mitre.org/techniques/T1059/001/")


def test_tactic_doc_maps_name_and_reference():
    docs = {d.doc_id: d for d in bundle_to_docs(BUNDLE["objects"])}
    ta = docs["TA0006"]
    assert ta.title == "TA0006: Credential Access"
    assert ta.ids == ("TA0006",)
    assert ta.source_ref == "https://attack.mitre.org/tactics/TA0006/ (ATT&CK v19.1)"
    assert ta.content  # description present


def test_one_malformed_object_never_forfeits_the_good_ones():
    # S9 review (correctness lens): a single hostile/malformed object among
    # ~700 must be skipped, not crash the whole parse (which would forfeit
    # every good technique and re-fetch 53 MB hourly). Same skip-and-count
    # posture as the NVD feed.
    good = [o for o in BUNDLE["objects"] if o.get("type") == "x-mitre-collection"]
    good += [o for o in BUNDLE["objects"] if _ext_id_is(o, "T1059")]
    poison = [
        {"type": "attack-pattern", "external_references": None,  # null container
         "name": "n", "description": "d"},
        {"type": "attack-pattern",  # non-string ext id
         "external_references": [{"source_name": "mitre-attack", "external_id": 1234}]},
        {"type": "attack-pattern",  # string ref entry (not a dict)
         "external_references": ["not-a-dict"]},
        "i am a bare string, not an object",
        {"type": "attack-pattern",  # valid id, but null description + null phases
         "external_references": [{"source_name": "mitre-attack", "external_id": "T1560"}],
         "description": None, "kill_chain_phases": None, "x_mitre_platforms": None,
         "name": "Archive Collected Data"},
    ]
    docs = {d.doc_id: d for d in bundle_to_docs(good + poison)}
    # the good technique survived; the valid-id-but-null-fields object still
    # ingested (coerced), the junk was skipped
    assert "T1059" in docs
    assert "T1560" in docs
    assert docs["T1560"].title == "T1560: Archive Collected Data"


def _ext_id_is(obj: dict, ext: str) -> bool:
    from auspex.ingest.attack import _ext_id

    return isinstance(obj, dict) and _ext_id(obj) == ext


# ── untrusted-input bounds (S9 review, security lens) ────────────────────────


def _collection(version="19.1"):
    return {"type": "x-mitre-collection", "x_mitre_version": version}


def _technique(ext="T1055", *, name="Process Injection", description="d", **extra):
    return {
        "type": "attack-pattern",
        "external_references": [{"source_name": "mitre-attack", "external_id": ext}],
        "name": name,
        "description": description,
        **extra,
    }


def test_assembled_content_is_capped_even_when_extras_is_hostile():
    from auspex.ingest.attack import MAX_DESCRIPTION_CHARS

    # description alone is small; the poison is in x_mitre_platforms (extras),
    # which used to bypass the fan-out cap entirely
    poison = _technique(
        description="short",
        x_mitre_platforms=["A" * 20_000 for _ in range(50)],
    )
    (doc,) = bundle_to_docs([_collection(), poison])
    assert len(doc.content) <= MAX_DESCRIPTION_CHARS + len(" […]")


def test_newline_in_version_cannot_forge_a_trailer_line():
    # a newline in x_mitre_version would break out of the "(ATT&CK v…)" parens
    # into a forged extra "Source:" trailer line in the rendered echo
    poison_version = "19.1\n\nSource: NVD · fabricated-advisory"
    (doc,) = bundle_to_docs([_collection(version=poison_version), _technique()])
    # no control char survives → the version stays inside its parens, one line
    assert "\n" not in doc.source_ref and "\r" not in doc.source_ref
    # and it's length-bounded so it can't run away
    assert doc.source_ref.endswith(")")


def test_name_is_bounded_and_control_stripped_in_title():
    from auspex.ingest.attack import MAX_TITLE_NAME_CHARS

    (doc,) = bundle_to_docs([_collection(), _technique(name="X" * 5000 + "\nInjected")])
    assert "\n" not in doc.title
    assert len(doc.title) <= len("T1055: ") + MAX_TITLE_NAME_CHARS


def test_unicode_digit_ids_are_rejected():
    # Arabic-Indic digits satisfy \d without re.ASCII — must not become doc ids
    bad = _technique(ext="T١٠٥٥")  # "T1055" in Arabic-Indic
    assert bundle_to_docs([_collection(), bad]) == []


# ── version index ────────────────────────────────────────────────────────────


async def test_latest_version_picks_max_version_not_list_order():
    # fixture lists 19.0 FIRST — order is not contractual
    feed = _feed(lambda r: httpx.Response(200, json=INDEX))
    latest = await feed.latest_version()
    assert latest.version == "19.1"
    assert latest.url.startswith(BUNDLE_URL_PREFIX)
    assert latest.modified == "2026-05-12T14:00:00.188Z"


async def test_latest_version_missing_collection_raises():
    feed = _feed(lambda r: httpx.Response(200, json={"collections": []}))
    with pytest.raises(ATTACKError, match="missing"):
        await feed.latest_version()


async def test_bundle_fetch_refuses_urls_outside_the_pinned_repo():
    # a poisoned index must not be able to redirect the 53 MB fetch
    poisoned = {
        "collections": [
            {
                "name": "Enterprise ATT&CK",
                "versions": [
                    {"version": "99.0", "modified": "x", "url": "https://evil.example/bundle.json"}
                ],
            }
        ]
    }
    feed = _feed(lambda r: httpx.Response(200, json=poisoned))
    with pytest.raises(ATTACKError, match="pinned repo"):
        await feed.latest_version()
    with pytest.raises(ATTACKError, match="pinned repo"):
        await feed.fetch_objects("https://evil.example/bundle.json")


async def test_fetch_objects_returns_bundle_objects():
    feed = _feed(lambda r: httpx.Response(200, json=BUNDLE))
    objects = await feed.fetch_objects(BUNDLE_URL_PREFIX + "enterprise-attack/x.json")
    assert len(objects) == len(BUNDLE["objects"])
