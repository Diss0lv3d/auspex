"""The connector HTTP client: declared hosts only, https only, TLS in one of three forms (S32).

`ConnectorHttp` is the client a handler gets as `ctx.http`. It wraps an `httpx.Client` and:

- sends only to the manifest's declared hosts, resolved from the integration's config
  (`resolve_hosts`). Each request is BUILT first and its parsed URL checked, so the host
  checked is the host httpx connects to (no parser disagreement). Hosts compare lowercased,
  host and port together, the port defaulting to 443 (Task 2's review carry).
- refuses plain http, and never follows a redirect: `follow_redirects` is off and cannot be
  turned on, so a declared host cannot bounce a request (and its headers) to another one.
- refuses httpx `extensions`, because `sni_hostname` would change the name the hostname check
  verifies against.
- ignores the environment (`trust_env=False`): no proxy from HTTPS_PROXY, no `.netrc`
  credentials sent to a host the connector did not choose.

TLS (Hunaiza's security call, spec "Hunaiza's two security calls"). There is no off:
- `verify`: the system trust store, chain and hostname checked (`ssl.create_default_context`).
- a pinned CA PEM: a context trusting ONLY that CA (`cadata`), chain and hostname checked.
- a pinned certificate SHA-256: the connection is trusted only if the SHA-256 of the live leaf
  certificate's DER equals the pin; it REPLACES the chain and hostname checks.

How the pin is enforced. The pin form uses `_PinnedContext`, an `ssl.SSLContext` whose
`sslsocket_class` (`_PinnedSocket`) checks the pin inside `do_handshake`, on that socket's own
peer certificate (`getpeercert(binary_form=True)`). `wrap_socket` is forced to handshake on
connect, so the check runs before `wrap_socket` returns: httpcore (`SyncStream.start_tls`) has
no TLS stream to write a request byte to until the pin has matched. On a mismatch the socket is
closed and `CertificatePinMismatch` is raised. The check lives in the context, not in httpx,
so it does not depend on httpx internals: whatever wraps a socket with this context gets the
check. `sslobject_class` (`_PinnedObject`, used by memory-BIO/async TLS) checks it too, and
refuses to write application data before the pin has matched. A test proves the ordering: a
pin one byte off is refused and the server received zero bytes after the handshake.
"""

import hashlib
import hmac
import re
import ssl
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from auspex_sdk.manifest import Tls

DEFAULT_TIMEOUT = 30.0  # seconds, per httpx phase

_PLACEHOLDER = re.compile(r"https://\{([^{}/:]*)\}")


class HostNotDeclared(Exception):
    """A request to a host:port the manifest does not declare (or that config does not name)."""


class PlainHttpRefused(HostNotDeclared):
    """A plain http:// URL. Connectors speak https only."""


class CertificatePinMismatch(Exception):
    """The live leaf certificate's SHA-256 is not the pin; the connection was closed unused."""


# --- hosts -----------------------------------------------------------------------------------


def _host_key(url: str) -> tuple[str, int]:
    """(lowercased host, port) of an https URL, parsed the way httpx parses requests."""
    try:
        u = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as exc:
        raise HostNotDeclared(f"not a URL: {exc}") from None
    if u.scheme == "http":
        raise PlainHttpRefused(f"plain http is refused: {u.host}")
    if u.scheme != "https" or not u.host:
        raise HostNotDeclared("expected an https:// URL with a host")
    return u.host.lower(), u.port or 443


def resolve_hosts(patterns: Iterable[str], values: Mapping[str, Any]) -> frozenset[tuple[str, int]]:
    """Resolve manifest `hosts` entries against config values.

    `https://{base_url}` takes the host and port of the config's `base_url`; a literal entry is
    its own host. A placeholder whose field is unset is refused (HostNotDeclared).
    """
    out: set[tuple[str, int]] = set()
    for p in patterns:
        ph = _PLACEHOLDER.fullmatch(p)
        if ph:
            v = values.get(ph.group(1))
            if not isinstance(v, str) or not v:
                raise HostNotDeclared(
                    f"host {p} names config field {ph.group(1)!r}, which is unset"
                )
            out.add(_host_key(v))
        else:
            out.add(_host_key(p))
    return frozenset(out)


# --- TLS ------------------------------------------------------------------------------------


def _check_pin(der: bytes | None, pin: str) -> None:
    got = hashlib.sha256(der).hexdigest() if der else ""
    if not der or not hmac.compare_digest(got, pin):
        raise CertificatePinMismatch(
            "the server's certificate does not match the pinned SHA-256; connection refused"
        )


