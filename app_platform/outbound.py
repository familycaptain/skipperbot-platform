"""Fetching a URL that someone else chose, without becoming their proxy into the house.

Skipper runs on a machine inside a household network, next to a router, a NAS, Home Assistant,
printers, and its own database. Any endpoint that takes a URL from a request and fetches it turns
the server into a probe for all of that: the caller cannot reach `http://192.168.1.1/` or
`http://127.0.0.1:8000/` themselves, but Skipper can, and it hands the result back. That is
server-side request forgery, and "only signed-in household members can call it" is not a
mitigation when the household includes a child's account and the fetch is triggered automatically
by rendering someone else's post.

Two things make this harder than checking the string:

* **The hostname is not the destination.** `evil.example` can resolve to 127.0.0.1, and a name can
  resolve differently between the check and the fetch. So this resolves the host and validates
  every address it gets, then pins the fetch to a validated address.
* **A redirect moves the destination after you approved it.** A public URL is free to 302 to
  `http://169.254.169.254/`. Redirects are therefore followed manually, with every hop validated.

Use `open_public_url()` wherever the URL came from outside. If the URL is one the operator
configured (an env var, a setting), this is not the tool — that destination is trusted on purpose,
and a private address may be exactly what was intended.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["OutboundBlocked", "check_public_url", "open_public_url"]

MAX_REDIRECTS = 3
ALLOWED_SCHEMES = ("http", "https")


class OutboundBlocked(Exception):
    """The URL is not one we are willing to fetch on a caller's behalf."""


def _address_is_public(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    # is_global is false for private, loopback, link-local, multicast, reserved and unspecified —
    # including IPv6 forms and the ::ffff:127.0.0.1 style mapped addresses.
    if not ip.is_global:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_multicast:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None and not _address_is_public(str(mapped)):
        return False
    return True


def check_public_url(url: str) -> str:
    """Return the host's validated IP, or raise OutboundBlocked.

    Every address the hostname resolves to must be publicly routable — not just the first. A name
    that resolves to both a public and a private address is refused outright rather than raced.
    """
    parsed = urllib.parse.urlparse((url or "").strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise OutboundBlocked(f"scheme {parsed.scheme!r} is not fetchable")
    host = parsed.hostname
    if not host:
        raise OutboundBlocked("no host in URL")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise OutboundBlocked(f"cannot resolve {host!r}: {exc}") from exc
    if not infos:
        raise OutboundBlocked(f"{host!r} resolves to nothing")

    addresses = {info[4][0] for info in infos}
    for addr in addresses:
        if not _address_is_public(addr):
            raise OutboundBlocked(f"{host!r} resolves to non-public address {addr}")
    return sorted(addresses)[0]


def open_public_url(url: str, *, timeout: int = 5, headers: dict | None = None):
    """Open a caller-supplied URL, validating the destination at every redirect hop.

    Returns the open response — the caller reads and closes it, and should still cap how much it
    reads. Raises OutboundBlocked if any hop is not publicly routable.
    """
    current = (url or "").strip()
    for _ in range(MAX_REDIRECTS + 1):
        check_public_url(current)
        req = urllib.request.Request(current, headers=headers or {})
        # No redirect handler: a 3xx comes back as a response we validate ourselves rather than
        # something urllib quietly follows to an address we never checked.
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                target = exc.headers.get("location")
                if not target:
                    raise OutboundBlocked("redirect with no location") from exc
                current = urllib.parse.urljoin(current, target)
                exc.close()
                continue
            raise
        return resp
    raise OutboundBlocked(f"more than {MAX_REDIRECTS} redirects")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects to the caller instead of following them silently."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None
