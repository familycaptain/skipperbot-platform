"""Bound tests for apps/evolve/spec_index.py (Phase 1 — capability-scoped read).

Offline, deterministic, no embedding lib: builds a fixture app tree under a temp
repo_root and asserts capability_specs reads it co-located, bounded, and sorted.
"""
import os
import tempfile
import shutil
import unittest

from apps.evolve import spec_index


def _write(path: str, body: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


class TestCapabilitySpecs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        root = os.path.join(self.tmp, "apps", "demo", "specs")
        _write(os.path.join(root, "_capability.yaml"),
               "kind: capability\nid: demo\ntitle: Demo\n")
        _write(os.path.join(root, "lists", "_feature.yaml"),
               "kind: feature\nid: demo.lists\ntitle: Lists\n")
        _write(os.path.join(root, "lists", "add-item.yaml"),
               "kind: specification\nid: demo.lists.add-item\ntitle: Add item\n"
               "behavior: Adds an item to a list.\nstate: live\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_colocated_tree_bounded_and_sorted(self):
        recs = spec_index.capability_specs("demo", repo_root=self.tmp)
        ids = [r["id"] for r in recs]
        self.assertEqual(ids, ["demo", "demo.lists", "demo.lists.add-item"])  # sorted
        spec = next(r for r in recs if r["kind"] == "specification")
        self.assertEqual(spec["behavior"], "Adds an item to a list.")
        self.assertEqual(set(recs[0].keys()), {"id", "kind", "title", "behavior"})

    def test_behavior_is_truncated_to_one_line(self):
        root = os.path.join(self.tmp, "apps", "demo", "specs", "lists")
        _write(os.path.join(root, "long.yaml"),
               "kind: specification\nid: demo.lists.long\ntitle: Long\n"
               "behavior: " + ("x " * 200) + "\nstate: live\n")
        rec = next(r for r in spec_index.capability_specs("demo", repo_root=self.tmp)
                   if r["id"] == "demo.lists.long")
        self.assertLessEqual(len(rec["behavior"]), spec_index._BEHAVIOR_CHARS)
        self.assertTrue(rec["behavior"].endswith("…"))

    def test_missing_capability_is_empty_not_error(self):
        self.assertEqual(spec_index.capability_specs("nope", repo_root=self.tmp), [])
        self.assertEqual(spec_index.capability_specs("", repo_root=self.tmp), [])

    def test_format_renders_and_flags_new_capability(self):
        self.assertIn("demo.lists.add-item",
                      spec_index.format_capability_specs("demo", repo_root=self.tmp))
        self.assertIn("no existing specs",
                      spec_index.format_capability_specs("nope", repo_root=self.tmp))


if __name__ == "__main__":
    unittest.main()
