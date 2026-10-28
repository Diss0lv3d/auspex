"""Observable extraction + defang normalization (S4 step 1) — pure, hermetic.

Every case here is a pinned behavior of the code-owned fast path: defang
refanging, canonical normalization, double-extraction guards, and the
false-positive traps the SARA study flagged (versions-as-IPs, filenames-as-
domains, hash-length collisions).
"""

import pytest

from auspex.classify import (
    Observable,
    ObservableType,
    extract,
    extract_observables,
    observable_id,
    refang,
)


def _values(text: str, type_: ObservableType) -> list[str]:
    return [o.value for o in extract_observables(text) if o.type is type_]


def _one(text: str, type_: ObservableType) -> Observable:
    matches = [o for o in extract_observables(text) if o.type is type_]
    assert len(matches) == 1, f"expected exactly one {type_}, got {matches}"
    return matches[0]


# -- refang -------------------------------------------------------------------


def test_refang_covers_the_common_defang_styles():
    assert refang("hxxp://evil[.]com/a") == "http://evil.com/a"
    assert refang("hxxps://evil[.]com") == "https://evil.com"
    assert refang("HXXPS://EVIL[.]COM") == "https://EVIL.COM"
    assert refang("evil(.)com") == "evil.com"
    assert refang("evil[dot]com") == "evil.com"
    assert refang("evil (dot) com") == "evil.com"
    assert refang("evil {.} com") == "evil.com"
    assert refang("bob[at]evil[.]com") == "bob@evil.com"
    assert refang("bob (at) evil (dot) com") == "bob@evil.com"
    assert refang("hxxp[:]//evil[.]com") == "http://evil.com"


def test_refang_is_idempotent_on_clean_text():
    clean = "check http://example.com and bob@corp.net"
    assert refang(clean) == clean


# -- IPv4 ---------------------------------------------------------------------


def test_ipv4_plain_and_defanged():
    assert _one("check 8.8.8.8", ObservableType.IPV4).value == "8.8.8.8"
    obs = _one("check 185.220.101[.]34 please", ObservableType.IPV4)
    assert obs.value == "185.220.101.34"
    assert obs.defanged is True


def test_ipv4_clean_input_is_not_flagged_defanged():
    assert _one("check 8.8.8.8", ObservableType.IPV4).defanged is False


def test_ipv4_invalid_octets_rejected():
    assert _values("host at 999.1.1.1 responded", ObservableType.IPV4) == []


def test_ipv4_version_strings_rejected():
    assert _values("upgrade to version 1.2.3.4 now", ObservableType.IPV4) == []
    assert _values("running v1.2.3.4", ObservableType.IPV4) == []
    assert _values("openssl build 3.0.2.1", ObservableType.IPV4) == []
    assert _values("release 1.2.3.4 fixes it", ObservableType.IPV4) == []
    # five dotted groups is a version, not an IP + junk
    assert _values("agent 1.2.3.4.5 deployed", ObservableType.IPV4) == []


def test_ipv4_after_cli_verbose_flag_is_not_a_version():
    assert _one("ran nmap -v 10.0.0.1 yesterday", ObservableType.IPV4).value == "10.0.0.1"


def test_ipv4_with_port_cidr_and_trailing_defang_dot():
    assert _one("conn to 10.0.0.1:8080", ObservableType.IPV4).value == "10.0.0.1"
    assert _one("block 203.0.113.0/24", ObservableType.IPV4).value == "203.0.113.0"
    assert _one("beacon to 203.0.113.7.", ObservableType.IPV4).value == "203.0.113.7"


# -- IPv6 ---------------------------------------------------------------------


def test_ipv6_full_compressed_and_canonicalized():
    assert _one("from 2001:db8::1 inbound", ObservableType.IPV6).value == "2001:db8::1"
    # full form canonicalizes to compressed lowercase
    obs = _one("src 2001:0DB8:0000:0000:0000:0000:0000:0001", ObservableType.IPV6)
    assert obs.value == "2001:db8::1"
    assert _one("ping ::1 locally", ObservableType.IPV6).value == "::1"


