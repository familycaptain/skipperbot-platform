"""Bound test for spec email.sync.reeval-on-rules-change — FOUNDATION pieces (issue #98).

Covers the data-layer primitives the gated snapshot-drain is built on (the drain
orchestration in runner._process_account is validated separately):
  * create_rule sets updated_at (was NULL) so a new rule triggers a re-eval;
  * get_reeval_trigger returns last_reeval_at + max active-rule COALESCE(updated_at,created_at);
  * get_unmatched_log_entries honors the newest-first (received_at, id) keyset LIMIT/upper_bound/
    before_cursor bounds consistently with its ORDER BY.

Runs against the real app_email schema (seeds + cleans up a throwaway account), so it
executes in the agent container on the test host.

Run with ``python3 -m unittest tests.evolve.email.test_reeval_foundation``.
"""

import unittest
from datetime import datetime, timezone, timedelta

from apps.email import data as ed
from app_platform.db import scoped_conn, execute_in_schema


def _cleanup(acc_id):
    execute_in_schema(ed.SCHEMA, "DELETE FROM email_log WHERE account_id=%s", (acc_id,))
    execute_in_schema(ed.SCHEMA, "DELETE FROM email_rules WHERE account_id=%s", (acc_id,))
    execute_in_schema(ed.SCHEMA, "DELETE FROM email_accounts WHERE id=%s", (acc_id,))


class ReevalFoundation(unittest.TestCase):

    def setUp(self):
        self.acc = ed.create_account("ev98-test-user", "ev98@example.com")
        self.acc_id = self.acc["id"]

    def tearDown(self):
        _cleanup(self.acc_id)

    def test_create_rule_sets_updated_at(self):
        r = ed.create_rule(self.acc_id, "r1", {"sender": "x@y.com"}, {"label": "L"})
        self.assertIsNotNone(r.get("updated_at"), "create_rule must set updated_at (not NULL)")

    def test_reeval_trigger_reads_watermark_and_max_rule_change(self):
        t0 = ed.get_reeval_trigger(self.acc_id)
        self.assertIsNone(t0["last_reeval_at"])
        self.assertIsNone(t0["max_rule_change"], "no rules yet -> None")
        ed.create_rule(self.acc_id, "r1", {"sender": "x@y.com"}, {"label": "L"})
        t1 = ed.get_reeval_trigger(self.acc_id)
        self.assertIsNotNone(t1["max_rule_change"], "an active rule -> a max change ts")
        # trigger fires: max_rule_change > COALESCE(last_reeval_at, -inf)
        self.assertTrue(t1["max_rule_change"] > (t1["last_reeval_at"] or datetime.min.replace(tzinfo=timezone.utc)))
        # advance the watermark past the rule change -> trigger no longer fires
        ed.update_account(self.acc_id, last_reeval_at=t1["max_rule_change"])
        t2 = ed.get_reeval_trigger(self.acc_id)
        self.assertFalse(t2["max_rule_change"] > t2["last_reeval_at"],
                         "after advancing last_reeval_at to the rule change, trigger is quiet")

    def _seed_log(self, n):
        # insert n unmatched log entries with strictly increasing received_at
        base = datetime.now(timezone.utc) - timedelta(hours=n)
        ids = []
        with scoped_conn(ed.SCHEMA) as conn:
            with conn.cursor() as cur:
                for i in range(n):
                    lid = ed._new_id("el")
                    cur.execute(
                        "INSERT INTO email_log (id, account_id, gmail_msg_id, received_at) "
                        "VALUES (%s,%s,%s,%s)",
                        (lid, self.acc_id, f"g{i}", base + timedelta(minutes=i)))
                    ids.append(lid)
            conn.commit()
        return ids  # oldest..newest

    def test_unmatched_newest_first_and_bounded(self):
        self._seed_log(5)
        all_e = ed.get_unmatched_log_entries(self.acc_id)
        self.assertEqual(len(all_e), 5)
        # newest-first
        rts = [e["received_at"] for e in all_e]
        self.assertEqual(rts, sorted(rts, reverse=True), "newest-first by received_at")
        # LIMIT
        self.assertEqual(len(ed.get_unmatched_log_entries(self.acc_id, limit=2)), 2)
        # upper_bound keyset freezes the set: bound at the 3rd-newest entry
        third = all_e[2]
        bounded = ed.get_unmatched_log_entries(
            self.acc_id, upper_bound=(third["received_at"], third["id"]))
        self.assertEqual(len(bounded), 3, "upper_bound includes entries at/below the keyset")
        self.assertNotIn(all_e[0]["id"], [e["id"] for e in bounded], "newer-than-bound excluded")
        # before_cursor continues strictly below the last processed keyset
        cur0 = all_e[0]
        after = ed.get_unmatched_log_entries(
            self.acc_id, before_cursor=(cur0["received_at"], cur0["id"]))
        self.assertEqual(len(after), 4)
        self.assertNotIn(cur0["id"], [e["id"] for e in after], "cursor entry excluded (strict <)")


if __name__ == "__main__":
    unittest.main()
