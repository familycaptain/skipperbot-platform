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
        # Q6: artifact-triggered activity rows come from the HANDS (goal_work);
        # routine pm sweeps log nothing (their sends are already log rows).
        self.assertIn('kind="activity"', _read("apps/goals/goal_work.py"))

    def test_bypass_paths_speak_in_one_voice(self):
        # Phase 3c: both former bypass paths now send REAL consciousness messages
        self.assertIn("send_message", _read("apps/goals/pm_runner.py"))
        self.assertIn('domain="pm"', _read("apps/goals/pm_runner.py"))
        self.assertIn("send_message", _read("apps/bounties/handlers.py"))
        self.assertIn('domain="bounties"', _read("apps/bounties/handlers.py"))


if __name__ == "__main__":
    unittest.main()


class TimelineRendering(unittest.TestCase):
    """Phase 1 (§12.4): the log tail as one multi-speaker native-turn array."""

    def setUp(self):
        from app_platform import context as X
        self.X = X

    def _row(self, **kw):
        base = dict(kind="message", who_from="rodney", who_to="skipper",
                    content="hi", payload=None)
        base.update(kw)
        return base

    def test_focal_person_plain_user_turn(self):
        m = self.X.render_event(self._row(), "rodney")
        self.assertEqual(m, {"role": "user", "content": "hi"})

    def test_other_person_is_speaker_tagged(self):
        m = self.X.render_event(self._row(who_from="jacob"), "rodney")
        self.assertEqual(m["role"], "user")
        self.assertTrue(m["content"].startswith("[jacob → skipper]:"))

    def test_skipper_to_focal_is_plain_assistant(self):
        m = self.X.render_event(
            self._row(who_from="skipper", who_to="rodney", content="hello"), "rodney")
        self.assertEqual(m, {"role": "assistant", "content": "hello"})

    def test_skipper_to_other_is_addressee_tagged(self):
        m = self.X.render_event(
            self._row(who_from="skipper", who_to="jacob", content="chores!"), "rodney")
        self.assertEqual(m["role"], "assistant")
        self.assertTrue(m["content"].startswith("[to jacob]:"))

    def test_write_actions_render_completed_marker(self):
        m = self.X.render_event(
            self._row(who_from="skipper", who_to="rodney", content="done",
                      payload={"write_actions": ["add_todo"]}), "rodney")
        self.assertIn("✓ Completed this turn", m["content"])
        self.assertIn("add_todo", m["content"])

    def test_activity_event_one_liners(self):
        a = self.X.render_event(self._row(kind="activity", who_from="skipper",
                                          who_to=None, content="checked goal X"), "rodney")
        self.assertEqual(a["role"], "assistant")
        self.assertTrue(a["content"].startswith("[activity]"))
        e = self.X.render_event(self._row(kind="event", who_from="system",
                                          who_to="rodney", content="rodney connected"), "rodney")
        self.assertEqual(e["role"], "user")
        self.assertTrue(e["content"].startswith("[system event]"))

    def test_chronology_is_array_order(self):
        rows = [
            self._row(content="A: msg1"),
            self._row(who_from="jacob", content="B: between"),
            self._row(content="A: msg2"),
        ]
        with mock.patch("app_platform.consciousness.tail", return_value=rows):
            out = self.X.build_chat_timeline("rodney")
        # boundary + 3 messages, interleaved exactly in log order (Q4)
        self.assertEqual(len(out), 4)
        self.assertIn("memory", out[0]["content"].lower())  # the boundary line
        self.assertIn("msg1", out[1]["content"])
        self.assertIn("between", out[2]["content"])
        self.assertIn("msg2", out[3]["content"])

    def test_visibility_rule_is_coherence_not_privacy(self):
        from app_platform import context as X
        b = X.TIMELINE_BOUNDARY.lower()
        # Coherence: replies must stand on their own for a reader who only saw
        # their own chat — bring context in. Explicitly NOT a privacy/secrecy rule.
        self.assertIn("only ever saw their own chat", b)
        self.assertIn("stands on its own", b)
        self.assertIn("not about secrecy", b)
        self.assertIn("sharing across the family is fine", b)
        self.assertIn("another one", b)   # the good/bad example is present

    def test_chat_seam_present(self):
        # Phase 5b: the timeline IS the history — no flag, no sessions dict.
        src = _read("chat.py")
        self.assertIn("build_chat_timeline", src)
        self.assertIn("write_actions", src)
        self.assertNotIn("sessions[", src)
        self.assertNotIn("consciousness_chat_enabled", src)


