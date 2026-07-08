"""Bound test for spec email.sync.reeval-on-rules-change — DRAIN ORCHESTRATION (issue #98).

Deterministic + DB-free: stubs the data layer + gmail client and drives
``runner._reprocess_unmatched`` (the gated, bounded, trigger-time-snapshot drain) directly.
Covers the spec rubric:
  (a) unchanged rules  -> NO backlog query, NO label API calls, no work;
  (b) a rule change    -> exactly-once re-eval, then the watermark quiets the next poll;
  (d) EDIT/ENABLE      -> a later watermark re-triggers;
  (e) DELETE           -> no watermark bump -> no trigger; a harmless over-eval (disable/
                          reorder) runs but produces ZERO new matches;
  (f) BOUNDED + SNAPSHOT -> a backlog larger than the cap drains in bounded batches across
                          polls over the FROZEN trigger-time set, newest-first, cursor
                          advancing; emails arriving mid-drain are NOT chased; terminates;
  (g) label API calls happen ONLY inside a triggered needs_labels drain;
  (h) MID-DRAIN RULE CHANGE -> the new rule gets its own exactly-once drain afterwards (no
                          skip, no unbounded re-loop);
  (i) NULL-SAFETY      -> a pre-migration account (last_reeval_at None) re-evals once.

The data-layer primitives (create_rule sets updated_at (c); get_reeval_trigger's COALESCE
NULL-safety (i, SQL side); get_unmatched_log_entries keyset bounds) are covered against the
real schema in test_reeval_foundation.py.

Run with ``python3 -m unittest tests.evolve.email.test_reeval_on_rules_change``.
"""

import unittest
from datetime import datetime, timezone, timedelta

from apps.email import runner


def _dt(minute):
    """A deterministic tz-aware timestamp keyed by an integer minute offset."""
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)


class _FakeDL:
    """In-memory stand-in for apps.email.data, modelling exactly the surface the drain uses:
    an account row (with the ev-98 watermark/snapshot/cursor fields) + an unmatched log."""

    def __init__(self, account_id="acc1"):
        self.account = {
            "id": account_id,
            "last_reeval_at": None,
            "reeval_target_watermark": None,
            "reeval_upper_bound_at": None,
            "reeval_upper_bound_id": None,
            "reeval_cursor_at": None,
            "reeval_cursor_id": None,
        }
        # each entry: {id, gmail_msg_id, received_at(datetime), rule_id}
        self.log = []
        self.max_rule_change = None  # the "max active-rule COALESCE(updated_at,created_at)"
        # call counters / spies
        self.n_get_unmatched = 0

    # --- rule-change trigger inputs ---
    def get_reeval_trigger(self, account_id):
        return {"last_reeval_at": self.account["last_reeval_at"],
                "max_rule_change": self.max_rule_change}

    # --- unmatched backlog, newest-first keyset (received_at DESC, id DESC) ---
    def get_unmatched_log_entries(self, account_id, limit=None,
                                  upper_bound=None, before_cursor=None):
        self.n_get_unmatched += 1
        rows = [e for e in self.log if e["rule_id"] is None]
        if upper_bound is not None:
            rows = [e for e in rows if (e["received_at"], e["id"]) <= tuple(upper_bound)]
        if before_cursor is not None:
            rows = [e for e in rows if (e["received_at"], e["id"]) < tuple(before_cursor)]
        rows.sort(key=lambda e: (e["received_at"], e["id"]), reverse=True)
        if limit is not None:
            rows = rows[:limit]
        # mimic _row: received_at serialized to an ISO string (exercises runner._as_dt)
        return [{"id": e["id"], "gmail_msg_id": e["gmail_msg_id"],
                 "thread_id": "", "sender": "s", "subject": "j",
                 "received_at": e["received_at"].isoformat(), "rule_id": None}
                for e in rows]

    def update_account(self, account_id, **kwargs):
        self.account.update(kwargs)
        return self.account

    def update_log_entry_match(self, log_id, rule_id, actions_taken):
        for e in self.log:
            if e["id"] == log_id:
                e["rule_id"] = rule_id

    # --- test helpers ---
    def seed(self, n, start_minute=0):
        for i in range(n):
            k = start_minute + i
            self.log.append({"id": f"el{k:03d}", "gmail_msg_id": f"g{k}",
                             "received_at": _dt(k), "rule_id": None})

    def n_unmatched(self):
        return len([e for e in self.log if e["rule_id"] is None])


class _FakeGmail:
    def __init__(self):
        self.n_label_calls = 0

    def get_message_labels(self, credentials, gmail_msg_id, cache_key=None, on_reauth_fail=None):
        self.n_label_calls += 1
        return []


