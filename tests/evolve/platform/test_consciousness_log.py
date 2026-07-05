"""Bound tests for the consciousness log — Phase 0 (specs/CONSCIOUSNESS.md §11, §13).

DB-free: pure-function checks (lane derivation, domain mapping), a monkeypatched
writer to prove the §11.9/§11.5 semantics, and source/migration assertions that
the shadow hooks + schema exist. Run: python -m unittest tests.evolve.platform.test_consciousness_log
"""
import os
import re
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


from app_platform import consciousness as C  # noqa: E402


class LaneDerivation(unittest.TestCase):
    """§15: lanes are a pure derivation — person for conversation, domain for alarms."""

    def test_inbound_message_lane_is_sender(self):
        self.assertEqual(C.lane_for("message", "rodney", "skipper", "chat"), "person:rodney")

    def test_outbound_message_lane_is_recipient(self):
        # inbound-from-P and outbound-to-P share ONE lane (one mouth per conversation)
        self.assertEqual(C.lane_for("message", "skipper", "rodney", "chat"), "person:rodney")

    def test_connection_event_lane_is_the_person_concerned(self):
        self.assertEqual(C.lane_for("event", "system", "rodney", "system"), "person:rodney")

    def test_alarm_event_lane_is_domain(self):
        self.assertEqual(C.lane_for("event", "system", None, "chores"), "domain:chores")

    def test_activity_and_summary_lanes_are_domain(self):
        self.assertEqual(C.lane_for("activity", "skipper", None, "goals"), "domain:goals")
        self.assertEqual(C.lane_for("summary", "skipper", None, "system"), "domain:system")


class WriterContract(unittest.TestCase):
    """§11.9: one atomic single-statement INSERT; §11.5 pre-attended semantics."""

    def test_insert_is_single_statement_with_returning(self):
        sql = C._INSERT_SQL.upper()
        self.assertIn("INSERT INTO CONSCIOUSNESS_LOG", sql)
        self.assertIn("RETURNING", sql)
        self.assertNotIn("BEGIN", sql)
        self.assertNotIn(";", C._INSERT_SQL.strip().rstrip(";"))  # no second statement

    def test_seq_is_never_supplied_by_the_writer(self):
        # seq comes from the bigserial INSIDE the statement (§11.9) — the column
        # list must not include it.
        cols = C._INSERT_SQL.split("VALUES")[0]
        self.assertNotIn("seq", cols)

    def test_pre_attended_forces_not_owed_and_records_responder(self):
        captured = {}

        def fake_exec(sql, params):
            captured["params"] = params
            return {"id": params[0], "seq": 1, "created_at": None, "lane": params[5]}

        with mock.patch.object(C, "execute_returning", fake_exec):
            row = C.log_event(
                kind="message", who_from="rodney", who_to="skipper",
                domain="chat", content="hi",
                needs_attention=True,               # caller asks…
                pre_attended_by="legacy-pipeline",  # …but a live responder is engaged
            )
        params = captured["params"]
        self.assertFalse(params[12], "needs_attention must be forced False when pre-attended")
        self.assertTrue(params[13], "attended_at must be set (CASE WHEN true)")
        self.assertIn("legacy-pipeline", params[11])  # payload records the responder
        self.assertEqual(row["lane"], "person:rodney")

    def test_rejects_unknown_kind_and_empty_content(self):
        with self.assertRaises(ValueError):
            C.log_event(kind="thought", who_from="x", domain="chat", content="y")
        with self.assertRaises(ValueError):
            C.log_event(kind="message", who_from="x", domain="chat", content="")

    def test_shadow_writer_never_raises(self):
        with mock.patch.object(C, "execute_returning", side_effect=RuntimeError("db down")):
            self.assertIsNone(C.shadow_log_event(
                kind="message", who_from="r", who_to="skipper", domain="chat", content="x"))


class DomainMapping(unittest.TestCase):
    def test_source_type_mapping(self):
        for st, dom in [("pm_thinking", "pm"), ("pm_checkin", "pm"),
                        ("goal_thinking", "goals"), ("onboarding_greeting", "onboarding"),
                        ("chores_morning", "chores"), ("bounty_digest", "bounties"),
                        ("reminder", "reminders"), ("job", "system"), ("", "system")]:
            self.assertEqual(C.domain_for_source_type(st), dom, st)


class MigrationShape(unittest.TestCase):
    """§11.2 schema shipped as a platform migration."""

    def setUp(self):
        self.sql = _read("migrations/001_consciousness_log.sql")

    def test_columns_and_constraints(self):
        for needle in ("consciousness_log", "seq", "bigserial", "lane",
                       "needs_attention", "attended_at", "thread_id", "reply_to",
                       "vector(1536)", "'message', 'activity', 'event', 'summary'"):
            self.assertIn(needle, self.sql, needle)

    def test_attention_queue_partial_index(self):
        self.assertRegex(self.sql, r"idx_cl_attention[\s\S]*WHERE needs_attention AND attended_at IS NULL")

    def test_backfill_idempotency_index(self):
        self.assertIn("idx_cl_legacy_id", self.sql)
        self.assertIn("payload->>'legacy_id'", self.sql)

    def test_no_transaction_wrapper(self):
        # the platform runner wraps each file — files must not BEGIN/COMMIT
        self.assertNotRegex(self.sql, r"(?m)^\s*(BEGIN|COMMIT)\b")

    def test_entity_registration_and_legacy_column_relax(self):
        self.assertIn("'cl'", self.sql)
        self.assertEqual(len(re.findall(r"ALTER COLUMN \w+\s+DROP NOT NULL", self.sql)), 3)


class ShadowHooksPresent(unittest.TestCase):
    """§13 Phase 0: every producer mirrors into the log via shadow_log_event."""

    def test_chat_post_turn(self):
        src = _read("chat.py")
        self.assertIn("shadow_log_event", src)
        self.assertIn('pre_attended_by="legacy-pipeline"', src)

    def test_create_notification_single_hook(self):
        src = _read("apps/notifications/store.py")
        self.assertIn("shadow_log_event", src)
        self.assertIn("domain_for_source_type", src)
        # delivery.py is deliberately NOT hooked (double-log guard)
        self.assertNotIn("shadow_log_event", _read("apps/notifications/delivery.py"))

    def test_arrival_event(self):
        src = _read("agent.py")
        self.assertIn('kind="event"', src)
        self.assertIn('"desktop.arrival"', src)

    def test_domain_outcome_rows(self):
        self.assertIn('kind="activity"', _read("apps/goals/domain.py"))
        self.assertIn('kind="activity"', _read("apps/goals/pm_domain.py"))

    def test_bypass_paths_hooked(self):
        self.assertIn("shadow_log_event", _read("apps/goals/pm_runner.py"))
        self.assertIn("_shadow_bounty_dm", _read("apps/bounties/handlers.py"))


if __name__ == "__main__":
    unittest.main()
