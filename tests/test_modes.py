"""Response modes (S9) — resolver priority (format beats keywords) + typed
contract compile/validate. Pure functions, no LLM, no network."""

from auspex.classify.observables import extract
from auspex.modes import (
    CONTRACTS,
    Mode,
    contract_for,
    resolve_mode,
)


def _obs(message: str):
    return extract(message).observables


def resolve(message: str) -> Mode:
    return resolve_mode(message, _obs(message))


# ── resolver: format beats keywords (the load-bearing rule) ──────────────────


def test_alert_paste_is_triage_even_when_it_mentions_phishing():
    # CEF envelope + the word "phishing" → ALERT_TRIAGE (format wins)
    cef = "CEF:0|Vendor|Product|1.0|100|phishing email blocked|5|src=10.0.0.1"
    assert resolve(cef) is Mode.ALERT_TRIAGE


def test_syslog_and_json_pastes_are_triage():
    syslog = "<134>1 2026-07-18T00:00:00Z host app - - - suspicious login"
    assert resolve(syslog) is Mode.ALERT_TRIAGE
    js = '{"event": "alert", "severity": "high", "src_ip": "1.2.3.4"}'
    assert resolve(js) is Mode.ALERT_TRIAGE


def test_email_paste_is_phishing_even_when_it_mentions_a_cve():
    email = (
        "From: ceo@examp1e.com\n"
        "To: finance@company.com\n"
        "Subject: URGENT wire re CVE-2021-44228 patch invoice\n"
        "\n"
        "Please action the attached immediately."
    )
    assert resolve(email) is Mode.PHISHING_ANALYSIS


def test_one_email_header_is_not_a_paste():
    # prose that happens to start "Subject:" once is not an email envelope
    assert resolve("Subject: explain how BEC scams work") is not Mode.PHISHING_ANALYSIS


def test_observable_present_is_ioc_enrichment_over_keywords():
    # a hash present + the word "malware" → IOC_ENRICHMENT (observable beats the
    # threat_intel keyword)
    q = "is this malware? 44d88612fea8a8f36de82e1278abb02f"
    assert resolve(q) is Mode.IOC_ENRICHMENT


def test_scoreable_ioc_beats_a_brief_ask():
    # format/observable (tier 3) beats the BRIEF keyword (tier 4): an IP to look
    # at wins over "summarize". Pins the ioc>brief boundary (S9 review, T-F1).
    assert resolve("summarize the recent activity from 8.8.8.8") is Mode.IOC_ENRICHMENT


def test_common_domain_in_prose_is_not_a_scoreable_ioc():
    # S9 review (correctness): the naive any(non-CVE) hijacked ordinary prose
    # mentioning a ubiquitous domain into IOC_ENRICHMENT, shadowing BRIEF/intel.
    # The resolver now reuses the classifier's ioc-shaping (common-domain exempt).
    assert resolve("give me a brief on why campaigns abuse microsoft.com branding") is Mode.BRIEF
    assert (
        resolve("why are we seeing so much traffic to github.com from the DMZ")
        is Mode.THREAT_INTEL
    )
    # a non-ubiquitous domain under a check verb is still a real indicator
    assert resolve("check the reputation of evil-c2-domain.xyz") is Mode.IOC_ENRICHMENT


def test_bare_cve_is_threat_intel_not_ioc_enrichment():
    # a CVE alone is threat framing, not indicator enrichment
    assert resolve("tell me about CVE-2021-44228 and its exploitation") is Mode.THREAT_INTEL


def test_brief_ask_resolves_to_brief():
    assert resolve("give me a brief on the Volt Typhoon activity") is Mode.BRIEF
    assert resolve("summarize the latest ransomware trends") is Mode.BRIEF


def test_definition_shape_resolves_to_definition():
    assert resolve("what is lateral movement in an intrusion") is Mode.DEFINITION
    assert resolve("define command and control") is Mode.DEFINITION


def test_threat_intel_keywords_and_default():
    assert resolve("what do we know about APT29's recent campaigns") is Mode.THREAT_INTEL
    # a general analytical question with no format/observable/keyword → default
    assert resolve("walk me through how this incident likely unfolded") is Mode.THREAT_INTEL


def test_brief_beats_definition_when_both_shapes_present():
    # "what is X" opener but an explicit brief ask — brief has higher priority
    assert resolve("what is Volt Typhoon — give me a brief") is Mode.BRIEF


# ── contract compilation (specs → prompts) ───────────────────────────────────


def test_every_mode_has_a_contract():
    assert set(CONTRACTS) == set(Mode)


def test_system_directive_names_the_mode_and_required_sections():
    c = contract_for(Mode.ALERT_TRIAGE)
    directive = c.system_directive()
    assert "alert_triage mode" in directive
    assert "## Risk" in directive and "## Reasoning" in directive
    # the enum values are compiled into the prompt
    assert "DEFERRED" in directive and "CRITICAL" in directive
    # the DEFERRED rail rule is injected
    assert "No data ≠ low risk" in directive


# ── contract validation (specs → validators) ─────────────────────────────────


def test_validate_accepts_a_conformant_answer():
    c = contract_for(Mode.ALERT_TRIAGE)
    answer = (
        "## Risk\nHIGH\n\n"
        "## Reasoning\nKnown-malicious source IP and a LOLBin execution.\n\n"
        "## Recommendation\nContain the host and escalate.\n"
    )
    result = c.validate(answer)
    assert result.ok, result.reason()


