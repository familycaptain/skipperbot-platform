"""Tests for app_platform/lifecycle.py — the lifecycle hook registry that lets
apps register background workers + shutdown hooks WITHOUT the platform importing
apps.* (BUG #11 / specs/platform/loader/lifecycle-hooks).

Offline + deterministic: no real workers run; coroutines used here either return
immediately or raise on first step. No network.
"""
import asyncio
import sys
import types
import unittest

from app_platform import lifecycle


class TestLifecycleRegistry(unittest.TestCase):
    def setUp(self):
        lifecycle.reset()

    def tearDown(self):
        lifecycle.reset()

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------
    def test_start_creates_one_task_per_registration_and_is_idempotent(self):
        async def worker():
            # never actually loops here; sleep a tick then return cleanly
            await asyncio.sleep(0)

        lifecycle.register_background_task("w1", worker)
        lifecycle.register_background_task("w2", worker)

        async def run():
            tasks = lifecycle.start_background_tasks()
            self.assertEqual(set(tasks.keys()), {"w1", "w2"})
            self.assertEqual(len(tasks), 2)
            for t in tasks.values():
                self.assertIsInstance(t, asyncio.Task)

            # Second call must be a no-op: same tasks, no duplicates.
            tasks2 = lifecycle.start_background_tasks()
            self.assertEqual(set(tasks2.keys()), {"w1", "w2"})
            self.assertIs(tasks2["w1"], tasks["w1"])
            self.assertIs(tasks2["w2"], tasks["w2"])

            # let them finish so the loop has no pending warnings
            await asyncio.gather(*tasks.values())

        asyncio.run(run())

    def test_register_rejects_a_coroutine_object(self):
        async def worker():
            await asyncio.sleep(0)

        coro = worker()  # this is the footgun: an awaitable, not a factory
        try:
            with self.assertRaises(TypeError):
                lifecycle.register_background_task("bad", coro)
        finally:
            coro.close()
        self.assertEqual(lifecycle.get_registered_task_ids(), [])

    def test_dying_worker_is_caught_by_done_callback_others_unaffected(self):
        logs = []

        async def dies():
            raise RuntimeError("boom on first step")

        async def healthy():
            await asyncio.sleep(0)
            return "ok"

        lifecycle.register_background_task("dies", dies)
        lifecycle.register_background_task("healthy", healthy)

        async def run():
            with self.assertLogs("platform.lifecycle", level="ERROR") as cm:
                tasks = lifecycle.start_background_tasks()
                # Let the event loop run both tasks to completion.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                logs.extend(cm.output)
            return tasks, results

        tasks, results = asyncio.run(run())
        # The done-callback logged the dying worker.
        self.assertTrue(any("died" in m and "dies" in m for m in logs), logs)
        # The healthy task completed fine (other tasks unaffected).
        self.assertEqual(tasks["healthy"].result(), "ok")

    # ------------------------------------------------------------------
    # Shutdown hooks
    # ------------------------------------------------------------------
    def test_run_shutdown_hooks_invokes_sync_and_async(self):
        calls = []

        def sync_hook():
            calls.append("sync")

        async def async_hook():
            calls.append("async")

        lifecycle.register_shutdown_hook(sync_hook)
        lifecycle.register_shutdown_hook(async_hook)

        asyncio.run(lifecycle.run_shutdown_hooks())
        self.assertEqual(set(calls), {"sync", "async"})

    def test_raising_hook_is_isolated(self):
        calls = []

        def bad():
            raise ValueError("nope")

        def good():
            calls.append("good")

        lifecycle.register_shutdown_hook(bad)
        lifecycle.register_shutdown_hook(good)

        with self.assertLogs("platform.lifecycle", level="ERROR"):
            asyncio.run(lifecycle.run_shutdown_hooks())
        # The good hook still ran despite the bad one raising.
        self.assertEqual(calls, ["good"])

    def test_reset_clears_state(self):
        async def worker():
            await asyncio.sleep(0)

        lifecycle.register_background_task("w", worker)
        lifecycle.register_shutdown_hook(lambda: None)
        self.assertTrue(lifecycle.get_registered_task_ids())
        self.assertTrue(lifecycle.get_shutdown_hooks())
        lifecycle.reset()
        self.assertEqual(lifecycle.get_registered_task_ids(), [])
        self.assertEqual(lifecycle.get_shutdown_hooks(), [])


def _stub_module(name: str, **attrs):
    """Install a stub module in sys.modules so an app's hooks.py can import it
    without pulling in heavy deps (psycopg2 etc.)."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class TestAppHookRegistration(unittest.TestCase):
    """Each app's hooks.py register_hooks() registers exactly the right
    lifecycle entries (workers referenced, not run)."""

    def setUp(self):
        lifecycle.reset()
        self._saved = {}

    def tearDown(self):
        lifecycle.reset()
        # Restore/remove any stubbed modules.
        for name, prev in self._saved.items():
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev

    def _stub(self, name, **attrs):
        self._saved.setdefault(name, sys.modules.get(name))
        return _stub_module(name, **attrs)

    def _import_hooks(self, module_path, file_rel):
        import importlib.util
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        path = repo / file_rel
        spec = importlib.util.spec_from_file_location(module_path, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_reminders_hooks_register_worker_and_shutdown(self):
        async def start_reminder_scheduler():
            await asyncio.sleep(0)

        def request_shutdown():
            pass

        self._stub("apps.reminders.scheduler",
                   start_reminder_scheduler=start_reminder_scheduler,
                   request_shutdown=request_shutdown)

        hooks = self._import_hooks("apps.reminders.hooks", "apps/reminders/hooks.py")
        hooks.register_hooks()

        self.assertIn("reminders_scheduler", lifecycle.get_registered_task_ids())
        self.assertIn(request_shutdown, lifecycle.get_shutdown_hooks())

    def test_jobs_hooks_register_worker_no_shutdown(self):
        async def start_job_runner():
            await asyncio.sleep(0)

        self._stub("apps.jobs.runner", start_job_runner=start_job_runner)

        hooks = self._import_hooks("apps.jobs.hooks", "apps/jobs/hooks.py")
        hooks.register_hooks()

        self.assertIn("jobs_runner", lifecycle.get_registered_task_ids())
        self.assertEqual(lifecycle.get_shutdown_hooks(), [])

    def test_timers_hooks_register_shutdown_no_worker(self):
        async def shutdown_all_timers():
            await asyncio.sleep(0)

        self._stub("apps.timers.scheduler", shutdown_all_timers=shutdown_all_timers)

        hooks = self._import_hooks("apps.timers.hooks", "apps/timers/hooks.py")
        hooks.register_hooks()

        self.assertEqual(lifecycle.get_registered_task_ids(), [])
        self.assertIn(shutdown_all_timers, lifecycle.get_shutdown_hooks())


if __name__ == "__main__":
    unittest.main()
