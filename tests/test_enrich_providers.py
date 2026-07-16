"""Provider clients vs saved probe fixtures — S5, hermetic (httpx.MockTransport).

Every fixture body below is copied (trimmed) from a LIVE response captured in
docs/probes/2026-07-16-enrichment-providers.md, except where marked
`docs-coded` (abuse.ch + AbuseIPDB happy paths are key-gated and unverified
live — the clients must therefore fail SOFT on shape drift).
"""

import json

import httpx
import pytest

from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.enrich.providers.abuseipdb import AbuseIPDB
from auspex.enrich.providers.greynoise import GreyNoise
from auspex.enrich.providers.hashlookup import Hashlookup
from auspex.enrich.providers.internetdb import InternetDB
from auspex.enrich.providers.otx import OTX
from auspex.enrich.providers.threatfox import ThreatFox
from auspex.enrich.providers.urlhaus import URLhaus
from auspex.enrich.types import ProviderError, VerdictLabel


def obs(type_: ObservableType, value: str) -> Observable:
    return Observable(type=type_, value=value, obs_id=observable_id(type_, value), defanged=False)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_response(status: int, body) -> httpx.Response:
    return httpx.Response(status, json=body)


async def lookup(provider, observable, handler):
    async with client_for(handler) as client:
        return await provider.lookup(client, observable)


# -- InternetDB (probe §1, live-verified) --------------------------------------

INTERNETDB_8888 = {
    "cpes": [],
    "hostnames": ["dns.google", "dev.slf.edf.fr"],
    "ip": "8.8.8.8",
    "ports": [53, 443],
    "tags": [],
    "vulns": [],
}
INTERNETDB_404 = {"detail": "No information available"}


async def test_internetdb_ports_are_context_not_a_verdict():
    def handler(request):
        assert request.url == "https://internetdb.shodan.io/8.8.8.8"
        return json_response(200, INTERNETDB_8888)

    signal = await lookup(InternetDB(), obs(ObservableType.IPV4, "8.8.8.8"), handler)
    assert signal.label is VerdictLabel.UNKNOWN  # open ports are not malice
    assert signal.confidence == 0.0
    assert "53, 443" in signal.summary and "dns.google" in signal.summary


async def test_internetdb_vulns_lean_suspicious():
    body = {**INTERNETDB_8888, "vulns": ["CVE-2023-44487"]}  # derived from probed shape
    signal = await lookup(
        InternetDB(), obs(ObservableType.IPV4, "8.8.8.8"), lambda r: json_response(200, body)
    )
    assert signal.label is VerdictLabel.SUSPICIOUS
    assert "CVE-2023-44487" in signal.summary


async def test_internetdb_404_is_no_data_not_an_error():
    signal = await lookup(
        InternetDB(),
        obs(ObservableType.IPV4, "192.0.2.1"),
        lambda r: json_response(404, INTERNETDB_404),
    )
    assert signal is None


async def test_internetdb_5xx_is_a_provider_error():
    with pytest.raises(ProviderError):
        await lookup(
            InternetDB(),
            obs(ObservableType.IPV4, "8.8.8.8"),
            lambda r: httpx.Response(503, text="upstream down"),
        )


# -- CIRCL hashlookup (probe §2, live-verified) --------------------------------

HASHLOOKUP_KNOWN = {  # trimmed from the live empty-file response
    "FileName": "./usr/lib/python3/dist-packages/zzzeeksphinx-1.0.20.egg-info/requires.txt",
    "MD5": "D41D8CD98F00B204E9800998ECF8427E",
    "ProductCode": {"ProductName": "Adobe Photoshop 4.0 Application CD-ROM"},
    "db": "nsrl_legacy",
    "hashlookup:trust": 100,
}
EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"


