"""Shortcut handlers (S4 step 3) — static fast-path answers, provably offline.

Two guards enforce the 92/8 contract:
- runtime: every handler runs with socket connections blocked (any network
  attempt raises), proving the shortcut path is network-free;
- structural: the classify package's source never imports an LLM client or an
  HTTP/socket library at all.
Plus the brand rule: the engine is never named in shortcut copy.
"""

import socket
from pathlib import Path

import pytest

import auspex.classify
from auspex.classify import Category, classify, shortcut_answer

# Superset of the lists in test_ui.py / test_models.py.
FORBIDDEN_ENGINE_NAMES = [
    "qwen", "ollama", "llama", "vllm", "northflank", "gpt", "openai",
    "scout", "nvidia", "claude", "anthropic", "model",
]

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
    answer = shortcut_answer(classify("check 185.220.101[.]34 and evil[.]xyz"))
    assert answer.category is Category.IOC_CHECK
    assert "`185.220.101.34`" in answer.text  # normalized, not the defanged raw
    assert "`evil.xyz`" in answer.text
    assert "185.220.101[.]34" not in answer.text
    for o in classify("check 185.220.101[.]34 and evil[.]xyz").observables:
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