def test_ipv6_look_alikes_rejected():
    assert _values("at 12:30:45 the alert fired", ObservableType.IPV6) == []
    assert _values("mac 00:11:22:33:44:55 seen", ObservableType.IPV6) == []
    assert _values("use std::vector or :: scope", ObservableType.IPV6) == []


def test_ipv6_with_trailing_sentence_period_still_extracts():
    assert _one("Block 2001:db8::1.", ObservableType.IPV6).value == "2001:db8::1"


def test_ipv6_v4_mapped_extracts_once_as_ipv6():
    result = extract_observables("hit from ::ffff:203.0.113.9 today")
    # stdlib canonical (hex) compression — same address ⇒ same value ⇒ same obs_id
    assert [o.value for o in result if o.type is ObservableType.IPV6] == ["::ffff:cb00:7109"]
    assert [o for o in result if o.type is ObservableType.IPV4] == []


# -- domains ------------------------------------------------------------------


def test_domain_plain_defanged_and_multilabel():
    assert _one("lookup evil.xyz now", ObservableType.DOMAIN).value == "evil.xyz"
    obs = _one("callback to c2[.]badguy[.]top", ObservableType.DOMAIN)
    assert obs.value == "c2.badguy.top"
    assert obs.defanged is True
    assert _one("seen at a.b.evil.xyz", ObservableType.DOMAIN).value == "a.b.evil.xyz"


def test_domain_normalizes_case_and_ignores_trailing_dot():
    assert _one("check EVIL.XYZ", ObservableType.DOMAIN).value == "evil.xyz"
    assert _one("check evil.xyz.", ObservableType.DOMAIN).value == "evil.xyz"


def test_domain_filenames_and_unknown_tlds_rejected():
    assert _values("open report.pdf and setup.exe", ObservableType.DOMAIN) == []
    assert _values("host server01.prod.internal is fine", ObservableType.DOMAIN) == []


def test_domain_backtracks_past_internal_suffix():
    assert _one("resolved evil.com.internal today", ObservableType.DOMAIN).value == "evil.com"


def test_domain_spaced_defang():
    assert _one("visit evil [.] xyz please", ObservableType.DOMAIN).value == "evil.xyz"


# -- URLs ---------------------------------------------------------------------


def test_url_defanged_normalized_and_host_not_double_extracted():
    result = extract_observables("visit hxxps://Evil[.]Com/Payload.EXE now")
    urls = [o for o in result if o.type is ObservableType.URL]
    assert len(urls) == 1
    # scheme + host lowercased, path case preserved, refanged
    assert urls[0].value == "https://evil.com/Payload.EXE"
    assert urls[0].defanged is True
    assert [o for o in result if o.type is ObservableType.DOMAIN] == []


def test_url_trailing_punctuation_stripped():
    assert _one("see http://evil.xyz/a.", ObservableType.URL).value == "http://evil.xyz/a"
    assert _one("(see http://evil.xyz/a)", ObservableType.URL).value == "http://evil.xyz/a"


def test_url_with_ip_host_suppresses_separate_ip():
    result = extract_observables("payload at http://203.0.113.9/mal.exe")
    assert [o.value for o in result if o.type is ObservableType.URL] == [
        "http://203.0.113.9/mal.exe"
    ]
    assert [o for o in result if o.type is ObservableType.IPV4] == []


def _b018_inputs() -> list[dict]:
    import json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "classify" / "b018_url_credentials.json"
    return json.loads(path.read_text())["inputs"]


@pytest.mark.parametrize("case", _b018_inputs(), ids=lambda c: c["url"])
def test_a_urls_credentials_are_dropped_before_it_is_an_observable(case):
    """B-018: the value is what is looked up at URLhaus and stored, so `user:pass@`
    never reaches it. An `@` after the host (path or query) is not userinfo."""
    url = _one(case["text"], ObservableType.URL)
    assert url.value == case["url"]
    assert "PLACEHOLDER" not in url.value
    assert url.obs_id == observable_id(ObservableType.URL, case["url"])