async def test_hashlookup_hit_is_weak_benign_evidence():
    def handler(request):
        assert str(request.url) == f"https://hashlookup.circl.lu/lookup/md5/{EMPTY_MD5}"
        return json_response(200, HASHLOOKUP_KNOWN)

    signal = await lookup(Hashlookup(), obs(ObservableType.MD5, EMPTY_MD5), handler)
    assert signal.label is VerdictLabel.BENIGN
    assert signal.confidence == 0.5  # capped: known-file is weak evidence
    assert "known distributed file" in signal.summary


async def test_hashlookup_routes_by_hash_type():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return json_response(404, {"message": "Non existing SHA-1"})

    sha1 = "a" * 40
    await lookup(Hashlookup(), obs(ObservableType.SHA1, sha1), handler)
    assert seen == [f"/lookup/sha1/{sha1}"]


async def test_hashlookup_miss_is_no_signal():
    signal = await lookup(
        Hashlookup(),
        obs(ObservableType.SHA256, "0" * 63 + "1"),
        lambda r: json_response(404, {"message": "Non existing SHA-256", "query": "0" * 63 + "1"}),
    )
    assert signal is None  # unknown file ≠ malicious


async def test_hashlookup_400_bad_input_is_a_provider_error():
    with pytest.raises(ProviderError):
        await lookup(
            Hashlookup(),
            obs(ObservableType.SHA256, "0" * 64),
            lambda r: json_response(400, {"message": "SHA-256 value incorrect"}),
        )


# -- OTX (probe §3, live-verified keyless) --------------------------------------

OTX_PULSED = {  # trimmed from the live WannaCry response
    "pulse_info": {
        "count": 50,
        "pulses": [{"name": "WannaCry linked Lazarus indicators", "adversary": "Lazarus Group"}],
    },
    "validation": [],
    "reputation": 0,
}
OTX_WHITELISTED = {  # trimmed from the live example.com response — the count trap
    "pulse_info": {"count": 50, "pulses": [{"name": "Microsoft Phishing Collection"}]},
    "validation": [
        {"source": "akamai", "message": "Akamai rank: #1608", "name": "Akamai Popular Domain"},
        {
            "source": "whitelist",
            "message": "Whitelisted domain example.com",
            "name": "Whitelisted domain",
        },
    ],
}
OTX_QUIET = {"pulse_info": {"count": 0, "pulses": []}, "validation": []}


async def test_otx_pulses_without_validation_are_suspicious():
    sha = "ed01ebfbc9eb5bbea545af4d01bf5f1071661840480439c6e5babe8e080e41aa"

    def handler(request):
        assert request.url.path == f"/api/v1/indicators/file/{sha}/general"
        assert "X-OTX-API-KEY" not in request.headers  # keyless works (probed)
        return json_response(200, OTX_PULSED)

    signal = await lookup(OTX(), obs(ObservableType.SHA256, sha), handler)
    assert signal.label is VerdictLabel.SUSPICIOUS
    assert "50 threat pulses" in signal.summary and "Lazarus Group" in signal.summary


async def test_otx_whitelist_validation_vetoes_pulse_count():
    """Probe mismatch #4: example.com sits in 50 pulses yet is benign —
    validation[] must win over pulse_info.count."""
    signal = await lookup(
        OTX(),
        obs(ObservableType.DOMAIN, "example.com"),
        lambda r: json_response(200, OTX_WHITELISTED),
    )
    assert signal.label is VerdictLabel.BENIGN
    assert "Whitelisted domain" in signal.summary


async def test_otx_urls_are_percent_encoded_and_quiet_is_none():
    seen = []

    def handler(request):
        seen.append(str(request.url))  # str keeps the wire encoding; .path decodes it
        return json_response(200, OTX_QUIET)

    signal = await lookup(OTX(), obs(ObservableType.URL, "http://example.com/test"), handler)
    assert signal is None
    expected = (
        "https://otx.alienvault.com/api/v1/indicators/url/http%3A%2F%2Fexample.com%2Ftest/general"
    )
    assert seen == [expected]


