"""Bound test for spec platform.email.gmail-service-cache-selfheal (issue #102).

Two coupled fixes in apps/email:
  * STABLE per-account cache key — for a no-refresh-token account whose access
    token rotates hourly, keying the service cache on an explicit cache_key (the
    account id) reuses ONE entry instead of stranding a fresh service each hour.
  * 401 / invalid_grant SELF-HEAL — _execute_with_reauth invalidates + REBUILDS
    the service and re-runs the request builder on the FRESH service exactly once;
    a still-revoked credential fires a persistent, idempotent reconnect nudge
    (runner-owned) and raises without looping. No token material is ever logged.

Deterministic + DB-free at the client layer: googleapiclient build + Credentials
are stubbed; no network, no real tokens. The runner-level notification test stubs
the notifications shim + user lookup. Needs the product runtime (imports
apps.email.*), so it runs on the test host.

Run: python3 -m unittest tests.evolve.email.test_gmail_service_cache_selfheal
"""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError


def _http_error(status):
    return HttpError(SimpleNamespace(status=status, reason="x"), b"{}")


class _BuildCounter:
    """Stands in for googleapiclient.discovery.build — a unique object per call."""
    def __init__(self):
        self.calls = 0
    def __call__(self, *a, **k):
        self.calls += 1
        return SimpleNamespace(_svc_n=self.calls)


def _fake_credentials(**kw):
    # A valid creds object so _build_service skips the real proactive refresh.
    return SimpleNamespace(valid=True, token="tok", expiry=None,
                           refresh_token=kw.get("refresh_token"))


class GmailServiceCache(unittest.TestCase):
    def setUp(self):
        import apps.email.gmail_client as gc
        self.gc = gc
        gc._service_cache.clear()
        self._p = [
            mock.patch.object(gc, "build", _BuildCounter()),
            mock.patch.object(gc, "Credentials", _fake_credentials),
        ]
        for p in self._p:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._p])
        self.addCleanup(gc._service_cache.clear)

    # (a) explicit cache_key + rotating access token, no refresh_token -> ONE entry
    def test_stable_key_no_stranding(self):
        gc = self.gc
        gc._build_service({"token": "t1"}, cache_key="ea-1")
        gc._build_service({"token": "t2"}, cache_key="ea-1")  # token rotated
        gc._build_service({"token": "t3"}, cache_key="ea-1")
        self.assertEqual(list(gc._service_cache.keys()), ["ea-1"])
        self.assertEqual(len(gc._service_cache), 1)

    # (b) key precedence: explicit cache_key, else refresh_token, else token
    def test_cache_key_precedence(self):
        gc = self.gc
        self.assertEqual(gc._service_cache_key({"refresh_token": "rt", "token": "t"}, "ea-1"), "ea-1")
        self.assertEqual(gc._service_cache_key({"refresh_token": "rt", "token": "t"}), "rt")
        self.assertEqual(gc._service_cache_key({"token": "t"}), "t")
        self.assertEqual(gc._service_cache_key({}), "")

    # (c) evict-on-rebuild: invalidate then rebuild -> one entry, NEW service object
    def test_evict_on_rebuild(self):
        gc = self.gc
        creds = {"token": "t1"}
        a = gc._build_service(creds, cache_key="ea-1")
        gc.invalidate_service(creds, cache_key="ea-1")
        self.assertEqual(len(gc._service_cache), 0)
        b = gc._build_service(creds, cache_key="ea-1")
        self.assertEqual(len(gc._service_cache), 1)
        self.assertIsNot(a, b)  # a genuinely fresh service, no stale reference

    # (d) self-heal: 401 on the first service, success on the REBUILT one
    def test_self_heal_retries_on_rebuilt_service(self):
        gc = self.gc
        on_reauth = mock.Mock()
        seen = []

        def build_request(svc):
            seen.append(svc)
            if len(seen) == 1:
                raise _http_error(401)
            return ("ok", svc)

        with mock.patch.object(gc, "invalidate_service", wraps=gc.invalidate_service) as inval:
            result = gc._execute_with_reauth({"token": "t1"}, "ea-1", build_request, on_reauth)
        self.assertEqual(result[0], "ok")
        self.assertEqual(len(seen), 2)
        self.assertIsNot(seen[0], seen[1])          # retry ran on the REBUILT service
        self.assertEqual(result[1], seen[1])
        inval.assert_called_once()
        self.assertEqual(inval.call_args.args[1] if len(inval.call_args.args) > 1
                         else inval.call_args.kwargs.get("cache_key"), "ea-1")
        on_reauth.assert_not_called()               # it healed — no reconnect nudge

    # (e) bounded + notify-once: 401 on both -> on_reauth once, raise, no loop
    def test_persistent_401_notifies_once_and_raises(self):
        gc = self.gc
        on_reauth = mock.Mock()
        calls = {"n": 0}

        def build_request(svc):
            calls["n"] += 1
            raise _http_error(401)

        with self.assertRaises(HttpError):
            gc._execute_with_reauth({"token": "t1"}, "ea-1", build_request, on_reauth)
        self.assertEqual(calls["n"], 2)             # initial + exactly one retry (no loop)
        on_reauth.assert_called_once()

    # (f) non-auth error is re-raised unchanged, no invalidate / no notify
    def test_non_auth_error_reraised(self):
        gc = self.gc
        on_reauth = mock.Mock()
        with mock.patch.object(gc, "invalidate_service", wraps=gc.invalidate_service) as inval:
            with self.assertRaises(ValueError):
                gc._execute_with_reauth({"token": "t1"}, "ea-1",
                                        lambda svc: (_ for _ in ()).throw(ValueError("boom")),
                                        on_reauth)
        inval.assert_not_called()
        on_reauth.assert_not_called()

    # (g) no token material on the auth-fail log path
    def test_no_token_in_logs_on_auth_fail(self):
        gc = self.gc
        with self.assertLogs(logging.getLogger(), level="WARNING") as cm:
            with self.assertRaises(HttpError):
                gc._execute_with_reauth({"token": "SECRET-TOKEN", "refresh_token": "SECRET-RT"},
                                        "ea-1",
                                        lambda svc: (_ for _ in ()).throw(_http_error(401)),
                                        None)
        logs = "\n".join(cm.output)
        self.assertNotIn("SECRET-TOKEN", logs)
        self.assertNotIn("SECRET-RT", logs)

    # (h) invalid_grant RefreshError -> reauth path; a generic RefreshError -> not
    def test_invalid_grant_vs_generic(self):
        gc = self.gc
        self.assertTrue(gc._is_auth_error(RefreshError("400 invalid_grant: expired")))
        self.assertFalse(gc._is_auth_error(RefreshError("some transient network blip")))
        self.assertTrue(gc._is_auth_error(_http_error(401)))
        self.assertFalse(gc._is_auth_error(_http_error(500)))

        on_reauth = mock.Mock()
        with self.assertRaises(RefreshError):
            gc._execute_with_reauth({"token": "t1"}, "ea-1",
                                    lambda svc: (_ for _ in ()).throw(RefreshError("invalid_grant")),
                                    on_reauth)
        on_reauth.assert_called_once()