def test_hash_inside_url_is_still_extracted():
    sha = "a" * 64
    result = extract_observables(f"see https://intel.example.com/file/{sha}")
    assert [o.value for o in result if o.type is ObservableType.SHA256] == [sha]


# -- hashes -------------------------------------------------------------------


def test_hashes_extracted_by_length_and_lowercased():
    sha256 = "A" * 63 + "b"
    sha1 = "b" * 40
    md5 = "c" * 32
    text = f"hashes: {sha256} {sha1} {md5}"
    result = extract_observables(text)
    assert [o.value for o in result if o.type is ObservableType.SHA256] == [sha256.lower()]
    assert [o.value for o in result if o.type is ObservableType.SHA1] == [sha1]
    assert [o.value for o in result if o.type is ObservableType.MD5] == [md5]


def test_hash_length_collision_yields_single_observable():
    # a 64-hex token is one SHA-256, never also a SHA-1/MD5
    result = extract_observables("check " + "d" * 64)
    assert [o.type for o in result] == [ObservableType.SHA256]


def test_hex_run_of_wrong_length_is_no_hash():
    assert extract_observables("blob " + "e" * 63) == []
    assert extract_observables("blob " + "e" * 65) == []


# -- emails -------------------------------------------------------------------


def test_email_plain_and_defanged_lowercased():
    assert _one("mail from Bob@Corp.NET", ObservableType.EMAIL).value == "bob@corp.net"
    obs = _one("sender bob[at]evil[.]com", ObservableType.EMAIL)
    assert obs.value == "bob@evil.com"
    assert obs.defanged is True


def test_curly_brace_defang_covers_at_too():
    assert _one("sender bob{at}evil{.}com", ObservableType.EMAIL).value == "bob@evil.com"


def test_email_domain_not_double_extracted():
    result = extract_observables("phish from ceo@evil.xyz")
    assert [o.value for o in result if o.type is ObservableType.EMAIL] == ["ceo@evil.xyz"]
    assert [o for o in result if o.type is ObservableType.DOMAIN] == []


# -- CVEs ---------------------------------------------------------------------


def test_cve_extracted_and_uppercased():
    assert _one("patch cve-2021-44228 asap", ObservableType.CVE).value == "CVE-2021-44228"
    assert _one("is CVE-2024-3400 exploited?", ObservableType.CVE).value == "CVE-2024-3400"


def test_cve_inside_url_still_extracted():
    result = extract_observables("see https://nvd.nist.gov/vuln/detail/CVE-2024-3400")
    assert [o.value for o in result if o.type is ObservableType.CVE] == ["CVE-2024-3400"]


# -- ids, ordering, dedup, residual --------------------------------------------


def test_obs_id_is_short_deterministic_and_type_prefixed():
    a = observable_id(ObservableType.SHA256, "a" * 64)
    b = observable_id(ObservableType.SHA256, "a" * 64)
    assert a == b
    assert a.startswith("sha256-")
    assert len(a) <= 16  # tool-arg friendly, never the raw 64-char string
    assert observable_id(ObservableType.MD5, "a" * 32) != a
    extracted = _one("check 8.8.8.8", ObservableType.IPV4)
    assert extracted.obs_id == observable_id(ObservableType.IPV4, "8.8.8.8")


def test_duplicates_dedup_to_first_occurrence():
    result = extract_observables("8.8.8.8 again 8.8.8.8 and 8.8.8[.]8")
    assert [o.value for o in result] == ["8.8.8.8"]
    assert result[0].defanged is True  # any defanged appearance is deliberate signal


def test_defanged_flag_survives_a_lookalike_substring():
    # "evil.com" is a substring of "devil.com" — the flag must not be fooled
    result = extract_observables("evil[.]com redirects to devil.com")
    flags = {o.value: o.defanged for o in result}
    assert flags == {"evil.com": True, "devil.com": False}


