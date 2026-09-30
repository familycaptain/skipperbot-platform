"""Bound tests for the platform.agents feature (shared chat thread with external agent participants).

Covers: registry + address parsing, addressee resolution rules, lane derivation for agent rows,
delegated inbound rows, agent speech validation, timeline rendering, history projection bubbles,
and the goals agent-owner gate. Deterministic + DB-free: DB calls are stubbed.

Run with ``python3 -m unittest tests.platform.test_agent_participants``.
"""

import unittest
from datetime import datetime, timezone
from unittest import mock

from app_platform import agents, consciousness, context


def _register_prof():
    agents.register_agent(name="professor", display_name="Professor", icon="🎓",
                          aliases=["prof"], description="subagent", ensure_user=False)


class _AgentsTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = dict(agents._registry)
        agents._registry.clear()

    def tearDown(self):
        agents._registry.clear()
        agents._registry.update(self._saved)


class Registry(_AgentsTestCase):
    def test_register_and_lookup(self):
        _register_prof()
        self.assertTrue(agents.is_agent("Professor"))
        self.assertFalse(agents.is_agent("skipper"))
        self.assertEqual(agents.speaker_label("professor"), "🎓 Professor")
        self.assertEqual(agents.list_agents()[0]["aliases"], ["prof"])

    def test_invalid_names_rejected(self):
        for bad in ("", "skipper", "x", "has space", "1abc"):
            with self.assertRaises(ValueError):
                agents.register_agent(name=bad, display_name="X", ensure_user=False)

    def test_address_prefix(self):
        _register_prof()
        self.assertEqual(agents._address_prefix("@prof what's the status?"), "professor")
        self.assertEqual(agents._address_prefix("Professor, go ahead"), "professor")
        self.assertEqual(agents._address_prefix("prof: yes"), "professor")
        self.assertEqual(agents._address_prefix("@skipper what's for dinner"), "skipper")
        self.assertIsNone(agents._address_prefix("yes, go ahead"))
        self.assertIsNone(agents._address_prefix("the professor said hi"))


class Resolve(_AgentsTestCase):
    def _fetch(self, reply_author=None, last=None):
        def fetch_one(sql, args):
            if "WHERE id = %s" in sql:
                return {"who_from": reply_author} if reply_author else None
            return last
        return fetch_one

    def test_no_agents_is_always_skipper(self):
        self.assertEqual(agents.resolve_addressee("rodney", "@prof hi", _fetch_one=self._fetch()),
                         ("skipper", "default"))

    def test_explicit_reply_wins(self):
        _register_prof()
        last = {"who_from": "professor", "payload": {"expects_reply": True}, "fresh": True}
        self.assertEqual(agents.resolve_addressee("rodney", "@prof x", "cl-1",
                                                  _fetch_one=self._fetch("skipper", last)),
                         ("skipper", "reply"))
        self.assertEqual(agents.resolve_addressee("rodney", "sure", "cl-2",
                                                  _fetch_one=self._fetch("professor")),
                         ("professor", "reply"))

    def test_address_beats_open_question(self):
        _register_prof()
        last = {"who_from": "professor", "payload": {"expects_reply": True}, "fresh": True}
        self.assertEqual(agents.resolve_addressee("rodney", "@skipper dinner?",
                                                  _fetch_one=self._fetch(last=last)),
                         ("skipper", "address"))

    def test_open_question_sticky(self):
        _register_prof()
        fresh = {"who_from": "professor", "payload": '{"expects_reply": true}', "fresh": True}
        stale = {"who_from": "professor", "payload": {"expects_reply": True}, "fresh": False}
        no_q = {"who_from": "professor", "payload": {}, "fresh": True}
        skipper_last = {"who_from": "skipper", "payload": {}, "fresh": True}
        f = lambda last: agents.resolve_addressee("rodney", "yes do it", _fetch_one=self._fetch(last=last))
        self.assertEqual(f(fresh), ("professor", "open_question"))
        self.assertEqual(f(stale), ("skipper", "default"))
        self.assertEqual(f(no_q), ("skipper", "default"))
        self.assertEqual(f(skipper_last), ("skipper", "default"))


class Lanes(_AgentsTestCase):
    def test_agent_rows_live_in_the_person_lane(self):
        _register_prof()
        self.assertEqual(consciousness.lane_for("message", "professor", "rodney", "professor"), "person:rodney")
        self.assertEqual(consciousness.lane_for("message", "rodney", "professor", "chat"), "person:rodney")
        self.assertEqual(consciousness.lane_for("message", "skipper", "rodney", "chat"), "person:rodney")

    def test_unregistered_name_is_still_a_person(self):
        self.assertEqual(consciousness.lane_for("message", "professor", "rodney", "x"), "person:professor")


