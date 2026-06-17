"""Bound tests for spec platform.auth.cookie-session.

principal_from_request resolves an HTTP request's principal with the Authorization
header as the PRIMARY path, and falls back to the `sb_session` cookie ONLY for SAFE
methods (GET/HEAD). The cookie is ignored for mutating methods (the CSRF guard), and
when both a valid header and a valid cookie are present the header wins.

Pure stdlib unittest — no DB, no network. verify_token is stubbed so we exercise the
transport logic, not the crypto/DB path: only the literal "GOOD" verifies.
"""

import unittest

import app_platform.auth as auth


class _FakeRequest:
    """Minimal stand-in for a Starlette Request: headers + cookies + method."""

    def __init__(self, method="GET", headers=None, cookies=None):
        self.method = method
        self.headers = headers or {}
        self.cookies = cookies or {}


class CookieSessionAuthTests(unittest.TestCase):
    def setUp(self):
        self._orig = auth.verify_token
        # Only the literal "GOOD" verifies; everything else is rejected.
        auth.verify_token = lambda tok: {"name": "alice"} if tok == "GOOD" else None

    def tearDown(self):
        auth.verify_token = self._orig

    def test_get_with_only_good_cookie_resolves(self):
        req = _FakeRequest(method="GET", cookies={"sb_session": "GOOD"})
        self.assertEqual(auth.principal_from_request(req), {"name": "alice"})

    def test_post_with_only_good_cookie_is_ignored(self):
        req = _FakeRequest(method="POST", cookies={"sb_session": "GOOD"})
        self.assertIsNone(auth.principal_from_request(req))

    def test_head_with_only_good_cookie_resolves(self):
        req = _FakeRequest(method="HEAD", cookies={"sb_session": "GOOD"})
        self.assertEqual(auth.principal_from_request(req), {"name": "alice"})

    def test_get_with_valid_header_no_cookie_resolves(self):
        req = _FakeRequest(method="GET", headers={"authorization": "Bearer GOOD"})
        self.assertEqual(auth.principal_from_request(req), {"name": "alice"})

    def test_get_with_bad_cookie_resolves_nothing(self):
        # Expired/tampered/revoked cookie: verify_token returns None.
        req = _FakeRequest(method="GET", cookies={"sb_session": "BAD"})
        self.assertIsNone(auth.principal_from_request(req))

    def test_get_with_neither_resolves_nothing(self):
        self.assertIsNone(auth.principal_from_request(_FakeRequest(method="GET")))

    def test_get_with_valid_header_and_cookie_prefers_header(self):
        # Both present and both valid; principal comes from the HEADER. We make the
        # cookie a value that would also verify, then confirm the header path was
        # taken by checking the cookie is never consulted via a tracking cookies map.
        consulted = {"cookie_read": False}

        class _TrackingCookies(dict):
            def get(self, key, default=None):
                consulted["cookie_read"] = True
                return super().get(key, default)

        req = _FakeRequest(
            method="GET",
            headers={"authorization": "Bearer GOOD"},
            cookies=_TrackingCookies({"sb_session": "GOOD"}),
        )
        self.assertEqual(auth.principal_from_request(req), {"name": "alice"})
        self.assertFalse(
            consulted["cookie_read"],
            "header is primary: cookie must not be consulted when the header resolves",
        )


if __name__ == "__main__":
    unittest.main()
