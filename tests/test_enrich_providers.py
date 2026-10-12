"""Provider clients vs saved probe fixtures — S5, hermetic (httpx.MockTransport).

Every fixture body below is copied (trimmed) from a LIVE response captured in
docs/probes/2026-07-16-enrichment-providers.md or, for the key-gated
providers, docs/probes/2026-07-16-keyed-providers-live.md (TD-004 follow-up:
keys registered same evening, all former docs-coded shapes re-probed live).
"""

import json
from pathlib import Path

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
from auspex.enrich.types import (
    NetworkContext,
    ProviderError,
    ProviderInputError,
    VerdictLabel,
    split_lookup,
)


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


async def test_internetdb_vulns_are_exposure_context_not_a_verdict():
    """Probe §1: exposure is not maliciousness — a vulnerable host is a victim
    candidate, not an IOC (S5 review aligned the label with the probe)."""
    body = {**INTERNETDB_8888, "vulns": ["CVE-2023-44487"]}  # derived from probed shape
    signal = await lookup(
        InternetDB(), obs(ObservableType.IPV4, "8.8.8.8"), lambda r: json_response(200, body)
    )
    assert signal.label is VerdictLabel.UNKNOWN
    assert signal.confidence == 0.0
    assert "CVE-2023-44487" in signal.summary and "exposed" in signal.summary


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
OTX_TOR_EXIT = {  # live 185.220.101.34 response (2026-07-16 in-container verify):
    # validation[] here is CONTEXT, not a whitelist — the original parser
    # treated any validation as benign and would have whitelisted a Tor exit.
    "pulse_info": {"count": 50, "pulses": [{"name": "Tor exit node tracking"}]},
    "validation": [
        {
            "source": "tor_exits",
            "message": "IP Associated with Tor Exit Nodes",
            "name": "IP Assosciated with Tor Exit Nodes",
        },  # (sic — OTX's own typo)
    ],
}


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


async def test_otx_tor_exit_validation_is_not_a_benign_veto():
    """Pinned live regression (2026-07-16): a Tor exit carries a validation[]
    entry with source=tor_exits. Only whitelist-family sources may veto —
    this indicator must stay SUSPICIOUS, with the Tor context surfaced."""
    signal = await lookup(
        OTX(),
        obs(ObservableType.IPV4, "185.220.101.34"),
        lambda r: json_response(200, OTX_TOR_EXIT),
    )
    assert signal.label is VerdictLabel.SUSPICIOUS
    assert "flagged: IP Associated with Tor Exit Nodes" in signal.summary


async def test_otx_context_validation_without_pulses_is_context_not_a_verdict():
    body = {"pulse_info": {"count": 0, "pulses": []}, "validation": OTX_TOR_EXIT["validation"]}
    signal = await lookup(
        OTX(), obs(ObservableType.IPV4, "185.220.101.34"), lambda r: json_response(200, body)
    )
    assert signal.label is VerdictLabel.UNKNOWN
    assert signal.confidence == 0.0
    assert "Tor Exit Nodes" in signal.summary


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
ABUSEIPDB_MALICIOUS = {  # live 185.220.101.34 (Tor exit) response, keyed probe
    "data": {
        "ipAddress": "185.220.101.34",
        "abuseConfidenceScore": 90,
        "totalReports": 106,
        "numDistinctUsers": 68,
        "isWhitelisted": False,
        "isTor": True,
        "usageType": "Commercial",
        "isp": "Network for Tor-Exit traffic.",
        "countryCode": "DE",
        "lastReportedAt": "2026-07-15T14:34:59+00:00",
    }
}