def test_observables_come_back_in_text_order():
    text = "CVE-2024-3400 then evil.xyz then 8.8.8.8"
    assert [o.type for o in extract_observables(text)] == [
        ObservableType.CVE,
        ObservableType.DOMAIN,
        ObservableType.IPV4,
    ]


def test_residual_blanks_observables_but_keeps_words():
    extraction = extract("please check 8.8.8.8 and evil[.]xyz for me")
    assert "8.8.8.8" not in extraction.residual
    assert "evil" not in extraction.residual
    assert extraction.residual == "please check and for me"


def test_bulk_ioc_paste_leaves_tiny_residual():
    hashes = " ".join(f"{i:064x}" for i in range(20))
    extraction = extract(f"triage these: {hashes}")
    assert len(extraction.observables) == 20
    assert extraction.residual == "triage these:"


def test_no_observables_in_plain_prose():
    assert extract_observables("how do I write a detection rule for beaconing") == []


def test_ipv4_mapped_ipv6_identity_does_not_move_with_the_interpreter():
    """S20 — found by the CI gate on its first run, green locally and red on a
    different 3.12 patch release.

    `observable_id` hashes the VALUE, so whatever text an address normalizes to
    IS that observable's identity — and identity is what every verdict, decay
    curve, watcher and retro-hunt match hangs off. The old code used
    `ip.compressed`, which is a stdlib FORMATTING choice: CPython renders
    IPv4-mapped addresses in mixed notation on newer patch releases. A silent
    interpreter upgrade would have forked every IPv4-mapped observable into a
    second identity and split its verdict history.

    This asserts the value WITHOUT consulting the stdlib for the expectation,
    which is the only way the test can fail when the stdlib changes.
    """
    result = extract_observables("hit from ::ffff:203.0.113.9 today")
    values = [o.value for o in result if o.type is ObservableType.IPV6]
    assert values == ["::ffff:cb00:7109"]
    assert [o for o in result if o.type is ObservableType.IPV4] == []
    # The identity that hangs off it, pinned verbatim.
    assert observable_id(ObservableType.IPV6, values[0]) == observable_id(
        ObservableType.IPV6, "::ffff:cb00:7109"
    )


def test_every_spelling_of_one_ipv4_mapped_address_is_one_observable():
    """The property the canonical form exists to give: the same address written
    three ways is one identity, not three."""
    spellings = [
        "::ffff:203.0.113.9",
        "::ffff:cb00:7109",
        "0:0:0:0:0:ffff:cb00:7109",
    ]
    ids = {
        observable_id(ObservableType.IPV6, _one(f"see {s} now", ObservableType.IPV6).value)
        for s in spellings
    }
    assert len(ids) == 1, ids


def test_ordinary_ipv6_compression_is_untouched():
    """The canonical form only overrides the IPv4-mapped case; everything else
    still goes through the stdlib, which is stable for it."""
    for text, expected in [
        ("see 2001:0db8:0000:0000:0000:0000:0000:0001 now", "2001:db8::1"),
        ("see fe80::1 now", "fe80::1"),
        ("see 2001:db8:0:0:1:0:0:1 now", "2001:db8::1:0:0:1"),
    ]:
        assert _one(text, ObservableType.IPV6).value == expected, text