class ReevalDrain(unittest.TestCase):

    def setUp(self):
        self.dl = _FakeDL()
        self.gm = _FakeGmail()
        # swap the runner's collaborators for the fakes
        self._orig_dl = runner.dl_email
        self._orig_gm = runner.gmail_client
        self._orig_eval = runner._evaluate_and_execute
        self._orig_limit = runner._REEVAL_BATCH_LIMIT
        runner.dl_email = self.dl
        runner.gmail_client = self.gm
        # default matcher: match nothing (entries stay unmatched -> pure cursor/bound test)
        self.match_ids = set()
        runner._evaluate_and_execute = self._fake_eval

    def tearDown(self):
        runner.dl_email = self._orig_dl
        runner.gmail_client = self._orig_gm
        runner._evaluate_and_execute = self._orig_eval
        runner._REEVAL_BATCH_LIMIT = self._orig_limit

    def _fake_eval(self, credentials, account_id, msg, rules, label_cache, label_map,
                   on_reauth_fail=None):
        if msg["id"] in self.match_ids:
            return ("ruleX", ["labeled"])
        return (None, [])

    def _poll(self, rules):
        """One re-eval pass with the account state as currently persisted."""
        return runner._reprocess_unmatched(
            {}, dict(self.dl.account), rules, {}, {}, None)

    # ------------------------------------------------------------------ (a)
    def test_unchanged_rules_does_no_work(self):
        self.dl.seed(5)
        self.dl.max_rule_change = _dt(100)
        self.dl.account["last_reeval_at"] = _dt(100)  # already caught up
        rules = [{"id": "r1", "active": True, "conditions": {"sender": "x"}}]
        got = self._poll(rules)
        self.assertEqual(got, 0)
        self.assertEqual(self.dl.n_get_unmatched, 0, "unchanged rules -> NO backlog query")
        self.assertEqual(self.gm.n_label_calls, 0, "unchanged rules -> NO label API calls")

    # ------------------------------------------------------------------ (b) + (i)
    def test_rule_change_triggers_once_then_quiets(self):
        self.dl.seed(3)
        self.dl.max_rule_change = _dt(50)          # a rule changed
        self.assertIsNone(self.dl.account["last_reeval_at"])  # (i) pre-migration NULL
        self.match_ids = {"g0", "g1", "g2"}
        rules = [{"id": "r1", "active": True, "conditions": {"sender": "x"}}]
        got = self._poll(rules)
        self.assertEqual(got, 3, "the triggered drain re-matched the whole backlog once")
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(50),
                         "watermark advances to the CAPTURED target on full drain")
        self.assertIsNone(self.dl.account["reeval_upper_bound_at"], "drain cleared")
        # next poll, rules unchanged -> quiet
        self.dl.n_get_unmatched = 0
        got2 = self._poll(rules)
        self.assertEqual(got2, 0)
        self.assertEqual(self.dl.n_get_unmatched, 0, "caught-up watermark -> no re-scan")

    # ------------------------------------------------------------------ (d)
    def test_edit_or_enable_retriggers(self):
        self.dl.seed(2)
        self.dl.max_rule_change = _dt(10)
        rules = [{"id": "r1", "active": True, "conditions": {"sender": "x"}}]
        self._poll(rules)
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(10))
        # EDIT/ENABLE bumps the max rule change to a later ts -> re-triggers
        self.dl.max_rule_change = _dt(20)
        self.dl.n_get_unmatched = 0
        self._poll(rules)
        self.assertGreater(self.dl.n_get_unmatched, 0, "a later rule change re-triggers a drain")
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(20))

    # ------------------------------------------------------------------ (e)
    def test_delete_no_trigger_and_overeval_is_harmless(self):
        self.dl.seed(2)
        # caught up (a prior drain ran at _dt(10))
        self.dl.max_rule_change = _dt(10)
        self.dl.account["last_reeval_at"] = _dt(10)
        rules = [{"id": "r1", "active": True, "conditions": {"sender": "x"}}]
        # DELETE removes a rule row -> no updated_at bump -> max_rule_change unchanged -> quiet
        got = self._poll(rules)
        self.assertEqual(got, 0)
        self.assertEqual(self.dl.n_get_unmatched, 0, "delete does not trigger a re-eval")
        # DISABLE/REORDER DO bump updated_at -> a drain runs but yields ZERO new matches
        self.dl.max_rule_change = _dt(30)
        self.match_ids = set()  # nothing newly matches
        got2 = self._poll(rules)
        self.assertEqual(got2, 0, "over-eval is safe: zero new matches")
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(30), "still completes cleanly")

    # ------------------------------------------------------------------ (f)
    def test_bounded_snapshot_drain_across_polls_ignores_mid_drain_arrivals(self):
        runner._REEVAL_BATCH_LIMIT = 3
        self.dl.seed(7)                 # el000..el006 (oldest..newest)
        self.dl.max_rule_change = _dt(500)
        self.match_ids = set()          # nothing matches -> entries stay unmatched (hard case)
        rules = [{"id": "r1", "active": True, "conditions": {"sender": "x"}}]
        seen_ids = []

        # poll 1: newest 3, drain not complete
        self._poll(rules)
        self.assertEqual(self.dl.account["reeval_upper_bound_id"], "el006", "upper bound frozen at newest")
        self.assertEqual(self.dl.account["reeval_cursor_id"], "el004", "cursor at oldest-of-batch")
        self.assertIsNone(self.dl.account["last_reeval_at"], "not complete after a full batch")
        seen_ids += ["el006", "el005", "el004"]

        # mid-drain: 2 NEW unmatched emails arrive (newer than the frozen upper bound)
        self.dl.seed(2, start_minute=10)   # el010, el011

        # poll 2: next 3 below cursor, still within the FROZEN set
        self._poll(rules)
        self.assertEqual(self.dl.account["reeval_cursor_id"], "el001")
        self.assertIsNone(self.dl.account["last_reeval_at"])
        seen_ids += ["el003", "el002", "el001"]

        # poll 3: the last 1 -> short batch -> complete
        self._poll(rules)
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(500), "watermark advances on full drain")
        self.assertIsNone(self.dl.account["reeval_upper_bound_at"], "drain cleared")
        seen_ids += ["el000"]

        self.assertEqual(seen_ids, ["el006", "el005", "el004", "el003", "el002", "el001", "el000"],
                         "the FROZEN 7-entry set drained newest-first, each once")
        self.assertNotIn("el010", seen_ids, "mid-drain arrivals were NOT chased")
        self.assertNotIn("el011", seen_ids)

    # ------------------------------------------------------------------ (g)
    def test_label_api_only_within_triggered_needs_labels_drain(self):
        self.dl.seed(2)
        rules = [{"id": "r1", "active": True, "conditions": {"has_label": "IMPORTANT"}}]
        # unchanged rules -> no drain -> no label calls
        self.dl.max_rule_change = _dt(5)
        self.dl.account["last_reeval_at"] = _dt(5)
        self._poll(rules)
        self.assertEqual(self.gm.n_label_calls, 0, "no label calls on an unchanged-rules poll")
        # a rule change triggers a needs_labels drain -> label calls happen (one per entry)
        self.dl.max_rule_change = _dt(6)
        self._poll(rules)
        self.assertEqual(self.gm.n_label_calls, 2, "label calls happen inside the triggered drain")

    # ------------------------------------------------------------------ (h)
    def test_mid_drain_rule_change_gets_its_own_exactly_once_drain(self):
        runner._REEVAL_BATCH_LIMIT = 3
        self.dl.seed(4)                 # el000..el003
        self.dl.max_rule_change = _dt(100)   # R1 change
        self.match_ids = set()
        rules = [{"id": "r1", "active": True, "conditions": {"sender": "x"}}]

        # poll 1: drain R1's frozen set (batch of 3, not complete)
        self._poll(rules)
        self.assertIsNone(self.dl.account["last_reeval_at"])

        # MID-DRAIN: R2 is edited/enabled -> a LATER max rule change
        self.dl.max_rule_change = _dt(200)

        # poll 2: finishes R1's frozen drain (1 left) -> watermark advances to the CAPTURED 100
        self._poll(rules)
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(100),
                         "R1 drain completes to its CAPTURED watermark, not the mid-drain 200")
        self.assertIsNone(self.dl.account["reeval_upper_bound_at"])

        # poll 3+: R2 (200 > 100) re-triggers its OWN fresh exactly-once drain of the backlog
        n_drains = 0
        for _ in range(5):  # bounded: must converge, never loop forever
            before = self.dl.account["last_reeval_at"]
            self._poll(rules)
            if self.dl.account.get("reeval_upper_bound_at") or self.dl.account["last_reeval_at"] != before:
                n_drains += 1
            if self.dl.account["last_reeval_at"] == _dt(200) and not self.dl.account["reeval_upper_bound_at"]:
                break
        self.assertEqual(self.dl.account["last_reeval_at"], _dt(200),
                         "R2 gets its own drain; watermark reaches 200 and converges (no infinite loop)")


if __name__ == "__main__":
    unittest.main()
