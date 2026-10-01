"""An automated greeting is said, but not remembered (notifications.delivery.greeting-is-not-remembered).

Every arrival greeting went out as a notification, and every notification left a memory that it
was sent — 13,421 greeting memories on the operator's install ("Welcome back, Rodney…" over and
over). The operator: Skipper should not store memories that it did its automated greeting.

create_notification(remember=False) sends and records the notification but writes no memory;
send_message carries the flag through; the connection skill's greeting is the caller that uses it.

Run: python3 -m unittest apps.notifications.tests.test_greeting_is_not_remembered
"""
import ast
import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class CreateNotificationRemember(unittest.TestCase):
    def _create(self, **kw):
        remembered, pruned, saved = [], [], []
        data = types.SimpleNamespace(
            save_notification=lambda n: saved.append(n),
            prune_notification_memories=lambda *a, **k: pruned.append(a) or 0)
        app_platform = types.ModuleType("app_platform")
        stubs = {
            "config": types.SimpleNamespace(logger=mock.Mock()),
            "app_platform": app_platform,
            "app_platform.time": types.SimpleNamespace(get_timezone=lambda: None),
            "app_platform.consciousness": types.SimpleNamespace(
                shadow_log_event=lambda **k: None, domain_for_source_type=lambda s: s),
            "auto_memory": types.SimpleNamespace(
                log_entity_change=lambda *a, **k: remembered.append(a)),
            "apps.notifications.data": data,
            "data_layer": types.ModuleType("data_layer"),
            "data_layer.users": types.SimpleNamespace(get_user=lambda u: {"id": u}),
        }
        import apps.notifications as pkg
        with mock.patch.dict(sys.modules, stubs), mock.patch.object(pkg, "data", data, create=True):
            sys.modules.pop("apps.notifications.store", None)
            import apps.notifications.store as store
            notif = store.create_notification("rodney", "Welcome back, Rodney.",
                                              source_type="consciousness", source_id="cl-1", **kw)
            sys.modules.pop("apps.notifications.store", None)
        return notif, saved, remembered, pruned

    def test_a_greeting_is_sent_but_leaves_no_memory(self):
        notif, saved, remembered, pruned = self._create(remember=False)
        self.assertEqual(len(saved), 1)                 # the notification itself still exists
        self.assertTrue(notif["id"].startswith("n-"))
        self.assertEqual(remembered, [])
        self.assertEqual(pruned, [])

    def test_everything_else_is_still_remembered(self):
        _, saved, remembered, _ = self._create()
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(remembered), 1)


class TheGreetingUsesIt(unittest.TestCase):
    def test_send_message_carries_the_flag_to_create_notification(self):
        src = open(os.path.join(ROOT, "app_platform/consciousness.py"), encoding="utf-8").read()
        fn = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.FunctionDef) and n.name == "send_message")
        self.assertIn("remember", [a.arg for a in fn.args.kwonlyargs])
        call = next(c for c in ast.walk(fn) if isinstance(c, ast.Call)
                    and getattr(c.func, "id", "") == "create_notification")
        self.assertIn("remember", [k.arg for k in call.keywords])

    def test_the_arrival_greeting_is_spoken_with_remember_false(self):
        src = open(os.path.join(ROOT, "apps/goals/handlers.py"), encoding="utf-8").read()
        fn = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "_greeting_turn")
        speak = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                 and getattr(c.func, "id", "") == "speak"]
        self.assertEqual(len(speak), 1)
        kw = {k.arg: k.value for k in speak[0].keywords}
        self.assertIs(kw["remember"].value, False)


if __name__ == "__main__":
    unittest.main()