def test_our_canonical_ipv6_agrees_with_the_stdlib():
    """The measurement that justified taking IPv6 identity off `ip.compressed`,
    kept running.

    Two properties, and they pull in opposite directions on purpose. The form
    must AGREE with the stdlib today — otherwise adopting it would silently
    re-key every existing IPv6 observable — and it must not CONSULT the stdlib,
    or it inherits a formatting policy that has already moved once.

    Seeded, so a failure is reproducible rather than a flake.
    """
    import ipaddress
    import random

    from auspex.classify.observables import _canonical_ipv6

    # Seeded and deterministic: this samples the address space, it does not
    # generate anything a secret depends on.
    rng = random.Random(20260815)  # noqa: S311
    addresses = [rng.getrandbits(128) for _ in range(5000)]
    addresses += [0, 1, (0xFFFF << 32) | 0xCB007109, 0x20010DB8 << 96]
    # structured sweeps: zero-runs, IPv4-mapped, IPv4-compatible, leading group
    for i in range(0, 65536, 997):
        addresses += [(0xFFFF << 32) | i, i, i << 112, (0x20010DB8 << 96) | i]

    differs, not_roundtrip = [], []
    for n in addresses:
        ip = ipaddress.IPv6Address(n)
        ours = _canonical_ipv6(ip)
        if ipaddress.IPv6Address(ours) != ip:
            not_roundtrip.append((str(ip), ours))
        if ip.ipv4_mapped is None and ours != ip.compressed:
            differs.append((ip.compressed, ours))

    assert not not_roundtrip, f"canonical form lost the address: {not_roundtrip[:5]}"
    assert not differs, f"disagrees with the stdlib on unmapped addresses: {differs[:5]}"


# -- B-010: the refang, domain and email scans cannot backtrack ----------------
# extract() runs on the chat route's event loop, so a rule that backtracks on
# crafted input stalls every request on the worker. Measured at B3 at the
# 32,000-character cap: 16 s for the refang [.] rule on a run of spaces, 49 s
# for the domain rule and 4 s for the email rule on "a." repeated
# (docs/probes/b3-b010/). The timed inputs are 8,000
# characters, so a regressed rule fails in seconds instead of hanging the gate.

import random  # noqa: E402
import re  # noqa: E402

from _timing import BOUNDED_MS as _BOUNDED_MS  # noqa: E402
from _timing import elapsed_ms as _elapsed_ms  # noqa: E402

from auspex.classify import observables as _O  # noqa: E402

# The rules exactly as they stood before B-010, kept to prove the fix changed
# how they match, never what.
_BEFORE_B010 = {
    "refang_dot": re.compile(r"\s*[\[({]\s*(?:\.|dot)\s*[\])}]\s*", re.IGNORECASE),
    "refang_at": re.compile(r"\s*[\[({]\s*(?:@|at)\s*[\])}]\s*", re.IGNORECASE),
    "domain": re.compile(
        r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b", re.IGNORECASE
    ),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b"),
}


def _after_b010(name: str, text: str) -> list[tuple[int, int]]:
    if name == "refang_dot":
        return [m.span() for m in _O._REFANG_RULES[2][0].finditer(text)]
    if name == "refang_at":
        return [m.span() for m in _O._REFANG_RULES[3][0].finditer(text)]
    if name == "domain":
        return [m.span() for m in _O._domain_candidates(text)]
    return [m.span() for m in _O._email_candidates(text)]




def test_b010_refang_does_not_backtrack_on_a_whitespace_run():
    for q in ("x" + " " * 7998 + "x", "x" + "\t \n" * 2666 + "x"):
        assert _elapsed_ms(refang, q) < _BOUNDED_MS, repr(q[:8])


