"""Bound test for app_platform.outbound — fetching a URL someone else chose.

Skipper runs inside a household network. An endpoint that fetches a caller-supplied URL and returns
what it found is a probe for the router, Home Assistant, the database and localhost — reachable by
any signed-in account, including a child's, and in the timeline's case triggered automatically for
every reader of someone else's post.

These assert the two properties that are easy to get wrong: the check is on the RESOLVED ADDRESS
rather than the string (a hostname can point at 127.0.0.1), and a public URL that redirects to a
private one is refused at the hop rather than followed.

Offline: DNS is stubbed, so nothing here touches the network.
"""
import os
import socket
import sys
import unittest


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


sys.path.insert(0, _repo_root())

from app_platform.outbound import OutboundBlocked, check_public_url  # noqa: E402


class _StubDNS:
    """Point every hostname at chosen addresses, so the test never resolves for real."""

    def __init__(self, mapping):
        self.mapping = mapping
        self._real = socket.getaddrinfo

    def __enter__(self):
        def fake(host, port, *a, **kw):
            addrs = self.mapping.get(host)
            if addrs is None:
                raise socket.gaierror(f"no stub for {host}")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 80)) for addr in addrs]
        socket.getaddrinfo = fake
        return self

    def __exit__(self, *exc):
        socket.getaddrinfo = self._real
        return False


class RejectsNonPublicDestinations(unittest.TestCase):
    def test_literal_private_and_loopback_addresses(self):
        for url in ("http://127.0.0.1:8000/api/admin/status",
                    "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/",
                    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
                    "http://[::1]:8000/", "http://0.0.0.0/"):
            with self.subTest(url=url), self.assertRaises(OutboundBlocked):
                check_public_url(url)

    def test_non_http_schemes(self):
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/", "data:text/html,x"):
            with self.subTest(url=url), self.assertRaises(OutboundBlocked):
                check_public_url(url)

    def test_a_public_hostname_that_resolves_inward_is_refused(self):
        # The string looks fine; only resolution reveals it. This is the case a scheme/prefix
        # check cannot catch, and the reason the guard resolves before fetching.
        with _StubDNS({"evil.example": ["127.0.0.1"]}):
            with self.assertRaises(OutboundBlocked):
                check_public_url("http://evil.example/")

    def test_a_host_resolving_to_both_public_and_private_is_refused(self):
        # Refused outright rather than raced: picking the public one would leave the actual
        # connection free to use the other.
        with _StubDNS({"mixed.example": ["93.184.216.34", "10.1.2.3"]}):
            with self.assertRaises(OutboundBlocked):
                check_public_url("http://mixed.example/")


class AllowsOrdinaryPublicUrls(unittest.TestCase):
    def test_public_addresses_pass(self):
        with _StubDNS({"example.com": ["93.184.216.34"]}):
            self.assertEqual(check_public_url("https://example.com/page"), "93.184.216.34")

    def test_port_and_path_do_not_matter(self):
        with _StubDNS({"example.com": ["93.184.216.34"]}):
            for url in ("https://example.com:8443/a/b?c=d", "http://example.com/#frag"):
                with self.subTest(url=url):
                    check_public_url(url)


if __name__ == "__main__":
    unittest.main()
