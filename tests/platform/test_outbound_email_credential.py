"""One place for the household's outbound-email key.

Two apps send mail — the newsletter, and finances emailing the monthly report — and both
read the Resend key straight out of `RESEND_API_KEY`. That meant the key could only be set
by editing a file on the host and restarting, it appeared nowhere in Settings, and the
second app to want it copied the first app's approach rather than finding a shared one.

It now lives in Settings → Integrations, encrypted at rest, alongside the other credentials
that belong to no single app. The environment variable is still honoured, so an install
that predates the setting keeps working and a container can be handed a key with no
database.

The refusal matters as much as the lookup: a send with no key configured has to say where
to put one, or it is just a stack trace in a job log.
"""
import os
import sys
import unittest
from unittest import mock


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()
sys.path.insert(0, REPO)

from app_platform import email_delivery  # noqa: E402


def _settings(value=None, broken=False):
    st = mock.MagicMock()
    if broken:
        st.get.side_effect = RuntimeError("settings unavailable")
    else:
        st.get.return_value = value
    return mock.patch.dict(sys.modules, {"app_platform.settings": st})


class TheKeyComesFromSettingsFirst(unittest.TestCase):
    def test_the_configured_setting_wins(self):
        with _settings("key-from-settings"), mock.patch.dict(os.environ, {"RESEND_API_KEY": "key-from-env"}):
            self.assertEqual(email_delivery.resend_api_key(), "key-from-settings")

    def test_the_environment_is_the_fallback(self):
        with _settings(""), mock.patch.dict(os.environ, {"RESEND_API_KEY": "key-from-env"}):
            self.assertEqual(email_delivery.resend_api_key(), "key-from-env")

    def test_an_unreadable_settings_store_still_lets_the_environment_work(self):
        # A container handed a key must not be stopped by a database problem.
        with _settings(broken=True), mock.patch.dict(os.environ, {"RESEND_API_KEY": "key-from-env"}):
            self.assertEqual(email_delivery.resend_api_key(), "key-from-env")

    def test_whitespace_is_not_a_key(self):
        with _settings("   "), mock.patch.dict(os.environ, {"RESEND_API_KEY": "  "}):
            self.assertEqual(email_delivery.resend_api_key(), "")

    def test_nothing_configured_anywhere_is_empty_not_an_error(self):
        with _settings(""), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(email_delivery.resend_api_key(), "")


class TheRefusalSaysWhereToPutOne(unittest.TestCase):
    def test_it_raises_when_there_is_no_key(self):
        with _settings(""), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(email_delivery.OutboundEmailNotConfigured) as ctx:
                email_delivery.require_resend_api_key()
        msg = str(ctx.exception)
        self.assertIn("Settings", msg)
        self.assertIn("Integrations", msg)

    def test_it_returns_the_key_when_there_is_one(self):
        with _settings("k"), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(email_delivery.require_resend_api_key(), "k")


class ItIsOfferedInIntegrations(unittest.TestCase):
    def test_the_settings_panel_declares_it_as_a_secret(self):
        with open(os.path.join(REPO, "apps/settings/routes.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index('"name": "Integrations"')
        panel = src[start:start + 2600]
        self.assertIn('"key": "resend_api_key"', panel)
        self.assertIn('"secret": True', panel[panel.index('"resend_api_key"'):
                                              panel.index('"resend_api_key"') + 200])

    def test_the_capability_points_at_the_setting_not_only_the_env_var(self):
        # Otherwise the capability screen still tells people to edit a file.
        with open(os.path.join(REPO, "app_platform/capabilities.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index('name="resend"')
        block = src[start:start + 600]
        self.assertIn('("resend_api_key", "platform")', block)
        self.assertIn("Settings", block)


class BothSendersUseIt(unittest.TestCase):
    """The point of a shared helper is that nobody reads the environment directly."""

    APPS = (("newsletter", "sender.py"), ("finances", "emailer.py"))

    def _source(self, app, filename):
        for base in (os.path.join(REPO, "apps", app),
                     os.path.join(os.path.dirname(REPO), f"skipperbot-app-{app}")):
            path = os.path.join(base, filename)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    return fh.read()
        return None

    def test_neither_sender_reads_the_environment_itself(self):
        for app, filename in self.APPS:
            src = self._source(app, filename)
            if src is None:
                self.skipTest(f"{app} not checked out beside the platform")
            with self.subTest(app=app):
                self.assertIn("require_resend_api_key", src)
                self.assertNotIn('os.getenv("RESEND_API_KEY")', src)


if __name__ == "__main__":
    unittest.main()