class Phase2Wiring(unittest.TestCase):
    """§13 Phase 2: attention system + chores skill + real producers."""

    def test_attention_module_contract(self):
        src = _read("app_platform/attention.py")
        for needle in ("GLOBAL_CAP = 3", "submit_message", "_lane_lock",
                       "claim_unattended"):
            self.assertIn(needle, src)
        self.assertIn("FOR UPDATE SKIP LOCKED", _read("app_platform/consciousness.py"))
        # messages-first admission
        self.assertIn('0 if r["kind"] == "message" else 1', src)

    def test_send_message_starts_thread_and_hands_off_transport(self):
        src = _read("app_platform/consciousness.py")
        self.assertIn("def send_message", src)
        self.assertIn("thread_id=thread_id or eid", src)
        self.assertIn('source_type="consciousness"', src)
        self.assertIn("def log_inbound_message", src)
        self.assertIn("interval '24 hours'", src)

    def test_notification_hook_skips_consciousness_transport(self):
        src = _read("apps/notifications/store.py")
        self.assertIn("_SkipShadow", src)
        self.assertIn('source_type == "consciousness"', src)

    def test_ws_routes_through_attention_unconditionally(self):
        # Phase 5b: attention is THE intake — no flag, no legacy fallback call.
        src = _read("agent.py")
        self.assertIn("submit_message", src)
        self.assertIn("start_attention", src)
        self.assertNotIn("attention_enabled", src)

    def test_chat_attention_mode_no_double_log(self):
        src = _read("chat.py")
        self.assertIn("log_event_id", src)
        self.assertIn("if log_event_id:", src)

    def test_chores_skill_registered_and_flagged(self):
        src = _read("apps/chores/handlers.py")
        self.assertIn('register_skill("chores"', src)
        self.assertIn("_fire_chores_alarm", src)
        self.assertIn("REFUSED", src)   # recipient allow-list guard
        self.assertIn("chore_id", src)


class Phase3aOnboarding(unittest.TestCase):
    """§13 Phase 3a: the greeting is a chat-skill turn on the connection event."""

    def test_connection_skill_registered_by_goals_app(self):
        src = _read("apps/goals/handlers.py")
        self.assertIn('register_skill("connection"', src)
        self.assertIn("_connection_skill_runner", src)

    def test_log_native_greet_once_no_claims(self):
        src = _read("apps/goals/handlers.py")
        # suppression reads the LOG (recent onboarding message), not a claim
        self.assertIn("domain='onboarding'", src)
        self.assertIn("_RECENT_GREETING_MINUTES", src)

    def test_one_call_greeting_uses_chat_skill_and_timeline(self):
        src = _read("apps/goals/handlers.py")
        self.assertIn("handle_chat", src)
        self.assertIn("build_chat_timeline", src)
        self.assertIn("send_message", src)

    def test_legacy_arrival_deleted(self):
        # Phase 5b: the connection skill is the ONLY greeting producer.
        src = _read("apps/goals/handlers.py")
        self.assertNotIn("onboarding_arrival_handler", src)
        self.assertIn("_connection_skill_runner", src)

    def test_consciousness_messages_render_as_chat_response(self):
        src = _read("apps/notifications/delivery.py")
        self.assertIn('in ("onboarding_greeting", "consciousness")', src)

    def test_attention_dispatches_connection_skill(self):
        src = _read("app_platform/attention.py")
        self.assertIn('get_skill("connection")', src)


class Phase3bGoalsSplit(unittest.TestCase):
    """§13 Phase 3b: oversight → pm sweep/router; execution → goal_work (hands)."""

    def test_goal_work_is_mouthless(self):
        src = _read("apps/goals/goal_work.py")
        self.assertIn("REFUSED: work sessions cannot message anyone", src)
        self.assertIn('!= "send_dm"', src)          # send_dm filtered from tools
        self.assertIn("report_milestone", src)       # results go via events
        self.assertIn("needs_attention=True", src)   # ... owed to the voice
        self.assertIn("update_working_memory", src)  # resumable sessions

    def test_goal_work_registered_as_job(self):
        self.assertIn("goal_work", _read("apps/goals/manifest.yaml"))

    def test_pm_alarm_hands_off_unconditionally(self):
        # Phase 5b: the handler IS the alarm clock; the private conversation
        # gatherer and the legacy in-handler produce loop are deleted.
        src = _read("apps/goals/pm_domain.py")
        self.assertIn('"alarm": "pm"', src)
        self.assertNotIn("_consciousness_pm_enabled", src)
        self.assertNotIn("_gather_conversation_context", src)

    def test_pm_skill_routes_and_speaks_in_one_voice(self):
        src = _read("apps/goals/pm_domain.py")
        self.assertIn("pm_skill_runner", src)
        self.assertIn("schedule_goal_work", src)
        self.assertIn("count_running", src)          # work-slot dedup
        self.assertIn("ALREADY messaged", src)       # one message per person per review

    def test_milestone_voice_and_g_star_deleted(self):
        self.assertIn("_goals_milestone_runner", _read("apps/goals/handlers.py"))
        self.assertIn('register_skill("pm"', _read("apps/goals/handlers.py"))
        self.assertIn('register_skill("goals"', _read("apps/goals/handlers.py"))
        # Phase 5b: the legacy per-goal domain module is DELETED (g-* rows,
        # pattern registration, and the flag went with it); the worker-context
        # builders live on in work_context.py.
        import os as _os
        self.assertFalse(_os.path.exists(_os.path.join(ROOT, "apps/goals/domain.py")))
        self.assertIn("_build_goal_snapshot", _read("apps/goals/work_context.py"))


