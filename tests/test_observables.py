"""Observable extraction + defang normalization (S4 step 1) — pure, hermetic.

Every case here is a pinned behavior of the code-owned fast path: defang
refanging, canonical normalization, double-extraction guards, and the
false-positive traps the SARA study flagged (versions-as-IPs, filenames-as-
domains, hash-length collisions).
"""

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
