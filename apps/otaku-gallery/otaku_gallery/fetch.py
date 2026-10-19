"""Server-controlled, SSRF-resistant JSON fetch for a fixed allowlist of public reference APIs.

The browser and the model never supply a URL. Every request is https, to an
allowlisted host, on port 443, with the TLS connection pinned to an address
that was verified to be globally routable. Redirects are never followed.
"""
import http.client
import ipaddress
import json
import socket
import ssl
from urllib import parse

from .errors import ResearchError

ALLOWED_HOSTS = frozenset({"en.wikipedia.org", "graphql.anilist.co"})
USER_AGENT = "OtakuGalleryDemo/1.0 (open-source hackathon demo; on-request reference lookup)"
FETCH_TIMEOUT_S = 4.0
FETCH_MAX_BYTES = 400_000


class _PinnedHTTPS(http.client.HTTPSConnection):
    """TLS to a pre-validated address while verifying the certificate for the hostname."""

    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def validate_url(url):
    """https, allowlisted host, default port, no credentials. Returns (host, request-target)."""
    if not isinstance(url, str) or len(url) > 2000:
        raise ResearchError("url_rejected")
    p = parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if (p.scheme != "https" or host not in ALLOWED_HOSTS or p.username is not None or p.password is not None
            or p.port not in (None, 443) or p.fragment or "@" in p.netloc):
        raise ResearchError("url_rejected")
    return host, (p.path or "/") + ("?" + p.query if p.query else "")


def resolve_public(host, resolver=socket.getaddrinfo):
    """Every resolved address must be globally routable; the first is pinned for the connection."""
    try:
        ipaddress.ip_address(host)
        raise ResearchError("ip_literal_rejected")
    except ValueError:
        pass
    try:
        infos = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ResearchError("dns_failed") from exc
    addresses = []
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        if not address.is_global:
            raise ResearchError("non_public_address")
        addresses.append(str(address))
    if not addresses:
        raise ResearchError("dns_failed")
    return sorted(addresses, key=lambda a: ":" in a)[0]  # prefer IPv4


def safe_fetch(url, body=None, timeout=FETCH_TIMEOUT_S, resolver=socket.getaddrinfo, connection=_PinnedHTTPS):
    """One request, no redirects, no proxy, no cookies, bounded body. JSON only."""
    host, target = validate_url(url)
    address = resolve_public(host, resolver)
    conn = connection(host, address, timeout)
    try:
        headers = {"Host": host, "User-Agent": USER_AGENT, "Accept": "application/json", "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request("POST" if body is not None else "GET", target, body=body, headers=headers)
        resp = conn.getresponse()
        if resp.status != 200:  # includes every 3xx: a redirect is never followed
            raise ResearchError("http_%d" % resp.status)
        raw = resp.read(FETCH_MAX_BYTES + 1)
        if len(raw) > FETCH_MAX_BYTES:
            raise ResearchError("oversize")
        return json.loads(raw.decode("utf-8"))
    except ResearchError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise ResearchError("fetch_failed", type(exc).__name__) from exc
    finally:
        conn.close()
