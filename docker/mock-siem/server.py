"""A stub SIEM for the S33 live check (dev profile only; synthetic, no data).

It makes a self-signed certificate at start into /certs (a volume the live check reads
to pin its SHA-256, the D-071 pin path) and serves the reference connector's health
endpoint: GET /api/health -> {"status": "ok"} when a Bearer token is sent, else 401.

S34 adds the reference connector's `close_alert` routes over synthetic alerts held in
memory: GET /api/alerts/<id>, POST /api/alerts/<id>/close and /reopen. Every write is
appended to /certs/writes.log, so the live check can count how often the SIEM was
actually asked to close.
"""

import json
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CERTS = Path("/certs")
ALERTS = {f"A-{n}": {"id": f"A-{n}", "title": "Synthetic alert", "severity": "high",
                     "status": "open", "created": 1792670400, "modified": 1792674000}
          for n in (1001, 1002, 2002)}


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
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self._send(401, {"error": "no token"})
        elif self.path == "/api/health":
            self._send(200, {"status": "ok"})
        elif self.path.startswith("/api/alerts/") and self.path[12:] in ALERTS:
            self._send(200, ALERTS[self.path[12:]])
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parts = self.path.strip("/").split("/")  # api, alerts, <id>, close|reopen
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self._send(401, {"error": "no token"})
        elif (len(parts) == 4 and parts[:2] == ["api", "alerts"] and parts[2] in ALERTS
              and parts[3] in ("close", "reopen")):
            ALERTS[parts[2]]["status"] = "closed" if parts[3] == "close" else "open"
            with (CERTS / "writes.log").open("a") as log:
                log.write(f"{parts[3]} {parts[2]}\n")
            self._send(200, ALERTS[parts[2]])
        else:
            self._send(404, {"error": "not found"})

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