class Writes(_AgentsTestCase):
    def test_inbound_to_agent_is_delegated(self):
        _register_prof()
        captured = {}
        with mock.patch.object(consciousness, "fetch_one", return_value=None), \
             mock.patch.object(consciousness, "log_event", side_effect=lambda **kw: captured.update(kw) or kw):
            consciousness.log_inbound_message(who_from="rodney", content="yes", who_to="professor")
        self.assertEqual(captured["who_to"], "professor")
        self.assertEqual(captured["pre_attended_by"], "agent:professor")
        self.assertFalse(captured["needs_attention"])

    def test_inbound_to_skipper_unchanged(self):
        captured = {}
        with mock.patch.object(consciousness, "fetch_one", return_value=None), \
             mock.patch.object(consciousness, "log_event", side_effect=lambda **kw: captured.update(kw) or kw):
            consciousness.log_inbound_message(who_from="rodney", content="hi", who_to="professor")
        self.assertEqual(captured["who_to"], "skipper")  # unregistered → Skipper
        self.assertTrue(captured["needs_attention"])
        self.assertIsNone(captured["pre_attended_by"])

    def test_only_registered_agents_may_speak(self):
        with self.assertRaises(ValueError):
            consciousness.send_message(who_to="rodney", content="hi", domain="x", who_from="mallory")

    def test_agent_speech_tags_payload(self):
        _register_prof()
        captured = {}
        row = {"id": "cl-1", "seq": 1, "lane": "person:rodney"}
        with mock.patch.object(consciousness, "log_event", side_effect=lambda **kw: captured.update(kw) or row), \
             mock.patch("app_platform.notifications.create_notification"):
            consciousness.send_message(who_to="rodney", content="Q?", domain="professor",
                                       who_from="professor", payload={"expects_reply": True})
        self.assertEqual(captured["who_from"], "professor")
        self.assertEqual(captured["payload"], {"expects_reply": True, "agent": "professor"})


class Rendering(_AgentsTestCase):
    def _row(self, **kw):
        base = {"kind": "message", "content": "text", "created_at": None, "payload": None}
        base.update(kw)
        return base

    def test_agent_speech_is_not_skippers_voice(self):
        _register_prof()
        m = context.render_event(self._row(who_from="professor", who_to="rodney"), "rodney")
        self.assertEqual(m["role"], "user")
        self.assertIn("[professor → rodney]: text", m["content"])

    def test_message_to_agent_is_tagged(self):
        m = context.render_event(self._row(who_from="rodney", who_to="professor",
                                           payload={"attended_by": "agent:professor"}), "rodney")
        self.assertIn("[rodney → professor]: text", m["content"])  # works even if unregistered later

    def test_skipper_and_person_unchanged(self):
        self.assertEqual(context.render_event(self._row(who_from="skipper", who_to="rodney"), "rodney"),
                         {"role": "assistant", "content": "text"})
        self.assertEqual(context.render_event(self._row(who_from="rodney", who_to="skipper"), "rodney"),
                         {"role": "user", "content": "text"})

    def test_boundary_names_agents(self):
        _register_prof()
        self.assertIn("professor (Professor — subagent)", context._agents_line())
        agents._registry.clear()
        self.assertEqual(context._agents_line(), "")


class History(_AgentsTestCase):
    def test_agent_bubbles_and_routed_chip(self):
        _register_prof()
        t = lambda s: datetime(2026, 9, 29, 12, 0, s, tzinfo=timezone.utc)
        rows = [
            {"id": "cl-a", "kind": "message", "who_from": "professor", "who_to": "rodney",
             "content": "Budget?", "created_at": t(1), "payload": {"agent": "professor"}, "reply_to": None},
            {"id": "cl-b", "kind": "message", "who_from": "rodney", "who_to": "professor",
             "content": "12k", "created_at": t(2), "payload": {"attended_by": "agent:professor"},
             "reply_to": "cl-a"},
        ]
        with mock.patch("data_layer.db.fetch_all", return_value=rows):
            turns = context.history_projection("rodney")
        self.assertEqual(turns[0]["speaker"], "professor")
        self.assertEqual(turns[0]["assistant_message"], "Budget?")
        self.assertEqual(turns[1]["routed_to"], "professor")
        self.assertEqual(turns[1]["assistant_message"], "")

        from chat_render import _turn_messages
        self.assertEqual(_turn_messages(turns[0])[0]["speaker"], "professor")
        self.assertEqual(_turn_messages(turns[1])[0]["routed_to"], "professor")


class GoalsGate(_AgentsTestCase):
    def test_agent_owner(self):
        _register_prof()
        from apps.goals.work_context import agent_owner
        self.assertEqual(agent_owner(["professor"]), "professor")
        self.assertEqual(agent_owner(["Professor"]), "professor")
        self.assertEqual(agent_owner(["professor", "rodney"]), "")
        self.assertEqual(agent_owner([]), "")
        self.assertEqual(agent_owner(["rodney"]), "")


if __name__ == "__main__":
    unittest.main()