class Phase4Subconscious(unittest.TestCase):
    """§13 Phase 4: summarizer, embeddings, log retrieval, cl- provenance."""

    def test_summarizer_policy(self):
        src = _read("app_platform/summarizer.py")
        self.assertIn("covers_to_seq", src)
        self.assertIn("PREVIOUS SUMMARY", src)            # cumulative-style (Q5)
        self.assertIn("timedelta(hours=24)", src)         # backstop
        self.assertIn("interval '2 seconds'", src)        # lagged cursor (§11.9)
        self.assertIn("kind != 'event'", src)             # events not embedded
        # span default BELOW the 60-event window → no-gap invariant holds
        self.assertIn("default=50", src)

    def test_rides_the_memory_heartbeat(self):
        self.assertIn("run_subconscious_pass", _read("domain_memory.py"))

    def test_timeline_no_gap_invariant(self):
        src = _read("app_platform/context.py")
        self.assertIn("_covers_to", src)
        self.assertIn("summary of earlier household activity", src)
        self.assertIn('row["seq"] <= after_seq', src)     # covered rows never render twice

    def test_log_retrieval_fan(self):
        self.assertIn("def search_log", _read("app_platform/consciousness.py"))
        src = _read("chat_domain.py")
        self.assertIn("_log_recall", src)
        self.assertIn("Related past conversation", src)
        self.assertIn("bring", src)                       # visibility-rule reminder in the block

    def test_memory_provenance_anchors_on_cl_inbound(self):
        self.assertIn("cl_inbound_id", _read("chat.py"))
        self.assertIn("cl_inbound_id", _read("domain_memory.py"))
        src = _read("chat_digest.py")
        self.assertIn("_anchor = cl_inbound_id or turn_id", src)
        self.assertIn("cl_reply_id", src)                 # reply one hop away


class Phase5aCutover(unittest.TestCase):
    """§13 Phase 5a: projection, voice integration, defaults ON."""

    def test_history_projection(self):
        src = _read("app_platform/context.py")
        self.assertIn("def history_projection", src)
        self.assertIn("chat_turns WHERE id = ANY", src)   # pre-bake hydration fallback
        self.assertIn('_p(reply).get("tool_calls")', src)  # post-bake payload replay
        agent = _read("agent.py")
        self.assertIn("history_projection", agent)
        self.assertNotIn("consciousness_history_enabled", agent)

    def test_voice_utterance_grain_pre_attended(self):
        src = _read("app_platform/voice/chatlog.py")
        self.assertIn('pre_attended_by="voice-session"', src)
        self.assertIn('surface="voice"', src)

    def test_voice_session_start_seeded_from_the_one_mind(self):
        src = _read("app_platform/voice/prompting.py")
        self.assertIn("build_voice_timeline_context", src)
        self.assertIn("RECENT HOUSEHOLD TIMELINE", src)
        # wired into BOTH instruction builders
        self.assertEqual(src.count('f"{timeline_context}"'), 2)

    def test_consciousness_is_the_default(self):
        for f in ("app_platform/context.py", "app_platform/attention.py",
                  "app_platform/summarizer.py", "apps/chores/handlers.py",
                  "apps/goals/handlers.py", "apps/goals/pm_domain.py"):
            self.assertNotIn('scope="platform", default=False', _read(f), f)


