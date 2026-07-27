"""Bound test for spec platform.thinking.doc-observe-bounded-memories (issue #103)
— the _observe integration: catchup counters + forward progress under a BOUNDED
fetch.

The whole point of ev-103 is that _observe no longer loads the whole memories
table, so it can no longer derive catchup counters from len(all_memories). This
suite proves _observe now computes them from bounded COUNT queries and still
advances its cursor past an all-noise window:

  * cursor far from the end  -> total_memory_count == COUNT(*) of the table and
                                total_unprocessed_before_filter == COUNT after the
                                cursor (NOT len(batch)); >500 keeps catchup honest.
  * first run (no cursor)    -> total_unprocessed_before_filter == the full table
                                count (so catchup fires on a big fresh install).
  * cursor deleted           -> total_unprocessed_before_filter == the recent
                                window we loaded (parity: abandon the old backlog).
  * all-noise window         -> raw_last_id advances to the LAST examined row, so
                                the next cycle moves on (no permanent stall).

Needs the product runtime (imports apps.documents.domain -> config). Runs on the
test host where the runtime is present; all DB/embedding/folder/doc seams are
monkeypatched so it is deterministic and DB-free.

Run: python3 -m unittest tests.evolve.platform.test_doc_observe_catchup_counters
"""
import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

_EPOCH = datetime(2026, 1, 1)


def _mem(i):
    return {
        "id": f"m{i}", "content": f"c{i}", "tags": [], "about": None,
        "saved_by": "", "related_entities": [], "source_chat_id": "",
        "created_at": (_EPOCH + timedelta(seconds=i)).isoformat(),
    }


def _wm_cursor(latest_id):
    return [{"subject_id": "last_processed_batch",
             "content": json.dumps({"latest_id": latest_id})}]


class ObserveCatchupCounters(unittest.TestCase):
    def setUp(self):
        import apps.documents.domain as domain
        self.domain = domain

    def _observe(self, *, working_memory, batch, total, remaining,
                 noise=False):
        """Drive _observe with every external seam stubbed.

        `remaining` is what count_after_cursor returns (int, or None to simulate
        a deleted cursor). `total` is count_memories(). `batch` is what
        load_after_cursor returns.
        """
        d = self.domain
        p = [
            mock.patch("data_layer.skipper_state.list_states",
                       return_value=working_memory),
            mock.patch("data_layer.memories.load_after_cursor",
                       return_value=batch),
            mock.patch("data_layer.memories.count_memories",
                       return_value=total),
            mock.patch("data_layer.memories.count_after_cursor",
                       return_value=remaining),
            mock.patch("app_platform.folders.get_all_folders", return_value=[]),
            mock.patch("app_platform.folders.get_item_count", return_value=0),
            mock.patch("app_platform.folders.get_child_folders", return_value=[]),
            mock.patch("apps.documents.data.search_documents_hybrid",
                       return_value=[]),
            mock.patch("apps.documents.data.get_all_documents", return_value=[]),
            mock.patch("memory_store.get_embedding", return_value=None),
            mock.patch.object(d, "_memories_per_cycle", return_value=75),
            mock.patch.object(d, "_is_noise_memory", return_value=noise),
        ]
        for x in p:
            x.start()
        self.addCleanup(lambda ps=p: [x.stop() for x in ps])
        return d._observe()

    def test_counters_from_counts_not_len_batch(self):
        # Cursor far from the end: bounded batch is tiny, but the counters must
        # reflect the TRUE table + remaining (from COUNT queries), not len(batch).
        batch = [_mem(i) for i in range(10)]
        ctx = self._observe(working_memory=_wm_cursor("cur1"), batch=batch,
                            total=10000, remaining=800)
        self.assertEqual(ctx["total_memory_count"], 10000)
        self.assertEqual(ctx["total_unprocessed_before_filter"], 800)
        # sanity: it is NOT len(batch)
        self.assertNotEqual(ctx["total_unprocessed_before_filter"], len(batch))

    def test_first_run_reports_full_table_for_catchup(self):
        # No cursor -> everything is unprocessed, so catchup fires on a big fresh
        # install. remaining is irrelevant here (count_after_cursor not consulted).
        batch = [_mem(i) for i in range(75)]
        ctx = self._observe(working_memory=[], batch=batch,
                            total=6000, remaining=None)
        self.assertEqual(ctx["total_memory_count"], 6000)
        self.assertEqual(ctx["total_unprocessed_before_filter"], 6000)

    def test_deleted_cursor_reports_window_size(self):
        # Cursor gone -> count_after_cursor returns None -> report the recent
        # window we actually loaded (do not claim the abandoned backlog).
        batch = [_mem(i) for i in range(30)]
        ctx = self._observe(working_memory=_wm_cursor("gone"), batch=batch,
                            total=9000, remaining=None)
        self.assertEqual(ctx["total_memory_count"], 9000)
        self.assertEqual(ctx["total_unprocessed_before_filter"], len(batch))

    def test_all_noise_window_advances_cursor(self):
        # Forward progress: an all-noise bounded window yields 0 useful, but the
        # cursor (raw_last_id) advances to the LAST examined row so the next
        # cycle moves past it — no permanent stall.
        batch = [_mem(i) for i in range(5)]
        ctx = self._observe(working_memory=_wm_cursor("cur1"), batch=batch,
                            total=10000, remaining=500, noise=True)
        self.assertEqual(ctx["unprocessed_memory_count"], 0)   # none useful
        self.assertEqual(ctx["raw_last_id"], batch[-1]["id"])  # advanced past noise
        self.assertEqual(ctx["noise_filtered"], len(batch))


if __name__ == "__main__":
    unittest.main()