def test_b010_extract_does_not_backtrack_on_a_dotted_run():
    for unit in ("a.", "a-b."):
        q = unit * (8000 // len(unit))
        assert _elapsed_ms(extract, q) < _BOUNDED_MS, unit


def test_b010_the_rules_still_find_what_they_found():
    """The fix changes how the rules match, not what. The S29 review's caution
    is pinned first: a candidate starting mid-run must still be found when the
    run's earlier labels cannot carry it."""
    assert _values("Block evil.com.", ObservableType.DOMAIN) == ["evil.com"]
    assert _values("seen at my_host.evil.com today", ObservableType.DOMAIN) == ["evil.com"]
    assert _values("a-.evil.com", ObservableType.DOMAIN) == ["evil.com"]
    assert _values("x" * 70 + ".evil.com", ObservableType.DOMAIN) == ["evil.com"]
    assert _values("mail bob.smith@evil.com now", ObservableType.EMAIL) == ["bob.smith@evil.com"]
    assert _values("..bob@evil.com", ObservableType.EMAIL) == ["bob@evil.com"]
    assert refang("evil   [ . ]   com and bob [at] evil [dot] com") == "evil.com and bob@evil.com"
    assert refang("[.]   [.]") == ".."


def test_b010_each_rule_matches_exactly_what_it_matched_before():
    """A seeded differential fuzz: the rules before B-010 against the rules
    after it, on short strings built from the characters that steer them
    (brackets, dots, hyphens, '@', whitespace, '_', a non-ASCII letter, the
    Kelvin sign that IGNORECASE folds to 'k'). Its strings stay under 41
    characters, so the 63-character label limit is left to the pinned case
    above and to the probe's larger fuzz (docs/probes/b3-b010/diff_fuzz.py)."""
    alphabet = "ab1-._@ \t\n[](){}dotDOTatcom%+éK,"
    rng = random.Random(1010)  # noqa: S311 -- a seeded fuzz, not a secret
    for _ in range(4000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        for name, before in _BEFORE_B010.items():
            assert _after_b010(name, text) == [m.span() for m in before.finditer(text)], (
                name, text,
            )


# -- B-027: the overlap checks are O(log spans), and find what they found -------
# Every span set `extract` checks against is disjoint, so a sorted index answers
# "does this match overlap one?" by bisection. Before, each check walked every span,
# so 4x the matches cost 8-14x the time (about a second for 4,571 emails); now 4x
# costs 2.4-4.6x (docs/probes/2026-10-28-b4-b027.md). Growth, not a wall-clock bound,
# is what is pinned: the linear rest of the pass (refang, building observables) is
# not this bug's, and a slow runner scales both sizes alike.
B027_MAX_GROWTH = 6.5
B027_INPUTS = {
    "emails": ("a@b.co ", 4571),
    "url+ip": ("http://a 1.2.3.4 ", 1882),
    "url+domain": ("http://a b.co ", 2285),
}


@pytest.mark.parametrize("name", sorted(B027_INPUTS))
def test_b027_extract_grows_linearly_in_its_matches(name):
    unit, repeat = B027_INPUTS[name]
    assert len(unit * repeat) <= 32_000
    growth = _elapsed_ms(extract, unit * repeat) / _elapsed_ms(extract, unit * (repeat // 4))
    assert growth < B027_MAX_GROWTH, f"{name}: 4x the input took {growth:.1f}x the time"


class _NaiveSpans:
    """The pre-B-027 check, kept as the reference: every span, every time."""

    def __init__(self, spans=()):
        self._spans = list(spans)

    def add(self, start, end):
        self._spans.append((start, end))

    def overlaps(self, start, end):
        return any(start < s_end and end > s_start for s_start, s_end in self._spans)

    def __add__(self, other):
        return _NaiveSpans(self._spans + other._spans)


def test_b027_the_index_finds_exactly_what_the_walk_found(monkeypatch):
    """Differential: random mixes of every observable shape, extracted with the
    index and with the walk, give the same observables and residual."""
    import auspex.classify.observables as obs

    pieces = ["a@b.co", "http://a", "http://u@x.co/p", "1.2.3.4", "b.co", "evil.com",
              "::1", "fe80::1", "d41d8cd98f00b204e9800998ecf8427e", "CVE-2024-1234",
              "x@evil[.]com", "hxxp://y.io/z", "a" * 64, "0" * 40, " ", "\n", ".", "@"]
    rng = random.Random(27)  # noqa: S311 -- a fixed-seed fuzz, not a secret
    texts = ["".join(rng.choice(pieces) for _ in range(rng.randint(1, 60)))
             for _ in range(400)]
    fast = [extract(t) for t in texts]
    monkeypatch.setattr(obs, "_Spans", _NaiveSpans)
    slow = [extract(t) for t in texts]
    assert fast == slow
