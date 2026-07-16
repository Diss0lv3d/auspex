"""Query classifier (S4 step 2) — every category + ambiguous-case tiebreaks.

The classifier is code-owned and deterministic; each assertion here pins a
routing decision. Bias rule under test: errors must fall toward DEEP (wrong
deep = wasted tokens; wrong shortcut = wrong answer).
"""

from auspex.classify import Category, ObservableType, classify


def _cat(query: str) -> Category:
    return classify(query).category


# -- greeting -----------------------------------------------------------------


def test_greetings():
    for q in ["hi", "Hello!", "hey there", "good morning", "greetings, Auspex"]:
        assert _cat(q) is Category.GREETING, q


def test_greeting_with_a_real_question_is_not_a_greeting():
    assert _cat("hi, what is dns tunneling?") is not Category.GREETING


def test_acknowledgements_and_farewells_reach_the_model():
    # mid-investigation "ok" may answer the model's question — canned greeting
    # copy would hijack the session (S4 review finding)
    for q in ["ok", "thanks", "Thank you so much!", "cool", "bye"]:
        assert _cat(q) is Category.DEEP, q


# -- identity -----------------------------------------------------------------


def test_identity_questions():
    for q in ["who are you?", "what are you", "are you an AI?", "what model are you",
              "who built you", "what's your name", "introduce yourself"]:
        assert _cat(q) is Category.IDENTITY, q


def test_identity_anchor_does_not_swallow_real_questions_mentioning_you():
    assert _cat("who are you seeing in the auth logs for host db-01") is not Category.IDENTITY


# -- ioc_check ----------------------------------------------------------------


def test_ioc_check_ip_hash_url_email():
    assert _cat("check 8.8.8.8") is Category.IOC_CHECK
    assert _cat("f" * 64) is Category.IOC_CHECK  # bare hash paste
    assert _cat("hxxps://evil[.]com/login") is Category.IOC_CHECK
    assert _cat("mail from bob[at]evil[.]com") is Category.IOC_CHECK
    assert _cat("is 185.220.101[.]34 clean") is Category.IOC_CHECK


def test_ioc_check_attaches_normalized_observables():
    c = classify("check 185.220.101[.]34 and evil[.]xyz")
    assert c.category is Category.IOC_CHECK
    assert [o.value for o in c.observables] == ["185.220.101.34", "evil.xyz"]


def test_bulk_ioc_paste_stays_on_fast_path():
    hashes = " ".join(f"{i:064x}" for i in range(30))
    c = classify(f"triage these: {hashes}")
    assert c.category is Category.IOC_CHECK
    assert len(c.observables) == 30


def test_bare_uncommon_domain_is_ioc_but_common_is_not():
    assert _cat("evil.xyz") is Category.IOC_CHECK
    assert _cat("google.com") is Category.DEEP
    assert _cat("check google.com") is Category.DEEP  # common stays non-IOC even with a verb
    assert _cat("check www.google.com") is Category.DEEP  # subdomains are just as common


def test_defanged_common_domain_is_deliberate_hence_ioc():
    assert _cat("google[.]com") is Category.IOC_CHECK


def test_domain_in_long_prose_needs_a_check_verb():
    long_no_verb = "our marketing team keeps mentioning partner-site.xyz in slack all day long"
    assert _cat(long_no_verb) is Category.DEEP
    assert _cat("can you check the reputation of partner-site.xyz for me please") \
        is Category.IOC_CHECK


def test_embedded_request_with_ip_routes_to_ioc_check():
    assert _cat("who are you and can you check 8.8.8.8") is Category.IOC_CHECK


# -- cve_lookup ---------------------------------------------------------------


def test_cve_lookup():
    assert _cat("CVE-2024-3400") is Category.CVE_LOOKUP
    assert _cat("what is cve-2021-44228") is Category.CVE_LOOKUP
    assert _cat("is CVE-2024-3400 exploited in the wild?") is Category.CVE_LOOKUP


def test_cve_plus_other_iocs_tiebreaks_to_ioc_check():
    c = classify(f"check {'a' * 64} related to CVE-2024-3400")
    assert c.category is Category.IOC_CHECK
    assert {o.type for o in c.observables} == {ObservableType.SHA256, ObservableType.CVE}


# -- definition ---------------------------------------------------------------


def test_definitions():
    assert _cat("what is dns tunneling") is Category.DEFINITION
    assert _cat("define beaconing") is Category.DEFINITION
    assert _cat("what's lateral movement?") is Category.DEFINITION


def test_definition_with_observable_is_not_a_definition():
    assert _cat("what is 8.8.8.8") is Category.IOC_CHECK  # format beats keywords


def test_long_definition_shaped_question_goes_deep():
    q = "what is the best way to structure a detection engineering team across three regions"
    assert _cat(q) is Category.DEEP


def test_analytical_definition_shaped_question_goes_deep():
    # "why" is an analytical marker — the veto beats the definition shape
    assert _cat("what is ransomware and why does it matter") is Category.DEEP


# -- deep: analytical veto ------------------------------------------------------


def test_analytical_queries_go_deep_even_with_observables():
    sha = "b" * 64
    assert _cat(f"analyze this hash {sha}") is Category.DEEP
    assert _cat("is this malicious: evil.xyz") is Category.DEEP
    assert _cat("why is 8.8.8.8 in my logs") is Category.DEEP
    assert _cat("investigate 185.220.101.34 and tell me what you find") is Category.DEEP


def test_long_prose_with_one_ioc_goes_deep():
    q = ("our EDR flagged a connection from 10.0.0.5 overnight but I think it might be "
         "the new proxy config rolling out, can you help me figure out what changed")
    assert _cat(q) is Category.DEEP


# -- deep: format beats keywords ------------------------------------------------


def test_alert_pastes_go_deep_regardless_of_iocs():
    assert _cat("CEF:0|Vendor|Product|1.0|100|intrusion|10|src=203.0.113.9") is Category.DEEP
    assert _cat("<134>Oct 11 22:14:15 host su: 'su root' failed for bob") is Category.DEEP
    assert _cat('{"alert": {"severity": "high", "src_ip": "203.0.113.9"}}') is Category.DEEP
    assert _cat("triage this CEF:0|X|Y|1|2|z|3| alert from overnight") is Category.DEEP


# -- deep: fallthrough ----------------------------------------------------------


def test_plain_questions_and_followups_go_deep():
    assert _cat("how do I write a sigma rule for beaconing") is Category.DEEP
    assert _cat("tell me more about the second one") is Category.DEEP
    assert _cat("summarize today's alerts") is Category.DEEP


def test_whitespace_only_goes_deep():
    assert _cat("   ") is Category.DEEP
