"""An app's ids resolve whichever way its manifest spells id_format.

`resolve_entity_id` matched an id against the RAW manifest value with `startswith`. An app
declaring `id_format: "img-{hex8}"` therefore matched nothing — no real id begins with the
literal text "{hex8}" — so `is_valid_entity_id` rejected every one of that app's ids and a
generic entity link to its records could not be created. Apps that omitted `id_format` got
the working "<prefix>-" default and were fine, so the failure tracked how somebody chose to
write a manifest, not anything about the app.

It failed silently: an id that matches no prefix is indistinguishable from an unknown id,
so eleven apps looked like they had no linkable records rather than looking broken.

Offline: the registry is stubbed, so these exercise the matching rule itself rather than
whatever happens to be registered on one box.
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
sys.modules.setdefault("psycopg2", mock.MagicMock())
sys.modules.setdefault("psycopg2.extras", mock.MagicMock())
sys.modules.setdefault("psycopg2.pool", mock.MagicMock())
sys.modules.setdefault("dotenv", mock.MagicMock())

from data_layer import entity_types  # noqa: E402

# Both spellings, plus the overlapping-prefix cases that longest-first matching exists for.
ROWS = [
    {"prefix": "g",   "name": "goal",     "id_format": "g-",           "table_name": "goals"},
    {"prefix": "img", "name": "image",    "id_format": "img-{hex8}",   "table_name": "images"},
    {"prefix": "beh", "name": "behavior", "id_format": "beh-{hex8}",   "table_name": "behaviors"},
    {"prefix": "sc",  "name": "score",    "id_format": "sc-",          "table_name": "scores"},
    {"prefix": "sch", "name": "schedule", "id_format": "sch-{hex8}",   "table_name": "schedules"},
    {"prefix": "l",   "name": "list",     "id_format": "l-",           "table_name": "lists"},
    {"prefix": "li",  "name": "listitem", "id_format": "li-{hex8}",    "table_name": "list_items"},
]


class _Registry:
    def __enter__(self):
        self.patch = mock.patch.object(entity_types, "_load_all", return_value=ROWS)
        self.patch.start()
        entity_types.invalidate_cache()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        entity_types.invalidate_cache()
        return False


class IdsResolveRegardlessOfHowTheFormatIsWritten(unittest.TestCase):
    def test_a_placeholder_format_still_matches_real_ids(self):
        with _Registry():
            for entity_id, want in (("img-1a2b3c4d", "image"),
                                    ("beh-deadbeef", "behavior"),
                                    ("sch-00112233", "schedule")):
                with self.subTest(entity_id=entity_id):
                    self.assertTrue(entity_types.is_valid_entity_id(entity_id))
                    self.assertEqual(entity_types.entity_type_name(entity_id), want)

    def test_a_plain_format_still_matches(self):
        with _Registry():
            self.assertEqual(entity_types.entity_type_name("g-abc123"), "goal")

    def test_matching_is_on_the_prefix_not_the_whole_format(self):
        # Before the fix, the ONLY string that matched an "img-{hex8}" registration was
        # the template text itself; a real id did not. Now the prefix is what matters, so
        # the id resolves and the template — which merely shares that prefix — is not
        # special either way.
        with _Registry():
            self.assertEqual(entity_types.entity_type_name("img-1a2b3c4d"), "image")
            self.assertEqual(entity_types.entity_type_name("img-"), "image")

    def test_an_unknown_prefix_is_still_unknown(self):
        with _Registry():
            for entity_id in ("zz-123", "", "nodash", "{hex8}"):
                with self.subTest(entity_id=entity_id):
                    self.assertFalse(entity_types.is_valid_entity_id(entity_id))

    def test_longest_prefix_still_wins(self):
        # The reason the list is sorted: 'sch-' must beat 'sc-', 'li-' must beat 'l-'.
        # Truncating formats must not disturb that ordering.
        with _Registry():
            self.assertEqual(entity_types.entity_type_name("sch-00112233"), "schedule")
            self.assertEqual(entity_types.entity_type_name("sc-99"), "score")
            self.assertEqual(entity_types.entity_type_name("li-1a2b3c4d"), "listitem")
            self.assertEqual(entity_types.entity_type_name("l-55"), "list")

    def test_the_table_lookup_follows(self):
        # is_valid_entity_id is the gate, but callers then ask for the source table;
        # a half-fixed resolve would validate and then return no table.
        with _Registry():
            self.assertEqual(entity_types.entity_table_name("img-1a2b3c4d"), "images")


class TheTruncationRule(unittest.TestCase):
    def test_it_keeps_everything_before_the_first_brace(self):
        for raw, want in (("img-{hex8}", "img-"), ("g-", "g-"), ("x-{a}-{b}", "x-"),
                          ("", ""), ("{hex8}", "")):
            with self.subTest(raw=raw):
                self.assertEqual(entity_types._literal_prefix(raw), want)

    def test_a_format_that_is_only_a_placeholder_matches_nothing(self):
        # "" would otherwise startswith-match every id ever, silently claiming them all.
        rows = [{"prefix": "bad", "name": "bad", "id_format": "{hex8}", "table_name": "t"},
                {"prefix": "g", "name": "goal", "id_format": "g-", "table_name": "goals"}]
        with mock.patch.object(entity_types, "_load_all", return_value=rows):
            entity_types.invalidate_cache()
            try:
                self.assertEqual(entity_types.entity_type_name("g-1"), "goal")
                self.assertFalse(entity_types.is_valid_entity_id("anything-else"))
            finally:
                entity_types.invalidate_cache()


class TheImagesManifestMatchesWhatIsMinted(unittest.TestCase):
    def test_the_declared_format_is_the_prefix_the_code_produces(self):
        # agent.py mints i-<hex8>; the manifest used to declare img-, so the app's own ids
        # did not match its own registration.
        import yaml
        with open(os.path.join(REPO, "apps/images/manifest.yaml"), encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh)
        fmt = manifest["entity_types"][0]["id_format"]
        self.assertTrue(fmt.startswith("i-"), f"images declares {fmt!r}")

        with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
            agent_src = fh.read()
        self.assertIn('image_id = f"i-{', agent_src)


if __name__ == "__main__":
    unittest.main()