async def test_otx_sends_key_when_configured():
    def handler(request):
        assert request.headers["X-OTX-API-KEY"] == "test-key"
        return json_response(200, OTX_QUIET)

    await lookup(OTX(api_key="test-key"), obs(ObservableType.IPV4, "8.8.8.8"), handler)


# -- GreyNoise (probe §4, live-verified) -----------------------------------------

GREYNOISE_BENIGN_SCANNER = {  # live 71.6.135.131 response
    "ip": "71.6.135.131",
    "noise": True,
    "riot": False,
    "classification": "benign",
    "name": "Shodan.io",
    "link": "https://viz.greynoise.io/ip/71.6.135.131",
    "last_seen": "2026-07-16",
    "message": "Success",
}
GREYNOISE_NOT_SEEN = {  # live 8.8.8.8 response — a SEMANTIC 404
    "ip": "8.8.8.8",
    "noise": False,
    "riot": False,
    "message": "IP not observed scanning the internet.",
}


async def test_greynoise_benign_scanner_maps_to_benign():
    def handler(request):
        assert request.headers["key"] == "gn-key"
        return json_response(200, GREYNOISE_BENIGN_SCANNER)

    signal = await lookup(GreyNoise("gn-key"), obs(ObservableType.IPV4, "71.6.135.131"), handler)
    assert signal.label is VerdictLabel.BENIGN
    assert "Shodan.io" in signal.summary


async def test_greynoise_malicious_classification():
    body = {**GREYNOISE_BENIGN_SCANNER, "classification": "malicious", "name": "unknown"}
    signal = await lookup(
        GreyNoise("gn-key"),
        obs(ObservableType.IPV4, "1.2.3.4"),
        lambda r: json_response(200, body),
    )
    assert signal.label is VerdictLabel.MALICIOUS


async def test_greynoise_semantic_404_is_no_signal():
    signal = await lookup(
        GreyNoise("gn-key"),
        obs(ObservableType.IPV4, "8.8.8.8"),
        lambda r: json_response(404, GREYNOISE_NOT_SEEN),
    )
    assert signal is None


# -- AbuseIPDB (probe §5: 401 live-verified; 200 docs-coded) ----------------------

ABUSEIPDB_401 = {  # live keyless response
    "errors": [
        {
            "detail": "Authentication failed. Your API key is either missing, "
            "incorrect, or revoked.",
            "status": 401,
        }
    ]
}
ABUSEIPDB_MALICIOUS = {  # docs-coded shape (unverified live — TD)
    "data": {
        "ipAddress": "185.220.101.34",
        "abuseConfidenceScore": 100,
        "totalReports": 187,
        "numDistinctUsers": 60,
        "isWhitelisted": False,
        "isTor": True,
        "usageType": "Data Center/Web Hosting/Transit",
        "isp": "Example Hosting",
        "lastReportedAt": "2026-07-15T09:00:00+00:00",
    }
}


async def test_abuseipdb_high_score_is_malicious():
    def handler(request):
        assert request.headers["Key"] == "ab-key"
        assert request.url.params["ipAddress"] == "185.220.101.34"
        assert request.url.params["maxAgeInDays"] == "90"
        return json_response(200, ABUSEIPDB_MALICIOUS)

    signal = await lookup(AbuseIPDB("ab-key"), obs(ObservableType.IPV4, "185.220.101.34"), handler)
    assert signal.label is VerdictLabel.MALICIOUS
    assert signal.confidence == 1.0
    assert "abuse confidence 100/100" in signal.summary and "187 reports" in signal.summary


async def test_abuseipdb_mid_score_is_suspicious_and_low_score_is_no_signal():
    def body(score):
        return {"data": {**ABUSEIPDB_MALICIOUS["data"], "abuseConfidenceScore": score}}

    mid = await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "1.2.3.4"),
        lambda r: json_response(200, body(50)),
    )
    assert mid.label is VerdictLabel.SUSPICIOUS
    low = await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "1.2.3.4"),
        lambda r: json_response(200, body(3)),
    )
    assert low is None


