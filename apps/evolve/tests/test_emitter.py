"""Tests for apps/evolve/emitter.py — the background activity emitter batches run-field
updates + events per instance and flushes them; a flush failure never propagates."""
import time
import unittest

from apps.evolve.emitter import EventEmitter


class TestEventEmitter(unittest.TestCase):
    def _collect(self):
        got = []
        return got, (lambda iid, fields, events: got.append((iid, dict(fields), list(events))))

    def test_batches_fields_and_events_per_instance(self):
        got, flush = self._collect()
        em = EventEmitter(flush, interval=0.05).start()
        em.run("i1", title="T", status="running")
        em.event("i1", "design", "tool", "$ grep foo")
        em.event("i1", "design", "emit", "emit → result")
        em.run("i1", status="building")           # later field wins
        em.stop()
        merged = {}
        for iid, fields, events in got:
            merged.setdefault(iid, {"fields": {}, "events": []})
            merged[iid]["fields"].update(fields)
            merged[iid]["events"] += events
        self.assertEqual(merged["i1"]["fields"]["status"], "building")
        self.assertEqual(merged["i1"]["fields"]["title"], "T")
        self.assertEqual([e["message"] for e in merged["i1"]["events"]],
                         ["$ grep foo", "emit → result"])

    def test_flush_failure_is_swallowed(self):
        def boom(iid, fields, events):
            raise RuntimeError("pi unreachable")
        em = EventEmitter(boom, interval=0.05).start()
        em.event("i1", "a", "tool", "x")
        em.stop()   # must not raise
        self.assertTrue(True)

    def test_empty_instance_id_ignored(self):
        got, flush = self._collect()
        em = EventEmitter(flush, interval=0.05).start()
        em.event("", "a", "tool", "x")
        em.run("", status="running")
        em.stop()
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