async def test_abuseipdb_high_score_is_malicious():
    def handler(request):
        assert request.headers["Key"] == "ab-key"
        assert request.url.params["ipAddress"] == "185.220.101.34"
        assert request.url.params["maxAgeInDays"] == "90"
        return json_response(200, ABUSEIPDB_MALICIOUS)

    signals, network = split_lookup(
        await lookup(AbuseIPDB("ab-key"), obs(ObservableType.IPV4, "185.220.101.34"), handler)
    )
    (signal,) = signals
    assert signal.label is VerdictLabel.MALICIOUS
    assert signal.confidence == 0.9
    assert "abuse confidence 90/100" in signal.summary and "106 reports" in signal.summary
    # B-001: the network rides beside the verdict, never inside it.
    assert [c.summary for c in network] == ["Network for Tor-Exit traffic., Commercial, DE"]


async def test_abuseipdb_mid_score_is_suspicious_and_low_score_is_no_reputation_signal():
    def body(score):
        return {"data": {**ABUSEIPDB_MALICIOUS["data"], "abuseConfidenceScore": score}}

    mid, _ = split_lookup(await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "1.2.3.4"),
        lambda r: json_response(200, body(50)),
    ))
    assert [s.label for s in mid] == [VerdictLabel.SUSPICIOUS]
    low = await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "1.2.3.4"),
        lambda r: json_response(200, body(3)),
    )
    # A low score is still no claim about reputation (B-001 changes only that
    # the network the source named is kept).
    assert isinstance(low, NetworkContext)


ABUSEIPDB_B001 = json.loads(
    (Path(__file__).parent / "fixtures" / "enrich" / "b001_ip_owner_claim.json").read_text()
)["abuseipdb_response"]


async def test_abuseipdb_names_the_network_it_reported_on_a_clean_ip_b001():
    """B-001, the live response: score 0, no reports, and the network named in
    full. It used to return None — the IOC check then said "unknown to them",
    and a model asked to dig deeper supplied an owner from memory (Amazon)."""
    result = await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "34.187.179.218"),
        lambda r: json_response(200, ABUSEIPDB_B001),
    )
    signals, network = split_lookup(result)
    assert signals == []  # no reputation claim — the verdict path is untouched
    (context,) = network
    assert context.provider == "AbuseIPDB"
    assert context.summary == (
        "Google LLC (google.com), Data Center/Web Hosting/Transit, US"
        " · hostname 218.179.187.34.bc.googleusercontent.com"
    )
    assert context.evidence == {
        "isp": "Google LLC",
        "domain": "google.com",
        "usage_type": "Data Center/Web Hosting/Transit",
        "country_code": "US",
        "hostnames": ["218.179.187.34.bc.googleusercontent.com"],
    }


async def test_abuseipdb_with_no_network_fields_and_a_low_score_is_no_data():
    body = {"data": {"ipAddress": "1.2.3.4", "abuseConfidenceScore": 0, "totalReports": 0,
                     "isWhitelisted": False, "isp": None, "hostnames": "not-a-list"}}
    result = await lookup(
        AbuseIPDB("k"), obs(ObservableType.IPV4, "1.2.3.4"), lambda r: json_response(200, body)
    )
    assert result is None


async def test_abuseipdb_whitelisted_is_benign():
    # live 8.8.8.8 keyed probe: score 0, isWhitelisted true, 121 reports —
    # famous infrastructure gets reported constantly; the whitelist must win.
    body = {
        "data": {
            **ABUSEIPDB_MALICIOUS["data"],
            "ipAddress": "8.8.8.8",
            "abuseConfidenceScore": 0,
            "totalReports": 121,
            "isWhitelisted": True,
            "isTor": False,
            "usageType": "Content Delivery Network",
        }
    }
    signals, network = split_lookup(await lookup(
        AbuseIPDB("k"),
        obs(ObservableType.IPV4, "8.8.8.8"),
        lambda r: json_response(200, body),
    ))
    assert [s.label for s in signals] == [VerdictLabel.BENIGN]
    assert [c.summary for c in network] == [
        "Network for Tor-Exit traffic., Content Delivery Network, DE"
    ]