async def test_abuseipdb_whitelisted_is_benign():
    body = {
        "data": {**ABUSEIPDB_MALICIOUS["data"], "abuseConfidenceScore": 0, "isWhitelisted": True}
    }
    signal = await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "8.8.8.8"),
        lambda r: json_response(200, body),
    )
    assert signal.label is VerdictLabel.BENIGN


async def test_abuseipdb_401_is_a_provider_error():
    with pytest.raises(ProviderError):
        await lookup(
            AbuseIPDB("bad"),
            obs(ObservableType.IPV4, "8.8.8.8"),
            lambda r: json_response(401, ABUSEIPDB_401),
        )


# -- URLhaus (probe §6: 401 live-verified; ok-shapes docs-coded) ------------------

URLHAUS_401 = {"error": "Unauthorized"}  # live keyless response
URLHAUS_HOST_OK = {  # docs-coded shape (unverified live — TD)
    "query_status": "ok",
    "url_count": 5,
    "firstseen": "2026-06-01",
    "blacklists": {"surbl": "listed", "spamhaus_dbl": "abused_domain"},
    "urls": [
        {
            "url": "http://bad.example/payload.exe",
            "url_status": "online",
            "threat": "malware_download",
            "tags": ["Mozi"],
        },
        {
            "url": "http://bad.example/old.exe",
            "url_status": "offline",
            "threat": "malware_download",
            "tags": [],
        },
    ],
}
URLHAUS_PAYLOAD_OK = {  # docs-coded shape
    "query_status": "ok",
    "md5_hash": "a" * 32,
    "sha256_hash": "b" * 64,
    "signature": "TrickBot",
    "file_type": "exe",
    "url_count": 10,
    "firstseen": "2026-05-20",
}


async def test_urlhaus_host_with_live_urls_is_malicious():
    def handler(request):
        assert request.url.path == "/v1/host/"
        assert request.headers["Auth-Key"] == "ac-key"
        assert b"host=bad.example" in request.read()
        return json_response(200, URLHAUS_HOST_OK)

    signal = await lookup(URLhaus("ac-key"), obs(ObservableType.DOMAIN, "bad.example"), handler)
    assert signal.label is VerdictLabel.MALICIOUS
    assert "1 live of 5 listed URLs" in signal.summary


async def test_urlhaus_host_with_only_offline_history_is_suspicious():
    body = {
        **URLHAUS_HOST_OK,
        "urls": [dict(u, url_status="offline") for u in URLHAUS_HOST_OK["urls"]],
    }
    signal = await lookup(
        URLhaus("k"), obs(ObservableType.IPV4, "1.2.3.4"), lambda r: json_response(200, body)
    )
    assert signal.label is VerdictLabel.SUSPICIOUS
    assert "historically hosted" in signal.summary


async def test_urlhaus_payload_lookup_uses_the_right_hash_field():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.read().decode()))
        return json_response(200, URLHAUS_PAYLOAD_OK)

    signal = await lookup(URLhaus("k"), obs(ObservableType.SHA256, "b" * 64), handler)
    assert signal.label is VerdictLabel.MALICIOUS
    assert "TrickBot" in signal.summary
    assert seen[0][0] == "/v1/payload/" and "sha256_hash=" in seen[0][1]

    await lookup(URLhaus("k"), obs(ObservableType.MD5, "a" * 32), handler)
    assert "md5_hash=" in seen[1][1]


async def test_urlhaus_no_results_is_no_signal():
    signal = await lookup(
        URLhaus("k"),
        obs(ObservableType.URL, "http://clean.example/"),
        lambda r: json_response(200, {"query_status": "no_results"}),
    )
    assert signal is None


async def test_urlhaus_401_and_unknown_status_are_provider_errors():
    with pytest.raises(ProviderError):
        await lookup(
            URLhaus("bad"),
            obs(ObservableType.DOMAIN, "x.example"),
            lambda r: json_response(401, URLHAUS_401),
        )
    with pytest.raises(ProviderError):  # docs-coded contract drift must fail SOFT
        await lookup(
            URLhaus("k"),
            obs(ObservableType.DOMAIN, "x.example"),
            lambda r: json_response(200, {"query_status": "weird_new_status"}),
        )


