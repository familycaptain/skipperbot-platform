"""Tests for apps/evolve/store.py — boot-sync projection + edit-serialize round-trip.

Bound to specs evolve.cfs-store.boot-sync and evolve.cfs-store.edit-serialize.
"""
import os
import tempfile
import unittest

from apps.evolve import schema, store

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SPECS = os.path.join(REPO, "specs", "evolve")


class TestBootSync(unittest.TestCase):
    def _boot(self, backend):
        s = store.Store(backend)
        rep = s.boot_sync(SPECS, repo_root=REPO, capability="evolve",
                          on_main=True, bootstrap=True)
        return s, rep

    def test_projects_real_tree_inmemory(self):
        s, rep = self._boot(store.InMemoryBackend())
        self.assertTrue(rep.ok, str(rep))
        self.assertEqual(len(s.all()), len(schema.scan_paths(SPECS)))
        self.assertEqual(len(s.by_kind("capability")), 1)

    def test_projects_real_tree_sqlite(self):
        s, rep = self._boot(store.SqliteBackend(":memory:"))
        self.assertTrue(rep.ok, str(rep))
        self.assertEqual(len(s.all()), len(schema.scan_paths(SPECS)))
        rec = s.get("evolve.cfs-store.boot-sync")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["kind"], "specification")
        self.assertIn("implements", rec["raw"])

    def test_tree_shape(self):
        s, _ = self._boot(store.InMemoryBackend())
        tree = s.tree()
        self.assertIn("evolve", tree)
        self.assertIn("evolve.cfs-store", tree["evolve"])
        self.assertIn("evolve.cfs-store.boot-sync", tree["evolve"]["evolve.cfs-store"])

    def test_children(self):
        s, _ = self._boot(store.InMemoryBackend())
        feats = s.children("evolve")
        self.assertTrue(all(f["kind"] == "feature" for f in feats))
        self.assertGreaterEqual(len(feats), 8)

    def test_refuses_corpus_with_hard_errors(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "specs", "cap")
            os.makedirs(root)
            # a spec with no parent feature -> hard error
            with open(os.path.join(root, "_capability.yaml"), "w") as fh:
                fh.write("kind: capability\nid: cap\ntitle: C\nstate: live\nscope: x\n")
            os.makedirs(os.path.join(root, "f"))
            with open(os.path.join(root, "f", "a.yaml"), "w") as fh:
                fh.write("kind: specification\nid: cap.f.a\ntitle: A\nstate: live\nbehavior: b\n")
            s = store.Store(store.InMemoryBackend())
            rep = s.boot_sync(root, repo_root=d, capability="cap")
            self.assertFalse(rep.ok)
            self.assertEqual(len(s.all()), 0, "backend must be untouched on error")


class TestEditSerialize(unittest.TestCase):
    def test_round_trip_preserves_data(self):
        # parse a real record -> serialize -> re-parse -> data must be equal
        src = os.path.join(SPECS, "cfs-store", "boot-sync.yaml")
        rec = schema.parse_file(src)
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "round.yaml")
            store.write_record_file(rec, dst)
            rec2 = schema.parse_file(dst)
            self.assertEqual(rec.raw, rec2.raw)
            self.assertEqual(rec.id, rec2.id)

    def test_serialize_is_deterministic_and_key_ordered(self):
        rec = schema.parse_file(os.path.join(SPECS, "cfs-store", "boot-sync.yaml"))
        out1 = store.serialize_record(rec.raw)
        out2 = store.serialize_record(rec.raw)
        self.assertEqual(out1, out2)
        # kind/id/title lead the file
        head = out1.splitlines()[:3]
        self.assertTrue(head[0].startswith("kind:"))
        self.assertTrue(head[1].startswith("id:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
