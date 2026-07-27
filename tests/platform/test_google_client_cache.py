"""Bound test for spec platform.google-clients.cache-built-service (issue #99).

apps/backups/gdrive.py and skipper_gmail.py must build their googleapiclient
service ONCE per identity and reuse it (mirroring apps/email/gmail_client.py), so
the SSL transport / discovery doc / trust store load once per identity instead of
on every call. Only a SUCCESSFULLY built service is cached; a config change
rotates the (hashed) key; a build error never poisons the cache.

Deterministic + DB-free: the config/settings seams, Credentials, and
googleapiclient build are monkeypatched; no network, no real SA JSON.

Run with ``python3 -m unittest tests.evolve.platform.test_google_client_cache``.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__import__("repo_paths").ROOT)
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SA_JSON = '{"type": "service_account", "client_email": "svc@x.iam", "k": 1}'
SA_JSON_2 = '{"type": "service_account", "client_email": "svc2@x.iam", "k": 2}'


class _BuildCounter:
    """Stands in for googleapiclient.discovery.build; unique object per call."""

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def __call__(self, *a, **k):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated build failure")
        return object()


def _fake_creds():
    creds = mock.MagicMock(name="creds")
    creds.with_subject.return_value = creds
    return creds


class GdriveServiceCache(unittest.TestCase):

    def setUp(self):
        import apps.backups.gdrive as gdrive
        self.gdrive = gdrive
        gdrive._reset_service_cache()

    def _patches(self, build_counter, *, raw=SA_JSON, email="admin@x.com"):
        import apps.backups.gdrive as gdrive
        return [
            mock.patch.object(gdrive, "_config", side_effect=lambda key, default=None: {
                "gdrive_enabled": True,
                "gdrive_impersonate_email": email,
            }.get(key, default)),
            mock.patch("app_platform.settings.get", return_value=raw),
            mock.patch("google.oauth2.service_account.Credentials.from_service_account_info",
                       return_value=_fake_creds()),
            mock.patch("googleapiclient.discovery.build", build_counter),
        ]

    def test_same_identity_builds_once(self):
        bc = _BuildCounter()
        ps = self._patches(bc)
        for p in ps:
            p.start()
        try:
            s1 = self.gdrive._build_service()
            s2 = self.gdrive._build_service()
        finally:
            for p in ps:
                p.stop()
        self.assertIs(s1, s2, "same identity must return the SAME cached service")
        self.assertEqual(bc.calls, 1, "build() must run once, not per call")

    def test_config_change_rebuilds(self):
        bc = _BuildCounter()
        ps = self._patches(bc, raw=SA_JSON)
        for p in ps:
            p.start()
        try:
            self.gdrive._build_service()
        finally:
            for p in ps:
                p.stop()
        # different SA JSON -> different key -> fresh build
        ps2 = self._patches(bc, raw=SA_JSON_2)
        for p in ps2:
            p.start()
        try:
            self.gdrive._build_service()
        finally:
            for p in ps2:
                p.stop()
        self.assertEqual(bc.calls, 2, "a changed SA JSON must rotate the key and rebuild")

    def test_build_failure_not_cached(self):
        bc = _BuildCounter(fail=True)
        ps = self._patches(bc)
        for p in ps:
            p.start()
        try:
            with self.assertRaises(RuntimeError):
                self.gdrive._build_service()
            with self.assertRaises(RuntimeError):
                self.gdrive._build_service()
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(bc.calls, 2, "a failed build must NOT be cached (next call retries)")
        self.assertEqual(len(self.gdrive._service_cache), 0, "cache must be empty after failures")


class SkipperGmailServiceCache(unittest.TestCase):

    def setUp(self):
        import skipper_gmail
        self.sg = skipper_gmail
        skipper_gmail._reset_service_cache()

    def test_same_identity_builds_once(self):
        import skipper_gmail
        bc = _BuildCounter()
        ps = [
            mock.patch("app_platform.settings.get", return_value=SA_JSON),
            mock.patch.object(skipper_gmail, "get_skipper_email", return_value="me@x.com"),
            mock.patch.object(skipper_gmail, "Credentials",
                              **{"from_service_account_info.return_value": _fake_creds()}),
            mock.patch.object(skipper_gmail, "build", bc),
        ]
        for p in ps:
            p.start()
        try:
            s1 = self.sg._build_service()
            s2 = self.sg._build_service()
        finally:
            for p in ps:
                p.stop()
        self.assertIs(s1, s2)
        self.assertEqual(bc.calls, 1)


if __name__ == "__main__":
    unittest.main()
