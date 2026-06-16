"""Bound test for spec backups.documentation.setup-guide (issue #3).

The backups setup guide must document the REAL Settings-based config and must
not regress to the retired .env credential model. These assertions pin the
correctness-critical facts the reviews flagged so the doc can't silently drift.

Pure stdlib unittest — run with ``python3 -m unittest discover -s tests/docs``.
"""

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "docs" / "backups-setup.md"
EXTENDED = REPO / "docs" / "03-extended-functionality.md"

# Retired .env credential model — creds live in Settings (encrypted), never in
# .env. NB: the real Settings key is the *lowercase* ``gdrive_impersonate_email``;
# only the UPPERCASE env-var spelling is the retired form, so that one is matched
# case-sensitively to avoid colliding with the legitimate Settings key.
RETIRED_KEYFILE_VAR = "BACKUP_GOOGLE_KEY_FILE"            # unique to the old model
RETIRED_IMPERSONATE_ENV = "GDRIVE_IMPERSONATE_EMAIL"     # uppercase env form only


class BackupsSetupDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = GUIDE.read_text(encoding="utf-8")
        cls.extended = EXTENDED.read_text(encoding="utf-8")

    def test_guide_exists_and_substantial(self):
        self.assertTrue(GUIDE.is_file(), "docs/backups-setup.md must exist")
        self.assertGreater(len(self.guide), 1500, "guide too thin to be a real walkthrough")
        self.assertTrue(self.guide.lstrip().startswith("#"), "guide must open with an H1")

    def test_guide_documents_real_settings_keys(self):
        for key in ("gdrive_service_account_json", "gdrive_impersonate_email",
                    "filesystem_path"):
            self.assertIn(key, self.guide, f"guide must reference Settings key {key}")

    def test_guide_covers_both_destinations_and_core_actions(self):
        for token in ("Google Drive", "Filesystem", "Run backup now", "RESTORE.md"):
            self.assertIn(token, self.guide, f"guide must mention {token!r}")

    def test_guide_states_key_preconditions_and_cautions(self):
        # Workspace-only (personal Gmail can't use Drive).
        self.assertIn("Workspace", self.guide)
        self.assertIn("gmail", self.guide.lower(), "must warn personal Gmail is unsupported")
        # Folder must be named exactly 'Backups'.
        self.assertIn("Backups", self.guide)
        # The zip carries .env secrets.
        self.assertIn(".env", self.guide)

    def test_guide_does_not_teach_retired_env_var_model(self):
        # Key-file var is unique to the retired model — ban it case-insensitively.
        self.assertNotIn(RETIRED_KEYFILE_VAR, self.guide.upper(),
                         f"guide must not instruct setting {RETIRED_KEYFILE_VAR} in .env")
        # The uppercase env-var spelling of the impersonate setting is the retired
        # form; the lowercase Settings key is correct, so match case-sensitively.
        self.assertNotIn(RETIRED_IMPERSONATE_ENV, self.guide,
                         "guide must use the lowercase Settings key, not the .env var")

    def test_extended_doc_points_at_guide_and_drops_stale_keys(self):
        upper = self.extended.upper()
        self.assertNotIn("BACKUP_GOOGLE_KEY_FILE", upper,
                         "stale .env key-file guidance must be removed from 03-extended")
        self.assertIn("backups-setup.md", self.extended,
                      "03-extended must link to the new guide")
        # Keep the anchor so the top-of-doc TOC link doesn't dangle.
        self.assertIn("## Google Drive Backups", self.extended)


if __name__ == "__main__":
    unittest.main()
