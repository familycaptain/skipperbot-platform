"""Bound tests for ev-108 — the Meals nightly dinner-check schedule + settings seam.

DB-free and unittest-style (the evolve runner can't collect pytest-only files):
we stub ``app_platform.settings`` / ``apps.schedules.data`` / ``app_platform.db``
/ ``app_platform.events`` / notifications / users so the logic runs without a
Postgres/psycopg2 stack, plus a few source/manifest assertions where behavior
can only be pinned at the SQL/parse level.

Run: python -m unittest tests.evolve.meals.test_dinner_schedule
"""

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _load_from_file(mod_name: str, rel_path: str) -> types.ModuleType:
    """Load a .py file as a fresh, standalone module (no package __init__ runs)."""
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(ROOT, rel_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fake schedules data layer — records upserts into a single-row store keyed by id
# ---------------------------------------------------------------------------

class _FakeSchedData:
    """Stand-in for apps.schedules.data with a stable-id keyed store (so an
    upsert on the same id can only ever produce ONE row) + a compute_next_due
    that returns a FUTURE datetime."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.upsert_calls: list[dict] = []
        self.compute_calls: list[tuple] = []

    def compute_next_due(self, recurrence_type, recurrence_rule, time_of_day=None, from_dt=None):
        self.compute_calls.append((recurrence_type, recurrence_rule, time_of_day))
        base = (from_dt or datetime.now(timezone.utc)) + timedelta(days=1)
        if time_of_day:
            h, m = (int(x) for x in str(time_of_day).split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        return base

    def get_schedule(self, schedule_id):
        row = self.rows.get(schedule_id)
        return dict(row) if row else None

    def upsert_schedule(self, schedule_id, *, next_due=None, active=True, **kw):
        self.upsert_calls.append({"id": schedule_id, "next_due": next_due,
                                  "active": active, **kw})
        prev = self.rows.get(schedule_id, {})
        # Mirror the real COALESCE(EXCLUDED.next_due, existing) semantics.
        eff_next = next_due if next_due is not None else prev.get("next_due")
        row = {"id": schedule_id, "active": bool(active), "next_due": eff_next, **kw}
        self.rows[schedule_id] = row  # keyed by id → exactly one row per id
        return dict(row)


def _install_sched_fake(fake, settings_value):
    """Patch sys.modules so apps.meals.schedule's function-local imports resolve
    to our fakes. Returns a list of (name, prev) to restore."""
    settings_mod = types.ModuleType("app_platform.settings")
    settings_mod.get = lambda key, scope=None, default=None: settings_value
    db_mod = types.ModuleType("app_platform.db")
    db_mod.execute_in_schema = lambda *a, **k: 0

    sched_pkg = types.ModuleType("apps.schedules")
    sched_pkg.data = fake
    data_mod = types.ModuleType("apps.schedules.data")
    for name in ("compute_next_due", "get_schedule", "upsert_schedule"):
        setattr(data_mod, name, getattr(fake, name))

    overrides = {
        "app_platform.settings": settings_mod,
        "app_platform.db": db_mod,
        "apps.schedules": sched_pkg,
        "apps.schedules.data": data_mod,
    }
    saved = [(n, sys.modules.get(n)) for n in overrides]
    sys.modules.update(overrides)
    return saved


def _restore(saved):
    for name, prev in saved:
        if prev is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prev


def _fresh_schedule_module():
    """Reload apps/meals/schedule.py as a standalone module for each test."""
    return _load_from_file("meals_schedule_ut", "apps/meals/schedule.py")


# ---------------------------------------------------------------------------
# (a) single-row upsert — idempotent + simulated-concurrent → exactly ONE row
# ---------------------------------------------------------------------------

class SingleRowUpsert(unittest.TestCase):
    def test_idempotent_and_concurrent_yield_one_row(self):
        fake = _FakeSchedData()
        saved = _install_sched_fake(fake, "21:00")
        try:
            sched = _fresh_schedule_module()
            # idempotent: run it several times
            sched.reconcile_dinner_schedule()
            sched.reconcile_dinner_schedule()
            # "simulated concurrent": two callers, same stable id
            sched.reconcile_dinner_schedule()
            self.assertEqual(len(fake.rows), 1, "must be exactly ONE schedule row")
            self.assertIn(sched.SCHEDULE_ID, fake.rows)
            self.assertTrue(all(c["id"] == sched.SCHEDULE_ID for c in fake.upsert_calls))
        finally:
            _restore(saved)

    def test_real_upsert_uses_on_conflict_pk(self):
        # Race-safety at the SQL level: the real upsert converges on the PK.
        src = _read("apps/schedules/data.py")
        self.assertIn("def upsert_schedule(", src)
        self.assertIn("ON CONFLICT (id) DO UPDATE", src)
        self.assertIn("COALESCE(EXCLUDED.next_due, schedules.next_due)", src)


# ---------------------------------------------------------------------------
# (b) enum times / Off / re-enable → time_of_day + active + FUTURE next_due
# (c) exactly ONE fire per day — daily recurrence, not an interval
# (d) fail-closed on out-of-enum value
# ---------------------------------------------------------------------------

class ReconcileBehavior(unittest.TestCase):
    def _run(self, fake, value):
        saved = _install_sched_fake(fake, value)
        try:
            sched = _fresh_schedule_module()
            sched.reconcile_dinner_schedule()
            return sched
        finally:
            _restore(saved)

    def test_enum_time_sets_active_and_future_next_due(self):
        fake = _FakeSchedData()
        self._run(fake, "20:00")
        row = fake.rows["sch-meals-dinner-check"]
        self.assertTrue(row["active"])
        self.assertEqual(row["time_of_day"], "20:00")
        self.assertIsNotNone(row["next_due"])
        self.assertGreater(row["next_due"], datetime.now(timezone.utc),
                           "next_due must be in the FUTURE")

    def test_exactly_one_fire_per_day_daily_not_interval(self):
        fake = _FakeSchedData()
        self._run(fake, "18:30")
        call = fake.upsert_calls[-1]
        # daily @ a single time_of_day == once per day (NOT every-30-min / interval)
        self.assertEqual(call["recurrence_type"], "daily")
        self.assertEqual(call["recurrence_rule"], {"every": 1})
        self.assertEqual(call["time_of_day"], "18:30")
        self.assertNotEqual(call["recurrence_type"], "interval")

    def test_off_disables(self):
        fake = _FakeSchedData()
        self._run(fake, "Off")
        row = fake.rows["sch-meals-dinner-check"]
        self.assertFalse(row["active"])

    def test_out_of_enum_is_fail_closed(self):
        fake = _FakeSchedData()
        # bogus value must NOT raise and must disable (fail-closed)
        sched = self._run(fake, "25:99-nonsense")
        row = fake.rows["sch-meals-dinner-check"]
        self.assertFalse(row["active"])

    def test_reenable_after_off_sets_future_next_due(self):
        fake = _FakeSchedData()
        # 1) enable at 21:00
        saved = _install_sched_fake(fake, "21:00")
        try:
            sched = _fresh_schedule_module()
            sched.reconcile_dinner_schedule()
        finally:
            _restore(saved)
        # 2) turn Off
        saved = _install_sched_fake(fake, "Off")
        try:
            sched = _fresh_schedule_module()
            sched.reconcile_dinner_schedule()
        finally:
            _restore(saved)
        self.assertFalse(fake.rows["sch-meals-dinner-check"]["active"])
        compute_before = len(fake.compute_calls)
        # 3) re-enable at 19:00 — must recompute next_due to a FUTURE occurrence
        saved = _install_sched_fake(fake, "19:00")
        try:
            sched = _fresh_schedule_module()
            sched.reconcile_dinner_schedule()
        finally:
            _restore(saved)
        row = fake.rows["sch-meals-dinner-check"]
        self.assertTrue(row["active"])
        self.assertEqual(row["time_of_day"], "19:00")
        self.assertGreater(len(fake.compute_calls), compute_before,
                           "re-enable must recompute next_due (not fire immediately)")
        self.assertGreater(row["next_due"], datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# (e) config.changed emits {scope,key} only (no value), secrets skipped,
#     and a subscriber raise does NOT propagate to config.set
# ---------------------------------------------------------------------------

class ConfigChangedEmit(unittest.TestCase):
    def _load_config(self, emit_impl):
        # Stub data_layer.db (config imports execute/fetch_one at module top).
        dl = types.ModuleType("data_layer.db")
        dl.execute = lambda *a, **k: 1
        dl.fetch_one = lambda *a, **k: None
        dl.fetch_all = lambda *a, **k: []
        events = types.ModuleType("app_platform.events")
        events.emit = emit_impl
        saved = [(n, sys.modules.get(n)) for n in ("data_layer.db", "app_platform.events")]
        sys.modules["data_layer.db"] = dl
        sys.modules["app_platform.events"] = events
        cfg = _load_from_file("config_ut", "app_platform/config.py")
        return cfg, saved

    def test_emit_is_value_free(self):
        calls = []
        cfg, saved = self._load_config(lambda et, payload, emitted_by="": calls.append((et, payload)))
        try:
            cfg.set("dinner_inquiry_time", "20:00", scope="app:meals")
        finally:
            _restore(saved)
        self.assertEqual(len(calls), 1)
        et, payload = calls[0]
        self.assertEqual(et, "config.changed")
        self.assertEqual(payload, {"scope": "app:meals", "key": "dinner_inquiry_time"})
        self.assertNotIn("value", payload)

    def test_secret_key_is_not_emitted(self):
        calls = []
        cfg, saved = self._load_config(lambda et, payload, emitted_by="": calls.append((et, payload)))
        try:
            cfg.set("api_token", "sekret", scope="platform", secret=True)
        finally:
            _restore(saved)
        self.assertEqual(calls, [], "secret-flagged writes must not emit config.changed")

    def test_subscriber_raise_does_not_propagate(self):
        def _boom(et, payload, emitted_by=""):
            raise RuntimeError("subscriber blew up")
        cfg, saved = self._load_config(_boom)
        try:
            # Must NOT raise — the emit is fault-isolated around the committed write.
            cfg.set("k", "v", scope="app:meals")
        except Exception as exc:  # pragma: no cover
            _restore(saved)
            self.fail(f"config.set propagated a subscriber failure: {exc}")
        else:
            _restore(saved)


# ---------------------------------------------------------------------------
# (f) manifest job_types + config enum parse
# ---------------------------------------------------------------------------

class ManifestParse(unittest.TestCase):
    def setUp(self):
        import yaml
        self.m = yaml.safe_load(_read("apps/meals/manifest.yaml"))

    def test_job_type_registered(self):
        jobs = {j["type"]: j for j in self.m.get("job_types", [])}
        self.assertIn("meals_dinner_check", jobs)
        self.assertEqual(jobs["meals_dinner_check"]["handler"], "handlers.handle_dinner_check")

    def test_config_enum_choices(self):
        cfg = {c["key"]: c for c in self.m.get("config", [])}
        self.assertIn("dinner_inquiry_time", cfg)
        entry = cfg["dinner_inquiry_time"]
        self.assertEqual(entry["default"], "21:00")
        values = {c["value"] for c in entry["choices"]}
        self.assertIn("Off", values)
        self.assertIn("21:00", values)
        self.assertIn("17:00", values)
        self.assertIn("22:00", values)


# ---------------------------------------------------------------------------
# (g) handle_dinner_check: logged → no notification; not-logged → one notification
# ---------------------------------------------------------------------------

class HandleDinnerCheck(unittest.TestCase):
    def _load_handlers(self, existing_log):
        recorded = {"notifs": []}

        cfg = types.ModuleType("config")
        cfg.logger = types.SimpleNamespace(info=lambda *a, **k: None,
                                           warning=lambda *a, **k: None,
                                           error=lambda *a, **k: None,
                                           debug=lambda *a, **k: None)
        ilr = types.ModuleType("image_link_registry")
        ilr.register_image_link_handler = lambda *a, **k: None
        meals_data = types.ModuleType("apps.meals.data")
        meals_data.link_meal_photo = lambda *a, **k: None
        meals_data.get_meal_log_for_date = lambda date_str, meal_type="dinner": existing_log
        events = types.ModuleType("app_platform.events")
        events.subscribe = lambda event_type: (lambda fn: fn)
        notifs = types.ModuleType("app_platform.notifications")
        notifs.create_notification = lambda **kw: recorded["notifs"].append(kw)
        users = types.ModuleType("data_layer.users")
        users.get_primary_user = lambda: "rodney"

        overrides = {
            "config": cfg,
            "image_link_registry": ilr,
            "apps.meals.data": meals_data,
            "app_platform.events": events,
            "app_platform.notifications": notifs,
            "data_layer.users": users,
        }
        saved = [(n, sys.modules.get(n)) for n in overrides]
        sys.modules.update(overrides)
        try:
            handlers = _load_from_file("meals_handlers_ut", "apps/meals/handlers.py")
        finally:
            _restore(saved)
        # Re-install the runtime stubs the handler needs at CALL time.
        call_saved = [(n, sys.modules.get(n)) for n in overrides]
        sys.modules.update(overrides)
        return handlers, recorded, call_saved

    def _ctx(self):
        return types.SimpleNamespace(update_progress=lambda *a, **k: None)

    def test_already_logged_sends_no_notification(self):
        handlers, recorded, call_saved = self._load_handlers({"description": "Tacos"})
        try:
            out = handlers.handle_dinner_check({"id": "j1"}, self._ctx())
        finally:
            _restore(call_saved)
        self.assertEqual(recorded["notifs"], [])
        self.assertIn("already logged", out.lower())

    def test_not_logged_sends_one_notification_to_primary(self):
        handlers, recorded, call_saved = self._load_handlers(None)
        try:
            handlers.handle_dinner_check({"id": "j1"}, self._ctx())
        finally:
            _restore(call_saved)
        self.assertEqual(len(recorded["notifs"]), 1)
        n = recorded["notifs"][0]
        self.assertEqual(n["recipient"], "rodney")
        self.assertEqual(n["source_type"], "meals_dinner_check")


# ---------------------------------------------------------------------------
# (h) domain_for_source_type('meals_dinner_check') == 'meals'
# ---------------------------------------------------------------------------

class DomainMapping(unittest.TestCase):
    def test_meals_source_types_map_to_meals_domain(self):
        from app_platform import consciousness as C
        self.assertEqual(C.domain_for_source_type("meals_dinner_check"), "meals")
        self.assertEqual(C.domain_for_source_type("meals"), "meals")
        self.assertEqual(C.domain_for_source_type("meals_log"), "meals")


if __name__ == "__main__":
    unittest.main()