class ReauthNudgeIdempotency(unittest.TestCase):
    """Runner-owned persistent reconnect nudge: at most one per account per day,
    re-armed on a successful sync."""
    def setUp(self):
        import apps.email.runner as runner
        self.runner = runner
        runner._reauth_notified.clear()
        self.addCleanup(runner._reauth_notified.clear)

    def _account(self):
        return {"id": "ea-1", "user_id": "katie"}

    def test_notify_once_then_deduped_by_recent_record(self):
        runner = self.runner
        created = []
        # First poll: no prior record -> create. Second poll: a recent record
        # exists -> skip (idempotent, no duplicate).
        recent_box = {"rows": []}

        def fake_get(recipient=None, source_type=None, source_id=None, limit=20):
            return recent_box["rows"]

        def fake_create(recipient, message, source_type="", source_id="", channel="", delivered=False):
            created.append({"recipient": recipient, "message": message, "channel": channel,
                            "source_id": source_id})
            from datetime import datetime, timezone
            recent_box["rows"] = [{"created_at": datetime.now(timezone.utc).isoformat()}]
            return {"id": "n-1"}

        with mock.patch("app_platform.notifications.create_notification", fake_create), \
             mock.patch("app_platform.notifications.get_notifications", fake_get):
            runner._notify_reauth_needed(self._account())
            runner._notify_reauth_needed(self._account())  # second failing poll same day

        self.assertEqual(len(created), 1)                    # exactly one nudge
        self.assertEqual(created[0]["channel"], "both")      # actively alerted
        self.assertEqual(created[0]["source_id"], "ea-1")
        self.assertNotIn("token", created[0]["message"].lower())
        self.assertIn("reconnect", created[0]["message"].lower())

    def test_missing_recipient_is_noop(self):
        runner = self.runner
        with mock.patch("app_platform.notifications.create_notification") as create, \
             mock.patch("app_platform.notifications.get_notifications", return_value=[]):
            runner._notify_reauth_needed({"id": "ea-1", "user_id": ""})
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
