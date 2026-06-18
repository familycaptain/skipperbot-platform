"""Tests for apps/evolve/variance.py — variance detection (spec evolve.cfs-store.variance-detect)."""
import os
import tempfile
import unittest

from apps.evolve import schema, variance

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SPECS = os.path.join(REPO, "apps", "evolve", "specs")


def _records(root, repo):
    recs, _ = schema.load_and_validate(root, repo_root=repo, capability=os.path.basename(root.rstrip("/")))
    return recs


class TestRealTreeVariance(unittest.TestCase):
    def test_built_substrate_is_reconciled(self):
        # The cfs-store + process-engine specs are now `live` and their code exists,
        # so the real tree should report ZERO missing-impl (full reconciliation).
        # (Negative detection is covered by TestSyntheticVariance below.)
        recs = _records(SPECS, REPO)
        vs = variance.detect(recs, repo_root=REPO)
        missing = [v for v in vs if v.reason == variance.MISSING_IMPL]
        self.assertEqual(missing, [], f"unexpected missing-impl: {[str(v) for v in missing]}")

    def test_live_specs_are_tested_drafts_may_be_untested(self):
        # Invariant: a `live` spec must have bound tests; only non-live (proposed)
        # specs may be UNTESTED. (Proposed build-validate/promotion specs are drafts.)
        recs = _records(SPECS, REPO)
        state = {r.id: r.state for r in recs}
        vs = variance.detect(recs, repo_root=REPO)
        untested_live = [v.spec_id for v in vs
                         if v.reason == variance.UNTESTED and state.get(v.spec_id) == "live"]
        self.assertEqual(untested_live, [], f"live specs must be tested: {untested_live}")


class TestSyntheticVariance(unittest.TestCase):
    def _spec(self, **over):
        raw = {"kind": "specification", "id": "cap.f.a", "title": "A",
               "state": "live", "behavior": "b", "implements": [], "tests": [{"type": "unit", "path": "t"}]}
        raw.update(over)
        return schema.Record(kind="specification", id=raw["id"], title="A",
                             path="/x/specs/cap/f/a.yaml", state="live", raw=raw)

    def test_untested(self):
        vs = variance.detect([self._spec(tests=[])], repo_root="/")
        self.assertEqual([v.reason for v in vs], [variance.UNTESTED])

    def test_missing_impl(self):
        vs = variance.detect([self._spec(implements=["nope/does_not_exist.py"])], repo_root="/")
        self.assertTrue(any(v.reason == variance.MISSING_IMPL for v in vs))

    def test_drift_against_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            rel = "code.py"
            with open(os.path.join(d, rel), "w") as fh:
                fh.write("v1")
            spec = self._spec(implements=[rel])
            base = {spec.id: variance.baseline_for(spec, repo_root=d)}
            # no drift yet
            self.assertFalse([v for v in variance.detect([spec], repo_root=d, baselines=base)
                              if v.reason == variance.DRIFTED])
            # mutate the file -> drift
            with open(os.path.join(d, rel), "w") as fh:
                fh.write("v2-changed")
            vs = variance.detect([spec], repo_root=d, baselines=base)
            self.assertTrue(any(v.reason == variance.DRIFTED for v in vs))

    def test_injected_test_runner(self):
        spec = self._spec()
        vs = variance.detect([spec], repo_root="/", test_runner=lambda r: [{"path": "t", "status": "red"}])
        self.assertTrue(any(v.reason == variance.TEST_FAILING for v in vs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
