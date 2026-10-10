"""Response modes (S9) — resolver priority (format beats keywords) + typed
contract compile/validate. Pure functions, no LLM, no network."""

from auspex.classify.observables import extract
from auspex.modes import (
    CONTRACTS,
    Mode,
    contract_for,
    resolve_mode,
)
from auspex.modes.contract import ContractField, ModeContract


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


def test_validate_pin_as_a_set_is_a_floor_not_a_lock():
    # S11: the phishing Verdict pin is an ALLOWED SET (floor + the raises the
    # model may make) — a member passes, a non-member (e.g. a launder to BENIGN
    # below a MALICIOUS floor) fails, even though BENIGN is a valid enum value.
    c = contract_for(Mode.PHISHING_ANALYSIS)

    def _v(token: str) -> str:
        return f"## Verdict\n{token}\n\n## Indicators\nx\n\n## Recommendation\ny\n"

    allowed = ("SUSPICIOUS", "MALICIOUS")
    assert c.validate(_v("MALICIOUS"), pinned={"Verdict": allowed}).ok  # raise: ok
    assert c.validate(_v("SUSPICIOUS"), pinned={"Verdict": allowed}).ok  # floor: ok
    bad = c.validate(_v("BENIGN"), pinned={"Verdict": allowed})
    assert not bad.ok  # laundered below the floor
    assert bad.pinned_mismatch and "BENIGN∉" in bad.pinned_mismatch[0]


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


def test_validate_accepts_an_emphasised_hyphenated_enum_value():
    """S14 Step 0, finding 3. A HYPHENATED allowed_value (the S13 pin tokens are
    the first in the codebase) took the compound branch of the leading-token
    parser, which returned the whole whitespace-delimited chunk — trailing
    markdown included — so "**TRUE-POSITIVE**" failed the enum AND the pin.
    Bolding a value is a rendering habit, not a different value, and Auspex runs
    on a customer-supplied model whose habits we do not control."""
    c = ModeContract(
        name="pin_probe",
        purpose="p",
        fields=(
            ContractField("Verdict", "d", allowed_values=("TRUE-POSITIVE", "NONE")),
            ContractField("Why", "d"),
        ),
    )
    for rendering in ("**TRUE-POSITIVE**", "_TRUE-POSITIVE_", "`TRUE-POSITIVE`",
                      "**TRUE-POSITIVE** — as computed", "TRUE-POSITIVE."):
        answer = f"## Verdict\n{rendering}\n\n## Why\nx\n"
        result = c.validate(answer, pinned={"Verdict": "TRUE-POSITIVE"})
        assert result.ok, f"{rendering}: {result.reason()}"


def test_emphasis_trim_still_rejects_a_hyphenated_hedge():
    """The guard rail on the fix above: trimming markdown must not rescue a real
    hedge. "/" and the inner hyphen are untouched, so the S9 false-accept the
    compound branch exists to prevent stays prevented."""
    c = contract_for(Mode.ALERT_TRIAGE)
    for hedged in ("**LOW/MEDIUM**", "**LOW-MEDIUM**", "*LOW/MEDIUM leaning low*"):
        result = c.validate(
            f"## Risk\n{hedged}\n\n## Reasoning\nx\n\n## Recommendation\ny\n"
        )
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


# -- D-043: the repair directive is compiled, never quoted --------------------


def test_the_repair_directive_names_fields_and_code_values_never_the_draft():
    """D-043: the re-ask after a failed held answer is compiled from the spec and
    the code's pins. The draft's own tokens are model output, possibly steered by
    the paste, and must never be lifted into a system message."""
    from auspex.modes.contract import ContractResult

    contract = contract_for(Mode.ALERT_TRIAGE)
    failed = ContractResult(
        mode="alert_triage",
        missing=("Recommendation",),
        bad_enum=("Risk=IGNOREPREVIOUS",),
        pinned_mismatch=("Risk=IGNOREPREVIOUS≠DEFERRED",),
    )

    directive = contract.repair_directive(failed, pinned={"Risk": "DEFERRED"})

    assert "IGNOREPREVIOUS" not in directive
    assert "## Recommendation" in directive and "## Risk" in directive
    assert 'The ## Risk section must begin with exactly "DEFERRED".' in directive


def test_the_repair_directive_says_an_empty_draft_was_empty_and_lists_a_pinned_set():
    contract = contract_for(Mode.PHISHING_ANALYSIS)

    directive = contract.repair_directive(None, pinned={"Verdict": ("SUSPICIOUS", "MALICIOUS")})

    assert "it was empty" in directive
    assert "The ## Verdict section must begin with one of: SUSPICIOUS, MALICIOUS." in directive


# -- D-044: a deep question with no security signal is answered as `general` --


def test_a_question_with_no_security_signal_resolves_to_general():
    """IDEAS (S26, measured 4x; S27 4x again): a status update for a manager
    resolved to threat_intel, whose contract it cannot meet."""
    assert resolve("Write me a status update for my manager about this week.") is Mode.GENERAL
    assert resolve("How do I convert a JSON file to CSV in Python?") is Mode.GENERAL


def test_a_security_situation_described_in_plain_words_keeps_its_structure():
    """Approach 1 (security words only) sent these to general; the resolver must
    read the IT and identity words an analyst describes a situation with."""
    for q in (
        "An admin account was created at 3am on Sunday and nobody admits to it.",
        "One of our laptops keeps reaching out to the same server every five minutes.",
        "Someone set up a rule in the CFO's mailbox that forwards anything to an outside address.",
    ):
        assert resolve(q) is Mode.THREAT_INTEL, q


def test_an_observable_alone_is_a_security_signal():
    """A prose mention of a common domain is not ioc-shaped (no enrichment), but
    an analyst who names infrastructure is not asking a general question."""
    q = "Tell me the long history of github.com and how its founders built it up, please."
    assert _obs(q) and resolve(q) is Mode.THREAT_INTEL


def test_the_general_contract_asks_for_no_structure_and_cannot_drift():
    general = contract_for(Mode.GENERAL)
    directive = general.system_directive()

    assert "No section structure is required" in directive and "## " not in directive
    assert general.validate("Here is a short status update.").ok


def _battery(name):
    import json
    from pathlib import Path

    path = Path(__file__).parents[1] / "docs" / "probes" / "s27-modes" / name
    return json.loads(path.read_text())


def test_the_measured_operating_point_on_the_independent_battery_holds():
    """D-044's numbers, from a battery an independent agent wrote AFTER the
    vocabulary was frozen (heldout2-battery.json): at most 9 of 50 security
    questions lose their structure, at least 24 of 30 non-security questions
    gain the general mode, and no non-security question stays threat_intel.
    A vocabulary edit that moves the point the wrong way fails here; one that
    improves it should move these bounds with a new probe log."""
    from auspex.classify import classify, shortcut_answer

    def deep_modes(questions):
        out = []
        for q in questions:
            c = classify(q)
            if shortcut_answer(c) is None:
                out.append(resolve_mode(q, c.observables))
        return out

    battery = _battery("heldout2-battery.json")
    security, non = deep_modes(battery["security"]), deep_modes(battery["non_security"])

    assert len(security) == 50 and len(non) == 30  # floors: nothing silently skipped
    assert security.count(Mode.GENERAL) <= 9
    assert non.count(Mode.GENERAL) >= 24
    assert non.count(Mode.THREAT_INTEL) == 0