def test_validate_flags_missing_required_section():
    c = contract_for(Mode.ALERT_TRIAGE)
    answer = "## Risk\nHIGH\n\n## Reasoning\nbecause.\n"  # no Recommendation
    result = c.validate(answer)
    assert not result.ok
    assert "Recommendation" in result.missing


def test_validate_flags_out_of_enum_risk_value():
    c = contract_for(Mode.ALERT_TRIAGE)
    answer = "## Risk\nPROBABLY BAD\n\n## Reasoning\nx\n\n## Recommendation\ny\n"
    result = c.validate(answer)
    assert not result.ok
    assert any(b.startswith("Risk=") for b in result.bad_enum)


def test_validate_pins_a_field_to_the_code_verdict():
    # S11 review of S10 (finding A): enum MEMBERSHIP alone let a steered model
    # swap one valid Risk level for another with contract_valid=true. A pinned
    # field must EQUAL the code-computed verdict — checked in code, not by
    # prompt (ADR 0006).
    c = contract_for(Mode.ALERT_TRIAGE)
    steered = "## Risk\nLOW\n\n## Reasoning\nx\n\n## Recommendation\ny\n"
    result = c.validate(steered, pinned={"Risk": "DEFERRED"})
    assert not result.ok
    assert result.pinned_mismatch == ("Risk=LOW≠DEFERRED",)
    assert "code-verdict mismatch" in result.reason()


def test_validate_pinned_match_passes_in_every_header_shape():
    c = contract_for(Mode.ALERT_TRIAGE)
    for lead in ("## Risk\nDEFERRED", "## Risk: DEFERRED", "## **Risk**\nDEFERRED"):
        answer = f"{lead}\n\n## Reasoning\nx\n\n## Recommendation\ny\n"
        result = c.validate(answer, pinned={"Risk": "DEFERRED"})
        assert result.ok, result.reason()


def test_deferred_is_a_valid_alert_triage_risk_value():
    # "no data ≠ low risk": DEFERRED must be an in-contract value from day one
    c = contract_for(Mode.ALERT_TRIAGE)
    answer = (
        "## Risk\nDEFERRED — insufficient signal to score\n\n"
        "## Reasoning\nNo severity, no enrichment, no IOCs, no MITRE mapping.\n\n"
        "## Recommendation\nEscalate to enrichment + deep triage before disposition.\n"
    )
    result = c.validate(answer)
    assert result.ok, result.reason()


def test_optional_section_absence_is_ok():
    c = contract_for(Mode.DEFINITION)  # "Related" is optional
    answer = "## Definition\nX is Y.\n\n## In practice\nSeen in Z.\n"
    assert c.validate(answer).ok


# ── validator robustness (S9 review: spec↔validator drift, honest checks) ─────


def test_validate_accepts_inline_and_emphasized_enum_headers():
    # the compiled directive renders `## Risk — description`, and models commonly
    # write `## Risk: HIGH` or `## **Risk**` — all must validate (header tolerance
    # the docstring promised but the code did not implement).
    c = contract_for(Mode.ALERT_TRIAGE)
    for risk_section in ("## Risk: HIGH", "## Risk — HIGH", "## **Risk**\nHIGH"):
        answer = f"{risk_section}\n\n## Reasoning\nx\n\n## Recommendation\ny\n"
        assert c.validate(answer).ok, risk_section


def test_validate_rejects_a_compound_hedged_enum_value():
    # "Must be exactly one of" — a hedge whose first token spells an allowed value
    # is NOT one of them; the leading-token check must not pass it (false-accept).
    c = contract_for(Mode.ALERT_TRIAGE)
    for hedged in ("LOW/MEDIUM leaning low", "LOW-MEDIUM"):
        answer = f"## Risk\n{hedged}\n\n## Reasoning\nx\n\n## Recommendation\ny\n"
        result = c.validate(answer)
        assert not result.ok, hedged
        assert any(b.startswith("Risk=") for b in result.bad_enum)


def test_validate_flags_a_required_section_that_is_present_but_empty():
    # a headers-only skeleton (section emitted, no content) is not conformant.
    c = contract_for(Mode.ALERT_TRIAGE)
    answer = "## Risk\nHIGH\n\n## Reasoning\n\n## Recommendation\n"
    result = c.validate(answer)
    assert not result.ok
    assert "Reasoning" in result.missing and "Recommendation" in result.missing


def test_single_hash_code_comment_is_not_parsed_as_a_section():
    # a `# details` comment inside answer prose must NOT satisfy the missing
    # `## Details` section — only `##…` ATX headings are sections.
    c = contract_for(Mode.BRIEF)
    answer = "## Bottom line\nX.\n\n# details\nnot a real section\n"
    result = c.validate(answer)
    assert not result.ok
    assert "Details" in result.missing


def test_duplicate_header_keeps_the_first_section():
    # a later `## Risk` cannot silently override the first (first-wins).
    c = contract_for(Mode.ALERT_TRIAGE)
    answer = (
        "## Risk\nHIGH\n\n## Reasoning\nx\n\n## Recommendation\ny\n\n"
        "## Risk\nthis late duplicate must not win\n"
    )
    assert c.validate(answer).ok
