"""The focus strip updates the moment a pinned item changes — not at the next minute's poll.

iss-15023699: "Deleting a reminder in the Reminders app for a reminder that is also on the
prioritize list does not remove it from the top banner bar on the UI immediately. There is a
minute delay which causes confusion."

The strip re-reads itself every 60s. An instant-refresh path existed, but only the Prioritize app
was given the callback, and chat-driven changes never used it. These pin the wiring at source level
(the web UI has no JS test runner on this platform); the refetch itself runs stale-focus cleanup
server-side, so refreshing is enough to drop a cancelled reminder.

Run: python3 -m unittest tests.platform.test_focus_banner_refreshes_on_change
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class EveryAppCanSignalIt(unittest.TestCase):
    def test_the_callback_is_not_limited_to_prioritize(self):
        panel = _src("web/src/components/AppPanel.jsx")
        self.assertIn("onFocusChanged={onFocusChanged}", panel)
        self.assertNotIn('app.appType === "prioritize" ? onFocusChanged', panel)

    def test_cancelling_a_reminder_signals_it(self):
        rem = _src("apps/reminders/ui/RemindersApp.jsx")
        cancel = rem[rem.index("async function handleCancel"):]
        cancel = cancel[:cancel.index("async function handleReorder")]
        self.assertIn("onFocusChanged?.()", cancel)


class ChatDrivenChangesSignalIt(unittest.TestCase):
    def test_reminders_goals_and_todo_refreshes_also_refresh_the_strip(self):
        app = _src("web/src/App.jsx")
        start = app.index("const handleFocusChanged")
        block = app[start:start + 600]
        for key in ("remindersRefreshKey", "goalsRefreshKey", "todoRefreshKey"):
            with self.subTest(key=key):
                self.assertIn(key, block)
        self.assertIn("handleFocusChanged()", block)


class TheRefetchDropsWhatIsNoLongerActive(unittest.TestCase):
    def test_the_focus_read_runs_stale_cleanup_first(self):
        # Without this, refreshing sooner would only show the stale item sooner.
        agent = _src("agent.py")
        route = agent[agent.index('@app.get("/api/apps/prioritize/focus")'):]
        route = route[:route.index("@app.", 10)]
        self.assertIn("cleanup_stale_focus", route)
        self.assertLess(route.index("cleanup_stale_focus"), route.index("get_focus_slots"))


if __name__ == "__main__":
    unittest.main()