class TimeAwareness(unittest.TestCase):
    """Soak finding: the timeline was TIME-BLIND — the model saw order but not
    elapsed time, so the PM asked about outcomes of plans whose stated time
    ("tomorrow morning") had not arrived, re-nudged an 8-minute-old unanswered
    question, and trusted a stale memory over fresher timeline statements."""

    def test_every_timeline_line_is_time_stamped(self):
        src = _read("app_platform/context.py")
        self.assertIn("def event_stamp", src)
        # all render branches carry the stamp
        self.assertGreaterEqual(src.count("{stamp}"), 5)

    def test_boundary_teaches_temporal_reasoning(self):
        src = _read("app_platform/context.py")
        self.assertIn("TIME AWARENESS", src)
        self.assertIn("has NOT happened yet", src)
        self.assertIn("timeline wins", src)
        # the NOW anchor rides with the boundary
        self.assertIn("current date/time NOW", src)

    def test_pm_skill_has_timing_rules_and_now_anchor(self):
        src = _read("apps/goals/pm_domain.py")
        self.assertIn("TIMING", src)
        self.assertIn("never ask how it went", src)
        self.assertIn("it is now", src)                   # alarm trigger carries NOW

    def test_pm_alarms_do_not_stack(self):
        src = _read("apps/goals/pm_domain.py")
        self.assertIn("attended_at IS NULL", src)          # pending alarm blocks a new one
        self.assertIn("interval '15 minutes'", src)        # recent sweep blocks a new one

    def test_summarizer_preserves_dates(self):
        src = _read("app_platform/summarizer.py")
        self.assertIn("event_stamp", src)                  # span lines are stamped
        self.assertIn("concrete dates", src)               # guidance says keep them

    @staticmethod
    def _fake_time_module():
        # app_platform.time transitively imports psycopg2 — stub it (DB-free suite)
        import types
        from zoneinfo import ZoneInfo
        m = types.ModuleType("app_platform.time")
        m.get_timezone = lambda user_id=None: ZoneInfo("America/Chicago")
        return m

    def test_event_stamp_renders_local_time(self):
        import sys
        from datetime import datetime, timezone
        from app_platform import context as C
        row = {"created_at": datetime(2026, 7, 5, 17, 18, tzinfo=timezone.utc)}
        with mock.patch.dict(sys.modules, {"app_platform.time": self._fake_time_module()}):
            s = C.event_stamp(row)
            self.assertEqual(s, "[Sun Jul 5, 12:18 PM] ")
        self.assertEqual(C.event_stamp({"created_at": None}), "")

    def test_render_event_prefixes_the_stamp(self):
        import sys
        from datetime import datetime, timezone
        from app_platform import context as C
        row = {"kind": "message", "who_from": "tyler", "who_to": "skipper",
               "content": "I broke the lamp",
               "created_at": datetime(2026, 7, 5, 17, 18, tzinfo=timezone.utc)}
        with mock.patch.dict(sys.modules, {"app_platform.time": self._fake_time_module()}):
            msg = C.render_event(row, "katie")
        self.assertEqual(msg["role"], "user")
        self.assertTrue(msg["content"].startswith("[Sun Jul 5, 12:18 PM] [tyler → skipper]:"))


class EntityNoteCapture(unittest.TestCase):
    """#107: a reply to an entity-tagged PM message records a history_note on the
    item (durable in every future PM snapshot + digested to an entity-tagged
    memory), instead of leaving it as a loose fact that may not recall later."""

    def test_render_surfaces_subject_marker(self):
        from datetime import datetime, timezone
        from unittest import mock
        import sys, types
        from zoneinfo import ZoneInfo
        m = types.ModuleType("app_platform.time")
        m.get_timezone = lambda user_id=None: ZoneInfo("America/Chicago")
        from app_platform import context as C
        self.assertEqual(C.subject_marker({"subject_id": "p-abc"}), " [re: p-abc]")
        self.assertEqual(C.subject_marker({}), "")
        row = {"kind": "message", "who_from": "skipper", "who_to": "rodney",
               "content": "How's the septic project?", "subject_id": "p-septic",
               "created_at": datetime(2026, 7, 7, 17, 0, tzinfo=timezone.utc)}
        with mock.patch.dict(sys.modules, {"app_platform.time": m}):
            out = C.render_event(row, "rodney")
        self.assertIn("[re: p-septic]", out["content"])

    def test_recent_entity_refs_filters_to_ptg(self):
        # source-level: the query only surfaces p-/t-/g- subject_ids (not bnt-, etc.)
        src = _read("app_platform/context.py")
        self.assertIn("def recent_entity_refs", src)
        self.assertIn("subject_id LIKE 'p-%%'", src)
        self.assertIn("subject_id LIKE 't-%%'", src)
        self.assertIn("subject_id LIKE 'g-%%'", src)

    def test_pm_outbound_can_tag_subject(self):
        src = _read("apps/goals/pm_domain.py")
        self.assertIn('"subject"', src)                 # the tool exposes a subject param
        self.assertIn("subject_id=subj", src)           # dispatch threads it to send_message

    def test_record_entity_note_tool_registered(self):
        src = _read("local_tools.py")
        self.assertIn("record_entity_note", src)
        self.assertIn('"record_entity_note"', src)      # in LOCAL_TOOL_NAMES
        self.assertIn("history_note=note", src)         # handler writes via update_item
        self.assertIn("not a project/task/goal id", src)  # id guard

    def test_chat_exposes_note_tool_conditionally(self):
        src = _read("chat_domain.py")
        self.assertIn("recent_entity_refs", src)
        self.assertIn('routed_tool_names.add("record_entity_note")', src)
        # scoped by the existence of a tagged ref (the flag itself is gone)
        self.assertNotIn("consciousness_chat_enabled", src)
