"""A stub SIEM for the S33 live check (dev profile only; synthetic, no data).

It makes a self-signed certificate at start into /certs (a volume the live check reads
to pin its SHA-256, the D-071 pin path) and serves the reference connector's health
endpoint: GET /api/health -> {"status": "ok"} when a Bearer token is sent, else 401.
"""

import json
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CERTS = Path("/certs")


def make_cert() -> None:
    CERTS.mkdir(exist_ok=True)
    subprocess.run(  # noqa: S603 -- the image's own openssl, fixed arguments
        ["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
         "-subj", "/CN=mock-siem", "-addext", "subjectAltName=DNS:mock-siem",
         "-keyout", str(CERTS / "key.pem"), "-out", str(CERTS / "cert.pem")],
        check=True, capture_output=True)
    der = subprocess.run(  # noqa: S603
        ["/usr/bin/openssl", "x509", "-in", str(CERTS / "cert.pem"), "-outform", "DER"],
        check=True, capture_output=True).stdout
    import hashlib

    (CERTS / "cert.sha256").write_text(hashlib.sha256(der).hexdigest())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- the stdlib's name
        if self.path != "/api/health":
            self._send(404, {"error": "not found"})
        elif not self.headers.get("Authorization", "").startswith("Bearer "):
            self._send(401, {"error": "no token"})
        else:
            self._send(200, {"status": "ok"})

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    make_cert()
    server = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)  # noqa: S104 -- a dev stub
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERTS / "cert.pem", CERTS / "key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
