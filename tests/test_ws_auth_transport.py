"""Bound tests for spec platform.auth.ws-token-transport (issue #7).

Two surfaces:
  A. principal_from_ws resolves the bearer token from the Sec-WebSocket-Protocol
     header, falls through a malformed subprotocol to the Authorization header, and
     no longer honors a ?token= querystring.
  B. the access-log redaction filter masks any auth token in a request line.

Pure stdlib unittest — no DB, no network. verify_token is stubbed so we exercise the
transport logic, not the crypto/DB path.
"""

import base64
import logging
import unittest

import app_platform.auth as auth
from app_platform.log_redaction import AccessLogTokenRedactor


def _b64url(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class _FakeWS:
    """Minimal stand-in for a Starlette WebSocket: headers + query_params."""

    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


class WsTokenTransportTests(unittest.TestCase):
    def setUp(self):
        self._orig = auth.verify_token
        # Only the literal "GOOD" verifies; everything else is rejected.
        auth.verify_token = lambda tok: {"name": "alice"} if tok == "GOOD" else None

    def tearDown(self):
        auth.verify_token = self._orig

    def test_subprotocol_path_without_querystring(self):
        ws = _FakeWS(headers={"sec-websocket-protocol": "bearer." + _b64url("GOOD")})
        self.assertEqual(auth.principal_from_ws(ws), {"name": "alice"})

    def test_first_matching_subprotocol_wins_others_ignored(self):
        ws = _FakeWS(headers={
            "sec-websocket-protocol": "json, bearer." + _b64url("GOOD") + ", x",
        })
        self.assertEqual(auth.principal_from_ws(ws), {"name": "alice"})

    def test_malformed_subprotocol_falls_through_to_header(self):
        ws = _FakeWS(headers={
            "sec-websocket-protocol": "bearer." + _b64url("BAD"),
            "authorization": "Bearer GOOD",
        })
        self.assertEqual(auth.principal_from_ws(ws), {"name": "alice"})

    def test_querystring_token_is_no_longer_accepted(self):
        # The ?token= path was removed (operator decision Q2=A); a token in the
        # query must NOT authenticate.
        ws = _FakeWS(query={"token": "GOOD"})
        self.assertIsNone(auth.principal_from_ws(ws))

    def test_no_credentials_returns_none(self):
        self.assertIsNone(auth.principal_from_ws(_FakeWS()))


class AccessLogRedactionTests(unittest.TestCase):
    def _render(self, msg, args=None):
        rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, msg, args, None)
        AccessLogTokenRedactor().filter(rec)
        return rec.getMessage()

    def test_ws_querystring_token_redacted(self):
        out = self._render("GET /ws/alice?token=SECRET123 HTTP/1.1 101")
        self.assertIn("***", out)
        self.assertNotIn("SECRET123", out)

    def test_access_token_param_redacted(self):
        out = self._render('GET /api/x?access_token=ABC HTTP/1.1 200')
        self.assertNotIn("ABC", out)
        self.assertIn("***", out)

    def test_tokenless_line_unchanged(self):
        raw = "GET /api/health HTTP/1.1 200"
        self.assertEqual(self._render(raw), raw)

    def test_redacts_path_in_args_tuple(self):
        # uvicorn renders the request line through record.args, not a literal msg.
        out = self._render(
            '%s - "%s %s HTTP/%s" %s',
            ("127.0.0.1", "GET", "/ws/alice?token=SECRET123", "1.1", 101),
        )
        self.assertNotIn("SECRET123", out)
        self.assertIn("***", out)


if __name__ == "__main__":
    unittest.main()
