"""Shortcut handlers (S4 step 3) — static fast-path answers, provably offline.

S5 narrowed the S4 contract: the shortcut path is LLM-FREE always, and the
*classify package* stays fully network-free — but ioc_check turns may now run
enrichment HTTP through the separate auspex.enrich package (mockable at
app.state.enrichment; see test_chat_sse.py). The guards here therefore cover:
- runtime: every static handler runs with socket connections blocked;
- structural: classify never imports an LLM client or HTTP/socket library,
  and enrich never imports the LLM client (enrichment is direct HTTP only).
Plus the brand rule: the engine is never named in shortcut copy.
"""

import socket
from pathlib import Path

import pytest
from _fakes import FORBIDDEN_ENGINE_NAMES as BASE_FORBIDDEN

import auspex.classify
from auspex.classify import Category, classify, shortcut_answer

# Shortcut copy is held to a stricter bar than page markup: even the generic
# word "model" must not appear (the platform never presents itself as one).
FORBIDDEN_ENGINE_NAMES = [*BASE_FORBIDDEN, "model"]

ALL_SHORTCUT_QUERIES = {
    Category.GREETING: "hello",
    Category.IDENTITY: "who are you?",
    Category.IOC_CHECK: "check 8.8.8.8 and evil[.]xyz",
    Category.CVE_LOOKUP: "CVE-2024-3400",
    Category.DEFINITION: "what is dns tunneling",
}


@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("shortcut path attempted a network call")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


# -- the contract: every shortcut category answers offline ---------------------


def test_every_shortcut_category_answers_with_network_blocked(no_network):
    for category, query in ALL_SHORTCUT_QUERIES.items():
        classification = classify(query)
        assert classification.category is category, query
        answer = shortcut_answer(classification)
        assert answer is not None and answer.category is category
        assert answer.text.strip(), query


def test_deep_returns_none_so_the_caller_falls_through(no_network):
    assert shortcut_answer(classify("summarize today's alerts")) is None


def test_shortcut_answers_are_deterministic(no_network):
    for query in ALL_SHORTCUT_QUERIES.values():
        first = shortcut_answer(classify(query))
        second = shortcut_answer(classify(query))
        assert first == second


def test_classify_package_never_imports_llm_or_network_libs():
    package_dir = Path(auspex.classify.__file__).parent
    forbidden = ("auspex.llm", "httpx", "requests", "socket", "urllib.request", "aiohttp")
    for source_file in package_dir.glob("*.py"):
        text = source_file.read_text()
        for needle in forbidden:
            assert needle not in text, f"{source_file.name} references {needle}"


def test_enrich_package_never_imports_the_llm(no_network):
    """S5: enrichment is direct provider HTTP — an LLM import anywhere in
    auspex.enrich would put model calls back on the 92% path."""
    import auspex.enrich

    package_dir = Path(auspex.enrich.__file__).parent
    for source_file in package_dir.rglob("*.py"):
        assert "auspex.llm" not in source_file.read_text(), source_file.name


# -- brand + voice --------------------------------------------------------------


def test_shortcut_copy_never_names_the_engine():
    for query in ALL_SHORTCUT_QUERIES.values():
        text = shortcut_answer(classify(query)).text.lower()
        for name in FORBIDDEN_ENGINE_NAMES:
            assert name not in text, f"{name!r} leaked into: {text[:80]}"


def test_identity_and_greeting_speak_as_auspex():
    assert "Auspex" in shortcut_answer(classify("who are you?")).text
    assert "Auspex" in shortcut_answer(classify("hi")).text


# -- ioc_check echo --------------------------------------------------------------


def test_ioc_check_echoes_normalized_values_and_ids():
    classification = classify("check 185.220.101[.]34 and evil[.]xyz")
    answer = shortcut_answer(classification)
    assert answer.category is Category.IOC_CHECK
    assert "185.220.101.34" in answer.text  # normalized, not the defanged raw
    assert "evil.xyz" in answer.text
    assert "185.220.101[.]34" not in answer.text
    assert "`" not in answer.text  # plain text — the UI renders content verbatim
    for o in classification.observables:
        assert o.obs_id in answer.text


def test_ioc_check_marks_defanged_observables():
    answer = shortcut_answer(classify("check 8.8.8.8 and evil[.]xyz"))
    lines = answer.text.splitlines()
    ip_line = next(ln for ln in lines if "8.8.8.8" in ln)
    domain_line = next(ln for ln in lines if "evil.xyz" in ln)
    assert "defanged" not in ip_line
    assert "defanged" in domain_line


def test_ioc_check_defers_enrichment_and_claims_no_verdict():
    answer = shortcut_answer(classify("check 8.8.8.8"))
    assert "deferred" in answer.text.lower()
    # deterministic echo only — no fabricated verdicts (D-014 spirit)
    for verdict_word in ("malicious", "clean", "benign", "safe", "suspicious"):
        assert verdict_word not in answer.text.lower()


def test_bulk_paste_echo_lists_every_observable():
    hashes = [f"{i:064x}" for i in range(30)]
    answer = shortcut_answer(classify("triage these: " + " ".join(hashes)))
    assert answer.category is Category.IOC_CHECK
    assert "Parsed 30 observables" in answer.text
    for h in hashes:
        assert h in answer.text


# -- deferred stubs ---------------------------------------------------------------


def test_cve_lookup_names_the_cve_and_defers():
    answer = shortcut_answer(classify("what is cve-2021-44228"))
    assert answer.category is Category.CVE_LOOKUP
    assert "CVE-2021-44228" in answer.text  # normalized uppercase
    assert "deferred" in answer.text.lower()
    assert "deep path" in answer.text.lower()


def test_definition_defers_to_deep_path():
    answer = shortcut_answer(classify("what is dns tunneling"))
    assert answer.category is Category.DEFINITION
    assert "deferred" in answer.text.lower()
    assert "deep path" in answer.text.lower()