async def test_abuseipdb_401_is_a_provider_error():
    with pytest.raises(ProviderError):
        await lookup(
            AbuseIPDB("bad"),
            obs(ObservableType.IPV4, "8.8.8.8"),
            lambda r: json_response(401, ABUSEIPDB_401),
        )


# -- URLhaus (probe §6: 401 live-verified; ok-shapes docs-coded) ------------------

URLHAUS_401 = {"error": "Unauthorized"}  # live keyless response
URLHAUS_HOST_OK = {  # live-verified shape (Mozi C2 keyed probe); counts adjusted
    "query_status": "ok",
    "url_count": 5,
    "firstseen": "2026-06-01",
    "blacklists": {"surbl": "not listed", "spamhaus_dbl": "not listed"},
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
URLHAUS_PAYLOAD_OK = {  # live-verified shape; url_count is a STRING here (probed)
    "query_status": "ok",
    "md5_hash": "a" * 32,
    "sha256_hash": "b" * 64,
    "signature": "TrickBot",
    "file_type": "exe",
    "file_size": "312832",
    "url_count": "10",
    "firstseen": "2026-05-20",
}
URLHAUS_PAYLOAD_EMPTY = {  # live empty-file MD5 response (keyed probe) — the trap:
    # URLhaus records ANY bytes served from a listed URL; empty = failed download.
    "query_status": "ok",
    "md5_hash": "d41d8cd98f00b204e9800998ecf8427e",
    "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "file_type": "unknown",
    "file_size": "0",
    "signature": None,
    "url_count": "2251",
    "firstseen": "2018-03-21 05:29:38",
    "lastseen": "2018-03-22 07:28:33",
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


async def test_urlhaus_empty_payload_is_a_failed_download_not_malware():
    """Pinned live regression (keyed probe): the canonical empty-file hash is
    query_status "ok" on /v1/payload/ — file_size 0 must yield NO signal."""
    signal = await lookup(
        URLhaus("k"),
        obs(ObservableType.MD5, "d41d8cd98f00b204e9800998ecf8427e"),
        lambda r: json_response(200, URLHAUS_PAYLOAD_EMPTY),
    )
    assert signal is None


async def test_urlhaus_unclassified_payload_is_suspicious_not_malicious():
    body = {**URLHAUS_PAYLOAD_OK, "signature": None, "file_type": "unknown"}
    signal = await lookup(
        URLhaus("k"), obs(ObservableType.SHA256, "b" * 64), lambda r: json_response(200, body)
    )
    assert signal.label is VerdictLabel.SUSPICIOUS
    assert signal.confidence == 0.65
    assert "unclassified payload" in signal.summary
    assert "malware payload" not in signal.summary  # no asserted family (D-014)


async def test_urlhaus_no_results_is_no_signal():
    signal = await lookup(
        URLhaus("k"),
        obs(ObservableType.URL, "http://clean.example/"),
        lambda r: json_response(200, {"query_status": "no_results"}),
    )
    assert signal is None


async def test_urlhaus_401_feeds_breaker_but_bad_status_is_an_input_error():
    """S5 review: invalid_*/unknown query_status is OUR problem (probe rule) —
    it must raise ProviderInputError so the fan-out never feeds the breaker."""
    with pytest.raises(ProviderError):
        await lookup(
            URLhaus("bad"),
            obs(ObservableType.DOMAIN, "x.example"),
            lambda r: json_response(401, URLHAUS_401),
        )
    for status in ("invalid_host", "weird_new_status"):
        with pytest.raises(ProviderInputError):
            await lookup(
                URLhaus("k"),
                obs(ObservableType.DOMAIN, "x.example"),
                lambda r, s=status: json_response(200, {"query_status": s}),
            )


async def test_urlhaus_url_endpoint_maps_online_and_offline():
    """The /v1/url/ 200-ok branch, pinned to the live-probed shape (Mozi URL:
    url_status online, threat malware_download, tags)."""
    body = {
        "query_status": "ok",
        "url_status": "online",
        "threat": "malware_download",
        "tags": ["Mozi", "elf"],
        "date_added": "2026-07-16 15:33:28 UTC",
    }
    online = await lookup(
        URLhaus("k"),
        obs(ObservableType.URL, "http://bad.example/bin.sh"),
        lambda r: json_response(200, body),
    )
    assert online.label is VerdictLabel.MALICIOUS
    assert online.confidence == 0.9
    assert "currently online" in online.summary

    offline = await lookup(
        URLhaus("k"),
        obs(ObservableType.URL, "http://bad.example/bin.sh"),
        lambda r: json_response(200, {**body, "url_status": "offline"}),
    )
    assert offline.label is VerdictLabel.SUSPICIOUS
    assert offline.confidence == 0.6


# -- ThreatFox (probe §7: 401 live-verified; ok-shape docs-coded) -----------------

THREATFOX_OK = {  # row 1 = live ClearFake hit (keyed probe); row 2 synthetic lower-confidence
    "query_status": "ok",
    "data": [
        {
            "id": "1852565",
            "ioc": "uvzbxwuc.gamehazarat.com",
            "ioc_type": "domain",
            "threat_type": "payload_delivery",
            "malware": "js.clearfake",
            "malware_printable": "ClearFake",
            "confidence_level": 100,
            "first_seen": "2026-07-16 15:12:32 UTC",
            "last_seen": None,
            "tags": ["ClearFake", "win-0x4679", "Windows"],
        },
        {
            "id": "1852566",
            "ioc": "uvzbxwuc.gamehazarat.com",
            "ioc_type": "domain",
            "threat_type": "botnet_cc",
            "malware": "js.clearfake",
            "malware_printable": "ClearFake",
            "confidence_level": 40,
            "first_seen": "2026-06-11 10:02:01 UTC",
            "last_seen": None,
            "tags": [],
        },
    ],
}


async def test_threatfox_hit_is_malicious_and_reports_the_top_row():
    def handler(request):
        assert request.headers["Auth-Key"] == "ac-key"
        payload = json.loads(request.read())
        assert payload == {
            "query": "search_ioc",
            "search_term": "uvzbxwuc.gamehazarat.com",
            "exact_match": True,
        }
        return json_response(200, THREATFOX_OK)

    signal = await lookup(
        ThreatFox("ac-key"), obs(ObservableType.DOMAIN, "uvzbxwuc.gamehazarat.com"), handler
    )
    assert signal.label is VerdictLabel.MALICIOUS
    assert signal.confidence == 1.0  # highest-confidence row wins
    assert "ClearFake" in signal.summary and "payload_delivery" in signal.summary


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


async def test_threatfox_401_feeds_breaker_but_bad_status_is_an_input_error():
    with pytest.raises(ProviderError):
        await lookup(
            ThreatFox("bad"),
            obs(ObservableType.IPV4, "1.2.3.4"),
            lambda r: json_response(401, {"error": "Unauthorized"}),
        )
    with pytest.raises(ProviderInputError):  # contract drift = our side, no breaker
        await lookup(
            ThreatFox("k"),
            obs(ObservableType.IPV4, "1.2.3.4"),
            lambda r: json_response(200, {"query_status": "mystery"}),
        )


# -- registry activation policy ---------------------------------------------------


def test_keyless_registry_activates_exactly_the_probed_free_providers():
    from auspex.config import Settings
    from auspex.enrich.providers import build_providers

    # Keys pinned empty explicitly: Settings() reads .env, and a developer's
    # real keys (present since the TD-004 registration) must not leak in here.
    settings = Settings(
        enrichment_enabled=True,
        abusech_auth_key="",
        abuseipdb_api_key="",
        otx_api_key="",
        greynoise_api_key="",
    )
    names = [p.name for p in build_providers(settings)]
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
