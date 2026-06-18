"""Tests for apps/evolve/schema.py — the C/F/S loader validation (EVOLVE.md §4).

Bound to spec evolve.cfs-store.schema-validate. Pure stdlib unittest, no DB/Claude:
    python3 -m unittest discover -s tests
"""
import os
import tempfile
import unittest

from apps.evolve import schema

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SPECS = os.path.join(REPO, "apps", "evolve", "specs")


def _write(root, relpath, body):
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


class TestRealEvolveTree(unittest.TestCase):
    """The hand-authored apps/evolve/specs/ tree must be well-formed."""

    def test_validates_clean_as_bootstrap(self):
        recs, rep = schema.load_and_validate(
            SPECS, repo_root=REPO, capability="evolve", on_main=True, bootstrap=True)
        self.assertTrue(rep.ok, msg="real tree should validate:\n" + str(rep))

    def test_record_counts(self):
        recs, _ = schema.load_and_validate(SPECS, repo_root=REPO, capability="evolve")
        kinds = [r.kind for r in recs]
        self.assertEqual(kinds.count("capability"), 1)
        self.assertGreaterEqual(kinds.count("feature"), 8)
        self.assertGreaterEqual(kinds.count("specification"), 8)

    def test_kind_contract_ignores_sdlc_and_docs(self):
        paths = schema.scan_paths(SPECS)
        self.assertTrue(paths, "should find C/F/S files")
        self.assertFalse(any(p.endswith("sdlc.yaml") for p in paths),
                         "sdlc.yaml has no `kind` and must be ignored")

    def test_main_invariant_fires_without_bootstrap(self):
        # The seed is all `proposed`; enforcing the steady-state main invariant
        # (bootstrap=False) must reject it — proving the check works.
        _, rep = schema.load_and_validate(
            SPECS, repo_root=REPO, capability="evolve", on_main=True, bootstrap=False)
        self.assertFalse(rep.ok)
        self.assertTrue(any("on main" in e for e in rep.errors))

    def test_every_id_is_path_consistent(self):
        recs, _ = schema.load_and_validate(SPECS, repo_root=REPO, capability="evolve")
        for r in recs:
            self.assertEqual(r.id, schema.path_derived_id(r.path, SPECS, "evolve"))


class TestSyntheticNegatives(unittest.TestCase):
    """Each malformation must be caught."""

    def _validate(self, root):
        return schema.load_and_validate(root, repo_root=root, capability="cap")[1]

    def test_duplicate_id(self):
        with tempfile.TemporaryDirectory() as d:
            r = os.path.join(d, "specs", "cap")
            _write(r, "_capability.yaml", "kind: capability\nid: cap\ntitle: Cap\nstate: live\nscope: x\n")
            _write(r, "f/_feature.yaml", "kind: feature\nid: cap.f\ntitle: F\nstate: live\n")
            # second spec deliberately reuses the id of the first
            _write(r, "f/a.yaml", "kind: specification\nid: cap.f.a\ntitle: A\nstate: live\nbehavior: b\n")
            _write(r, "f/dup.yaml", "kind: specification\nid: cap.f.a\ntitle: Dup\nstate: live\nbehavior: b\n")
            rep = self._validate(r)
            self.assertTrue(any("duplicate id" in e for e in rep.errors), str(rep))

    def test_depth_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            r = os.path.join(d, "specs", "cap")
            _write(r, "_capability.yaml", "kind: capability\nid: cap\ntitle: Cap\nstate: live\nscope: x\n")
            # a feature whose id has 3 segments (spec depth)
            _write(r, "f/_feature.yaml", "kind: feature\nid: cap.f.x\ntitle: F\nstate: live\n")
            rep = self._validate(r)
            self.assertTrue(any("depth" in e for e in rep.errors), str(rep))

    def test_missing_parent(self):
        with tempfile.TemporaryDirectory() as d:
            r = os.path.join(d, "specs", "cap")
            _write(r, "_capability.yaml", "kind: capability\nid: cap\ntitle: Cap\nstate: live\nscope: x\n")
            # spec with no feature record present
            _write(r, "orphan/a.yaml", "kind: specification\nid: cap.orphan.a\ntitle: A\nstate: live\nbehavior: b\n")
            rep = self._validate(r)
            self.assertTrue(any("parent" in e for e in rep.errors), str(rep))

    def test_bad_state_and_missing_behavior(self):
        with tempfile.TemporaryDirectory() as d:
            r = os.path.join(d, "specs", "cap")
            _write(r, "_capability.yaml", "kind: capability\nid: cap\ntitle: Cap\nstate: live\nscope: x\n")
            _write(r, "f/_feature.yaml", "kind: feature\nid: cap.f\ntitle: F\nstate: live\n")
            _write(r, "f/a.yaml", "kind: specification\nid: cap.f.a\ntitle: A\nstate: bogus\n")
            rep = self._validate(r)
            self.assertTrue(any("invalid state" in e for e in rep.errors), str(rep))
            self.assertTrue(any("no `behavior`" in e for e in rep.errors), str(rep))

    def test_untested_is_warning_not_error(self):
        with tempfile.TemporaryDirectory() as d:
            r = os.path.join(d, "specs", "cap")
            _write(r, "_capability.yaml", "kind: capability\nid: cap\ntitle: Cap\nstate: live\nscope: x\n")
            _write(r, "f/_feature.yaml", "kind: feature\nid: cap.f\ntitle: F\nstate: live\n")
            _write(r, "f/a.yaml", "kind: specification\nid: cap.f.a\ntitle: A\nstate: live\nbehavior: b\n")
            rep = self._validate(r)
            self.assertTrue(rep.ok, "untested should not be a hard error:\n" + str(rep))
            self.assertTrue(any("untested" in w for w in rep.warnings), str(rep))


if __name__ == "__main__":
    unittest.main(verbosity=2)
