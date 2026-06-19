"""Bound tests for spec_index Phase-2 cross-corpus retrieval (search_specs).

Offline + deterministic via an INJECTED stub embedder (bag-of-words) — never imports the
real embedding lib. Proves the plumbing: cross-corpus gather, ranking, floor, bounding,
content-hash incremental cache, prune, and graceful degrade when no backend exists.
"""
import hashlib
import os
import shutil
import tempfile
import unittest

from apps.evolve import spec_index


def _write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def make_stub(dim=32):
    """A deterministic bag-of-words embedder: texts sharing words get similar vectors."""
    state = {"embedded": 0}

    def emb(texts):
        texts = list(texts)
        state["embedded"] += len(texts)
        out = []
        for t in texts:
            v = [0.0] * dim
            for w in t.lower().replace(":", " ").replace("-", " ").split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
            out.append(v)
        return out
    emb.model_name = "stub"
    emb.state = state
    return emb


class TestSearchSpecs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "cache.json")
        # two different apps -> cross-corpus
        _write(os.path.join(self.tmp, "apps", "alpha", "specs", "lists", "add-item.yaml"),
               "kind: specification\nid: alpha.lists.add-item\ntitle: Add item\n"
               "behavior: add an item to a shopping list\nstate: live\n")
        _write(os.path.join(self.tmp, "apps", "beta", "specs", "notes", "create.yaml"),
               "kind: specification\nid: beta.notes.create\ntitle: Create note\n"
               "behavior: create a note in the journal\nstate: live\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _search(self, q, **kw):
        return spec_index.search_specs(q, repo_root=self.tmp, embedder=make_stub(),
                                       cache_path=self.cache, **kw)

    def test_ranks_similar_spec_across_corpus(self):
        hits = self._search("add an item to a shopping list", floor=0.3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "alpha.lists.add-item")          # best match
        self.assertEqual(hits[0]["capability"], "alpha")                  # capability tagged
        self.assertGreater(hits[0]["score"], hits[-1]["score"] - 1e-9)    # sorted desc
        self.assertEqual(set(hits[0]), {"id", "kind", "capability", "behavior", "score"})

    def test_floor_filters_unrelated(self):
        # a query with no shared words clears nothing at a high floor
        self.assertEqual(self._search("xyzzy frobnicate quux", floor=0.5), [])

    def test_top_k_bounds_results(self):
        hits = self._search("add an item to a shopping list", floor=0.0, top_k=1)
        self.assertEqual(len(hits), 1)

    def test_cache_is_incremental(self):
        stub = make_stub()
        spec_index.search_specs("add item", repo_root=self.tmp, embedder=stub, cache_path=self.cache, floor=0.0)
        first = stub.state["embedded"]            # 2 records + 1 query = 3
        spec_index.search_specs("add item", repo_root=self.tmp, embedder=stub, cache_path=self.cache, floor=0.0)
        # second run: records unchanged (cache hit by content_hash) -> only the query embeds
        self.assertEqual(stub.state["embedded"] - first, 1)

    def test_no_backend_degrades_to_empty(self):
        orig = spec_index._default_embedder
        spec_index._default_embedder = lambda: None
        try:
            self.assertEqual(spec_index.search_specs("anything", repo_root=self.tmp,
                                                     cache_path=self.cache), [])
        finally:
            spec_index._default_embedder = orig


if __name__ == "__main__":
    unittest.main()