# -- ThreatFox (probe §7: 401 live-verified; ok-shape docs-coded) -----------------

THREATFOX_OK = {  # docs-coded shape (unverified live — TD)
    "query_status": "ok",
    "data": [
        {
            "id": "41",
            "ioc": "1.2.3.4:445",
            "threat_type": "botnet_cc",
            "malware": "win.cobalt_strike",
            "malware_printable": "Cobalt Strike",
            "confidence_level": 75,
            "first_seen": "2026-07-01 07:44:46 UTC",
            "tags": ["c2"],
        },
        {
            "id": "42",
            "ioc": "1.2.3.4:8443",
            "threat_type": "botnet_cc",
            "malware": "win.cobalt_strike",
            "malware_printable": "Cobalt Strike",
            "confidence_level": 40,
            "first_seen": "2026-06-11 10:02:01 UTC",
            "tags": [],
        },
    ],
}


async def test_threatfox_hit_is_malicious_and_reports_the_top_row():
    def handler(request):
        assert request.headers["Auth-Key"] == "ac-key"
        payload = json.loads(request.read())
        assert payload == {"query": "search_ioc", "search_term": "1.2.3.4", "exact_match": True}
        return json_response(200, THREATFOX_OK)

    signal = await lookup(ThreatFox("ac-key"), obs(ObservableType.IPV4, "1.2.3.4"), handler)
    assert signal.label is VerdictLabel.MALICIOUS
    assert signal.confidence == 0.75  # highest-confidence row wins
    assert "Cobalt Strike" in signal.summary and "botnet_cc" in signal.summary


async def test_threatfox_low_reporter_confidence_is_floored():
    body = {"query_status": "ok", "data": [dict(THREATFOX_OK["data"][1], confidence_level=10)]}
    signal = await lookup(
        ThreatFox("k"),
        obs(ObservableType.DOMAIN, "c2.example"),
        lambda r: json_response(200, body),
    )
    assert signal.confidence == 0.5  # curated malicious feed never drops below 0.5


async def test_threatfox_no_result_is_no_signal_even_with_string_data():
    signal = await lookup(
        ThreatFox("k"),
        obs(ObservableType.IPV4, "9.9.9.9"),
        lambda r: json_response(
            200, {"query_status": "no_result", "data": "Your search did not yield any result"}
        ),
    )
    assert signal is None


async def test_threatfox_401_and_unknown_status_are_provider_errors():
    with pytest.raises(ProviderError):
        await lookup(
            ThreatFox("bad"),
            obs(ObservableType.IPV4, "1.2.3.4"),
            lambda r: json_response(401, {"error": "Unauthorized"}),
        )
    with pytest.raises(ProviderError):
        await lookup(
            ThreatFox("k"),
            obs(ObservableType.IPV4, "1.2.3.4"),
            lambda r: json_response(200, {"query_status": "mystery"}),
        )


# -- registry activation policy ---------------------------------------------------


def test_keyless_registry_activates_exactly_the_probed_free_providers():
    from auspex.config import Settings
    from auspex.enrich.providers import build_providers

    names = [p.name for p in build_providers(Settings(enrichment_enabled=True))]
    assert names == ["InternetDB", "CIRCL hashlookup", "OTX"]


def test_keys_activate_the_gated_providers():
    from auspex.config import Settings
    from auspex.enrich.providers import build_providers

    settings = Settings(
        enrichment_enabled=True,
        abusech_auth_key="a",
        abuseipdb_api_key="b",
        greynoise_api_key="c",
    )
    names = {p.name for p in build_providers(settings)}
    assert names == {
        "InternetDB",
        "CIRCL hashlookup",
        "OTX",
        "URLhaus",
        "ThreatFox",
        "AbuseIPDB",
        "GreyNoise",
    }
