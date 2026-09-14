"""Sending a notification from off the box, and never being told it worked when it did not.

Every other way to raise a notification is an in-process call to
``app_platform.notifications.create_notification``, so only code running ON the box
could tell anybody anything. This router could list history and configure Pushover;
it could not send. A caretaker watching from another machine had no way in.

The route that closes that gap is an escalation path — the thing you reach for when
the person who normally handles it cannot be reached — so the property that matters
is not that it sends. It is that it is never silent about not sending. Two habits of
the surrounding code would otherwise swallow a failure whole:

  * ``create_notification`` returns ``{}`` for a name that belongs to nobody and logs
    it at debug. Called blind, an alert addressed to a typo looks exactly like one
    that was delivered.
  * ``_deliver_one`` marks the row delivered once it has TRIED, whatever came back.
    The row records the attempt; it is not evidence that a person was reached.

Two design decisions deserved tests of their own.

The Discord mirroring policy is allowed to narrow a notification to nothing, on the
stated grounds that the web console always has the record. That holds while somebody
is watching the web console — the one thing this route cannot assume.

And it sends to everyone it CAN reach rather than refusing over one bad name. The
failure that bites an escalation path is not a typo in a hardcoded list, which fails
loudly on its first smoke test; it is drift — a discord_id quietly unset months
later, on a route nothing exercises until the emergency. One stale link must not
silence the alert to the other two people. What must never happen is that the
incompleteness goes unnoticed, so the partial send is pinned from both sides: the
good recipients are delivered to, AND the response cannot read as success.

Run: python3 -m unittest apps.notifications.tests.test_direct_send_route
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from unittest import mock


ROSTER = {
    "jacob":  {"name": "jacob",  "discord_id": "111", "role": "member"},
    "elijah": {"name": "elijah", "discord_id": "222", "role": "member"},
    "caleb":  {"name": "caleb",  "discord_id": "333", "role": "member"},
    "nodiscord": {"name": "nodiscord", "discord_id": "", "role": "member"},
}

DELIVERED = {"discord": {"ok": True, "detail": "DM sent to x successfully."},
             "web": {"ok": False, "detail": "not connected — waiting in history"}}
REFUSED = {"discord": {"ok": False, "detail": "Error: Cannot send DM — DMs disabled."},
           "web": {"ok": False, "detail": "not connected — waiting in history"}}


def _patch_targets():
    """Import the modules the patches name, so mock.patch can resolve them.

    They are imported INSIDE the handler at call time, and a dotted patch target has
    to be importable before it can be replaced.
    """
    import data_layer.users            # noqa: F401
    import app_platform.auth           # noqa: F401
    import apps.notifications.store    # noqa: F401
    import apps.notifications.delivery # noqa: F401


def _notif(recipient, message, source_type="", source_id="", channel="", delivered=False):
    return {"id": f"n-{recipient[:6]}", "recipient": recipient, "message": message,
            "source_type": source_type, "source_id": source_id, "channel": channel,
            "delivered": delivered}


class SendRoute(unittest.TestCase):
    """Real HTTP through the actual router, with the roster and the wire stubbed."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on the host
            raise unittest.SkipTest(f"fastapi TestClient unavailable: {exc}")

    def _post(self, body, *, receipts=DELIVERED, admin=True, roster=None,
              created=_notif):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from apps.notifications import routes as notif_routes

        _patch_targets()
        app = FastAPI()
        app.include_router(notif_routes.router, prefix="/api/apps/notifications")

        people = ROSTER if roster is None else roster
        self.delivered_calls = []

        async def _fake_deliver(notif, *, honor_surface_policy=True):
            self.delivered_calls.append((notif["id"], honor_surface_policy))
            return receipts

        def _fake_admin(request):
            if not admin:
                raise HTTPException(403, "Admin access required")
            return {"name": "service:caretaker", "role": "admin", "is_service": True}

        with mock.patch("app_platform.auth.require_admin", _fake_admin), \
             mock.patch("data_layer.users.get_user", lambda n: people.get(n)), \
             mock.patch("apps.notifications.store.create_notification",
                        mock.Mock(side_effect=created)) as created_mock, \
             mock.patch("apps.notifications.delivery._deliver_one", _fake_deliver):
            self.created = created_mock
            client = TestClient(app, raise_server_exceptions=False)
            return client.post("/api/apps/notifications", json=body)

    # -- the happy path, stated so the failures below mean something ---------

    def test_it_records_and_delivers_to_every_recipient(self):
        res = self._post({"recipients": ["jacob", "elijah", "caleb"],
                          "message": "Trading system halted."})
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["ok"])
        self.assertEqual([r["recipient"] for r in payload["results"]],
                         ["jacob", "elijah", "caleb"])
        for r in payload["results"]:
            self.assertTrue(r["delivered"])
            self.assertIsNone(r["error"])
            self.assertTrue(r["notification_id"])
            self.assertEqual(r["channels_reached"], ["discord"])

    def test_a_single_recipient_may_be_named_in_the_singular(self):
        res = self._post({"recipient": "jacob", "message": "hi"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["recipient"] for r in res.json()["results"]], ["jacob"])

    def test_the_two_spellings_combine_without_sending_twice(self):
        res = self._post({"recipients": ["jacob", "elijah"], "recipient": "jacob",
                          "message": "hi"})
        self.assertEqual([r["recipient"] for r in res.json()["results"]],
                         ["jacob", "elijah"])

    def test_names_are_matched_the_way_they_are_stored(self):
        res = self._post({"recipients": ["  JACOB  "], "message": "hi"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["results"][0]["recipient"], "jacob")

    # -- refusing, by name, before anything is written -----------------------

    def test_an_unknown_recipient_is_named_in_their_own_result(self):
        res = self._post({"recipients": ["jacob", "jakob"], "message": "hi"})
        by_name = {r["recipient"]: r for r in res.json()["results"]}
        self.assertEqual(sorted(by_name), ["jacob", "jakob"])
        self.assertIn("not a known user", by_name["jakob"]["error"])
        self.assertFalse(by_name["jakob"]["delivered"])

    def test_a_recipient_with_no_discord_id_is_named_and_not_recorded(self):
        # send_dm answers "Error: No Discord ID found for 'x'" — which _deliver_one
        # would record as a failed receipt on a row ALREADY marked delivered. Caught
        # before the write, so no row claims they were told anything.
        res = self._post({"recipients": ["nodiscord"], "message": "hi"})
        r = res.json()["results"][0]
        self.assertIn("discord_id", r["error"])
        self.assertIsNone(r["notification_id"])
        self.assertEqual(self.created.call_count, 0)

    def test_one_bad_name_does_not_silence_the_others(self):
        # THE DECISION THIS ENDPOINT TURNS ON. A discord_id going stale months from
        # now, on a path nothing exercises until the emergency, must not stop the
        # alert reaching the people it still can — one of whom may be the only person
        # able to act on it.
        res = self._post({"recipients": ["jacob", "elijah", "nobody"], "message": "hi"})
        by_name = {r["recipient"]: r for r in res.json()["results"]}
        self.assertTrue(by_name["jacob"]["delivered"])
        self.assertTrue(by_name["elijah"]["delivered"])
        self.assertFalse(by_name["nobody"]["delivered"])
        self.assertEqual(sorted(i for i, _ in self.delivered_calls),
                         ["n-elijah", "n-jacob"])

    def test_a_partial_send_can_never_read_as_success(self):
        # The other half, and the one that matters more. 207 is "successful" to most
        # HTTP clients (requests' resp.ok is True for it), so the body has to be the
        # authoritative field — and the status still must not be 200.
        res = self._post({"recipients": ["jacob", "nobody"], "message": "hi"})
        self.assertEqual(res.status_code, 207)
        self.assertNotEqual(res.status_code, 200)
        body = res.json()
        self.assertFalse(body["ok"])
        self.assertEqual((body["requested"], body["succeeded"], body["failed"]),
                         (2, 1, 1))

    def test_reaching_nobody_at_all_is_distinguishable_from_a_partial_send(self):
        # A monitor loop may want to escalate differently for a total outage than for
        # "two of three got it".
        res = self._post({"recipients": ["nobody", "noone"], "message": "hi"})
        self.assertEqual(res.status_code, 502)
        self.assertFalse(res.json()["ok"])
        self.assertEqual(res.json()["succeeded"], 0)

    def test_a_200_still_means_every_requested_recipient_was_reached(self):
        # The guarantee the caller is allowed to lean on.
        res = self._post({"recipients": ["jacob", "elijah", "caleb"], "message": "hi"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["succeeded"], body["requested"])
        self.assertEqual(body["failed"], 0)
        self.assertTrue(all(r["delivered"] for r in body["results"]))

    def test_discord_id_is_only_required_when_discord_is_a_target(self):
        # The check has to follow the channel actually asked for, or a Pushover-only
        # alert is refused over a credential it was never going to use.
        res = self._post({"recipients": ["nodiscord"], "message": "hi",
                          "channel": "pushover"},
                         receipts={"pushover": {"ok": True, "detail": "sent"}})
        self.assertEqual(res.status_code, 200)

    def test_an_empty_message_is_refused(self):
        self.assertEqual(self._post({"recipients": ["jacob"], "message": "   "}).status_code, 400)

    def test_no_recipients_at_all_is_refused(self):
        self.assertEqual(self._post({"message": "hi"}).status_code, 400)

    def test_absurd_volume_is_refused(self):
        res = self._post({"recipients": [f"p{i}" for i in range(50)], "message": "hi"})
        self.assertEqual(res.status_code, 400)

    # -- the status code has to agree with the body --------------------------

    def test_a_refused_dm_is_not_a_200(self):
        # The whole reason this endpoint exists in this shape. _deliver_one marks the
        # row delivered whatever Discord said, so the row cannot be the evidence.
        res = self._post({"recipients": ["jacob"], "message": "hi"}, receipts=REFUSED)
        self.assertEqual(res.status_code, 502)
        body = res.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["results"][0]["delivered"])
        self.assertIn("DMs disabled", body["results"][0]["error"])

    def test_one_failure_among_several_fails_the_whole_response(self):
        calls = {"n": 0}

        async def _mixed(notif, *, honor_surface_policy=True):
            calls["n"] += 1
            return DELIVERED if calls["n"] == 1 else REFUSED

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.notifications import routes as notif_routes
        _patch_targets()
        app = FastAPI()
        app.include_router(notif_routes.router, prefix="/api/apps/notifications")
        with mock.patch("app_platform.auth.require_admin", lambda r: {"role": "admin"}), \
             mock.patch("data_layer.users.get_user", lambda n: ROSTER.get(n)), \
             mock.patch("apps.notifications.store.create_notification", _notif), \
             mock.patch("apps.notifications.delivery._deliver_one", _mixed):
            res = TestClient(app, raise_server_exceptions=False).post(
                "/api/apps/notifications",
                json={"recipients": ["jacob", "elijah"], "message": "hi"})
        self.assertEqual(res.status_code, 207, "one of two reached is partial, not total")
        self.assertFalse(res.json()["ok"])
        self.assertEqual([r["delivered"] for r in res.json()["results"]], [True, False])

    def test_reaching_only_the_web_console_is_not_delivery(self):
        # web is written to unconditionally, so counting it would make every send
        # look successful — including one where Discord was never attempted.
        res = self._post({"recipients": ["jacob"], "message": "hi"},
                         receipts={"web": {"ok": True, "detail": "pushed live"}})
        self.assertEqual(res.status_code, 502)
        self.assertFalse(res.json()["results"][0]["delivered"])

    def test_a_delivery_that_raises_is_reported_not_propagated(self):
        async def _boom(notif, *, honor_surface_policy=True):
            raise RuntimeError("discord gateway down")

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.notifications import routes as notif_routes
        _patch_targets()
        app = FastAPI()
        app.include_router(notif_routes.router, prefix="/api/apps/notifications")
        with mock.patch("app_platform.auth.require_admin", lambda r: {"role": "admin"}), \
             mock.patch("data_layer.users.get_user", lambda n: ROSTER.get(n)), \
             mock.patch("apps.notifications.store.create_notification", _notif), \
             mock.patch("apps.notifications.delivery._deliver_one", _boom):
            res = TestClient(app, raise_server_exceptions=False).post(
                "/api/apps/notifications",
                json={"recipients": ["jacob"], "message": "hi"})
        self.assertEqual(res.status_code, 502)
        self.assertIn("discord gateway down", res.json()["results"][0]["error"])

    def test_a_record_that_silently_fails_to_save_is_reported(self):
        # create_notification answers {} rather than raising. Returned as-is that is
        # an empty result the caller has to notice; named, it is a failure.
        res = self._post({"recipients": ["jacob"], "message": "hi"},
                         created=lambda *a, **k: {})
        self.assertEqual(res.status_code, 502)
        self.assertIsNone(res.json()["results"][0]["notification_id"])
        self.assertIn("could not be created", res.json()["results"][0]["error"])

    # -- recording without sending -------------------------------------------

    def test_deliver_false_records_and_says_so(self):
        res = self._post({"recipients": ["jacob"], "message": "hi", "deliver": False})
        self.assertEqual(res.status_code, 200)
        r = res.json()["results"][0]
        self.assertTrue(r["notification_id"])
        self.assertFalse(r["delivered"])
        self.assertIn("deliver=false", r["note"])
        self.assertEqual(self.delivered_calls, [], "nothing should have been sent")

    # -- who may do this ------------------------------------------------------

    def test_sending_as_skipper_requires_an_admin(self):
        # A member's own credential must not be able to address the household as
        # Skipper. Off-box callers use a service token minted with --role admin.
        res = self._post({"recipients": ["jacob"], "message": "hi"}, admin=False)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.created.call_count, 0)

    # -- the mirroring policy is not applied to this path ---------------------

    def test_the_conversation_mirroring_policy_is_switched_off_for_this_route(self):
        self._post({"recipients": ["jacob"], "message": "hi"})
        self.assertEqual([flag for _, flag in self.delivered_calls], [False])


class TheListRouteIsUnchanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on the host
            raise unittest.SkipTest(f"fastapi TestClient unavailable: {exc}")

    def test_get_still_lists_and_is_not_shadowed_by_the_new_post(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.notifications import routes as notif_routes

        _patch_targets()
        app = FastAPI()
        app.include_router(notif_routes.router, prefix="/api/apps/notifications")
        with mock.patch.object(notif_routes, "scope_user", lambda r, u: "jacob"), \
             mock.patch("apps.notifications.data.get_notifications_for_user",
                        lambda r, l: [{"id": "n-1"}]):
            res = TestClient(app, raise_server_exceptions=False).get(
                "/api/apps/notifications?recipient=jacob")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"notifications": [{"id": "n-1"}]})


class DeliveryReportsWhatItReached(unittest.TestCase):
    """_deliver_one, exercised directly with the outside world stubbed out."""

    def _run(self, *, honor_policy, plan_says_no=True, discord_result="DM sent to jacob successfully."):
        stubs = {}
        discord_bot = mock.MagicMock()

        async def _send_dm(recipient, message):
            return discord_result
        discord_bot.send_dm = _send_dm
        discord_bot.strip_entity_ids = lambda m: m
        stubs["discord_bot"] = discord_bot

        connections = mock.MagicMock()

        async def _send_to_user(recipient, frame):
            return False
        connections.manager.send_to_user = _send_to_user
        connections.manager.list_connected_users = lambda: []
        stubs["connections"] = connections

        speak = mock.MagicMock()
        speak._primary_surface = lambda u: "web"
        speak._discord_active = lambda u: False
        speak._discord_reachable = lambda u: True
        stubs["app_platform.speak"] = speak

        policy = mock.MagicMock()
        self.plan_calls = []

        def _plan(**kw):
            self.plan_calls.append(kw)
            return not plan_says_no
        policy.plan_discord = _plan
        policy.DISCORD_ACTIVE_SECONDS = 900
        stubs["app_platform.voice_policy"] = policy

        pushover = mock.MagicMock()
        pushover.is_pushover_user = lambda u: False
        stubs["tools.pushover_tool"] = pushover

        fcm = mock.MagicMock()
        fcm.is_enabled = lambda: False
        stubs["fcm_sender"] = fcm

        from apps.notifications import delivery
        notif = _notif("jacob", "Trading system halted.", "system", "", "discord")
        with mock.patch.dict(sys.modules, stubs), \
             mock.patch.object(delivery._dl_notif, "mark_delivered", lambda i: True), \
             mock.patch.object(delivery._dl_notif, "set_receipts", lambda i, r: True):
            return asyncio.run(
                delivery._deliver_one(notif, honor_surface_policy=honor_policy))

    def test_it_returns_the_receipts_rather_than_nothing(self):
        # The scheduler ignores the return; a caller that has to TELL somebody whether
        # the message landed needs it, and reading the row back is a round trip for
        # something already in hand.
        receipts = self._run(honor_policy=False)
        self.assertTrue(receipts["discord"]["ok"])
        self.assertIn("DM sent", receipts["discord"]["detail"])

    def test_a_refused_dm_comes_back_as_a_failed_receipt(self):
        receipts = self._run(honor_policy=False,
                             discord_result="Error: Cannot send DM to jacob.")
        self.assertFalse(receipts["discord"]["ok"])

    def test_the_policy_can_still_drop_discord_on_the_ordinary_path(self):
        # Unchanged behaviour for every existing producer: this is what the flag is
        # turning OFF, so it has to be shown to be ON by default.
        receipts = self._run(honor_policy=True, plan_says_no=True)
        self.assertNotIn("discord", receipts)
        self.assertTrue(self.plan_calls, "the policy should have been consulted")

    def test_an_explicit_send_is_not_dropped_by_it(self):
        # A web-primary recipient who has not used Discord recently — the exact
        # condition that narrows discord away — still gets the DM on this path.
        receipts = self._run(honor_policy=False, plan_says_no=True)
        self.assertTrue(receipts["discord"]["ok"])
        self.assertEqual(self.plan_calls, [], "the policy must not even be consulted")


if __name__ == "__main__":
    unittest.main()
