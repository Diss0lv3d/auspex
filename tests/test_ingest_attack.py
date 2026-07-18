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