class _PinnedSocket(ssl.SSLSocket):
    def do_handshake(self, block: bool = False) -> None:
        super().do_handshake(block)
        try:
            _check_pin(self.getpeercert(binary_form=True), self.context._auspex_pin)
        except CertificatePinMismatch:
            self.close()
            raise


class _PinnedObject(ssl.SSLObject):
    _auspex_pinned = False

    def do_handshake(self) -> None:
        super().do_handshake()
        _check_pin(self.getpeercert(binary_form=True), self.context._auspex_pin)
        self._auspex_pinned = True

    def write(self, data: Any) -> int:
        if not self._auspex_pinned:
            raise CertificatePinMismatch("no application data before the pin has matched")
        return super().write(data)


class _PinnedContext(ssl.SSLContext):
    """A client context that trusts exactly one leaf certificate, by the SHA-256 of its DER.

    Chain and hostname checks are off ON PURPOSE: the pin replaces them (Hunaiza's call). It is
    never off without the pin: the pin is checked in the handshake of every socket it wraps.
    """

    sslsocket_class = _PinnedSocket
    sslobject_class = _PinnedObject

    def wrap_socket(
        self,
        sock: Any,
        server_side: bool = False,
        do_handshake_on_connect: bool = True,
        suppress_ragged_eofs: bool = True,
        server_hostname: str | None = None,
        session: ssl.SSLSession | None = None,
    ) -> ssl.SSLSocket:
        # Always handshake on connect, whatever the caller asked: the pin check runs inside the
        # handshake, so no socket leaves this method (and no byte is written) unchecked.
        return super().wrap_socket(
            sock,
            server_side=server_side,
            do_handshake_on_connect=True,
            suppress_ragged_eofs=suppress_ragged_eofs,
            server_hostname=server_hostname,
            session=session,
        )


def ssl_context_for(tls: Tls) -> ssl.SSLContext:
    """The client SSL context for a Tls value. Every form checks something; none is off."""
    if not isinstance(tls, Tls):
        raise TypeError("tls must be an auspex_sdk.manifest.Tls")
    if tls.cert_sha256 is not None:
        ctx: ssl.SSLContext = _PinnedContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx._auspex_pin = tls.cert_sha256.lower()  # type: ignore[attr-defined]
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif tls.ca_pem is not None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # no system CAs: only the pinned one
        ctx.load_verify_locations(cadata=tls.ca_pem)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx = ssl.create_default_context()  # system trust; chain and hostname checked
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


# --- the client -----------------------------------------------------------------------------


class ConnectorHttp:
    """An https client bound to the declared hosts and one TLS form.

    `allowed_hosts` takes URLs (`https://host[:port]`) or (host, port) pairs, usually from
    `resolve_hosts`. `transport` replaces the network for the harness (httpx.MockTransport):
    the host and scheme checks still run, TLS does not.
    """

    def __init__(
        self,
        allowed_hosts: Iterable[str | tuple[str, int]],
        tls: Tls,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.allowed_hosts: frozenset[tuple[str, int]] = frozenset(
            (h[0].lower(), int(h[1])) if isinstance(h, tuple) else _host_key(h)
            for h in allowed_hosts
        )
        if not isinstance(tls, Tls):
            raise TypeError("tls must be an auspex_sdk.manifest.Tls")
        self.tls = tls
        if transport is None:
            transport = httpx.HTTPTransport(verify=ssl_context_for(tls), trust_env=False)
        self._client = httpx.Client(
            transport=transport, follow_redirects=False, trust_env=False, timeout=timeout
        )

    def _check(self, url: httpx.URL) -> None:
        if url.scheme == "http":
            raise PlainHttpRefused(f"plain http is refused: {url.host}")
        if url.scheme != "https" or not url.host:
            raise HostNotDeclared("expected an absolute https:// URL")
        key = (url.host.lower(), url.port or 443)
        if key not in self.allowed_hosts:
            raise HostNotDeclared(f"{key[0]}:{key[1]} is not a declared host")

    def request(self, method: str, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        for refused in ("follow_redirects", "extensions"):
            if refused in kwargs:
                raise ValueError(f"{refused} is not available to connectors")
        auth = kwargs.pop("auth", httpx.USE_CLIENT_DEFAULT)
        request = self._client.build_request(method, url, **kwargs)
        self._check(request.url)
        return self._client.send(request, auth=auth, follow_redirects=False)

    def get(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return self.request("OPTIONS", url, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ConnectorHttp":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
