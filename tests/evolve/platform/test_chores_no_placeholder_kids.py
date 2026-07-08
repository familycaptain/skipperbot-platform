"""Bound tests for chores.kids.pristine-empty-hero (ev-59).

Two halves:

  * TestChoresSources — pure offline source/text assertions (no DB, no JS
    runtime): the ev-52 hero OPT-IN wiring, the single neutral blurb, the live
    empty-state-hero.yaml amendment, the gutted 002, the shape of the new 007
    cleanup migration, and that no placeholder kid1/2/3 references linger in the
    manifest / store docstring / mock-seed hide-hack.

  * TestChoresCleanupMigration — DB-backed: applies the REAL migration files to
    a throwaway Postgres schema and asserts the 007 cleanup behavior (untouched
    seed removed + idempotent; adopted seed left intact with no RESTRICT abort;
    fresh gutted-002 seeds zero kids) plus the zero-active-kids safety of
    apps.chores.data.list_kids / apps.chores.store.today_by_kid. Skips cleanly
    when no live Postgres is reachable (brain-host unittest venv) — it runs on
    the test host under validate.
"""
import datetime as dt
import os
import re
import unittest
import uuid

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel_path: str) -> str:
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


# The exact placeholder household the OLD 002_seed_from_sheet.sql shipped. Kept
# here (not read from 002, which is now gutted) so the DB tests can recreate the
# "already-upgraded install" state that 007 must clean up.
LEGACY_SEED_SQL = """
INSERT INTO kids (id, name, color, sort_order, user_id, notify_morning) VALUES
  ('kid-one',    'Kid One',   '#3b82f6', 0, 'kid1', TRUE),
  ('kid-two',    'Kid Two',   '#10b981', 1, 'kid2', TRUE),
  ('kid-three',  'Kid Three', '#f59e0b', 2, 'kid3', TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO zones (id, name, rotation_start, sort_order, description) VALUES
  ('cz-bathroom',  'Bathroom',           '2022-07-18', 0, 'Shared bathroom.'),
  ('cz-bedone',    'Bedroom - Kid One',  '2022-07-18', 1, 'Kid One bedroom.'),
  ('cz-bedshared', 'Bedroom - Shared',   '2022-07-18', 2, 'Shared bedroom.')
ON CONFLICT (id) DO NOTHING;

INSERT INTO zone_members (zone_id, kid_id, position) VALUES
  ('cz-bathroom',  'kid-one',   0),
  ('cz-bathroom',  'kid-two',   1),
  ('cz-bathroom',  'kid-three', 2),
  ('cz-bedone',    'kid-one',   0),
  ('cz-bedshared', 'kid-two',   0),
  ('cz-bedshared', 'kid-three', 1)
ON CONFLICT DO NOTHING;

INSERT INTO chores (id, zone_id, dow, position, name, note) VALUES
  ('ch-bathtu0', 'cz-bathroom', 2, 0, 'Sink & Counter', ''),
  ('ch-bathtu1', 'cz-bathroom', 2, 1, 'Toilet', ''),
  ('ch-bathtu2', 'cz-bathroom', 2, 2, 'Vac & Mop', ''),
  ('ch-bathfr0', 'cz-bathroom', 5, 0, 'Sink & Counter', ''),
  ('ch-bathfr1', 'cz-bathroom', 5, 1, 'Toilet', ''),
  ('ch-bathfr2', 'cz-bathroom', 5, 2, 'Vacuum & Shower', ''),
  ('ch-b1mo0',  'cz-bedone', 1, 0, 'Laundry & Declutter', ''),
  ('ch-b1we0',  'cz-bedone', 3, 0, 'Vacuum & Empty Trash', ''),
  ('ch-b1th0',  'cz-bedone', 4, 0, 'Dust & Clean Desk', ''),
  ('ch-bsmo0', 'cz-bedshared', 1, 0, 'Vacuum', ''),
  ('ch-bsmo1', 'cz-bedshared', 1, 1, 'Clean Desk', ''),
  ('ch-bswe0', 'cz-bedshared', 3, 0, 'Laundry', ''),
  ('ch-bswe1', 'cz-bedshared', 3, 1, 'Declutter', ''),
  ('ch-bsth0', 'cz-bedshared', 4, 0, 'Dust', ''),
  ('ch-bsth1', 'cz-bedshared', 4, 1, 'Empty Trash', '')
ON CONFLICT (id) DO NOTHING;
"""


# ===========================================================================
# Offline source/text assertions (always run)
# ===========================================================================
class TestChoresSources(unittest.TestCase):
    BLURB = ("Set up chores for your household and track who does what. "
             "Add a chore to get started.")

    def test_hero_registry_opts_chores_in_not_excluded(self):
        js = _read("web/src/apps/emptyStateHero.js")
        marker = "export const EXCLUDE"
        self.assertIn(marker, js)
        opt_in_part, exclude_part = js.split(marker, 1)
        # chores registered as a default-mode OPT_IN entry ...
        self.assertRegex(
            opt_in_part,
            r"chores:\s*\{\s*mode:\s*[\"']default[\"']\s*\}",
            "chores must be a default-mode OPT_IN entry",
        )
        # ... and no longer sits in EXCLUDE.
        self.assertNotIn("chores:", exclude_part,
                         "chores must be removed from EXCLUDE")

    def test_chores_ui_manifest_has_the_single_neutral_blurb(self):
        idx = _read("apps/chores/ui/index.js")
        self.assertIn(self.BLURB, idx,
                      "chores ui/index.js must carry the exact v1 blurb")
        # Guardrail requires a non-empty blurb for default-mode opt-in entries.
        self.assertRegex(idx, r"blurb:\s*[\"']")

    def test_empty_state_hero_spec_amended_in_lockstep(self):
        y = _read("specs/platform/app-ui/empty-state-hero.yaml")
        self.assertIn("tasks, chores", y, "chores must be listed in the OPT-IN set")
        self.assertNotIn("chores, prioritize", y,
                         "chores must be removed from the EXCLUDED list")
        self.assertIn("20 apps / 26 heroes", y, "app/hero count must be bumped")

    def test_seed_002_gutted(self):
        sql = _read("apps/chores/migrations/002_seed_from_sheet.sql")
        self.assertNotIn("INSERT INTO kids", sql)
        self.assertNotIn("kid-one", sql)
        self.assertIn("007_remove_placeholder_kids.sql", sql,
                      "002 should reference its 007 upgrade companion")

    def test_007_cleanup_migration_shape(self):
        sql = _read("apps/chores/migrations/007_remove_placeholder_kids.sql")
        # Guarded (untouched-only) cleanup.
        self.assertIn("untouched", sql)
        # FK-safe delete order: completions -> zone_members -> chores -> zones -> kids.
        order = [
            sql.index("DELETE FROM chore_completions"),
            sql.index("DELETE FROM zone_members"),
            sql.index("DELETE FROM chores"),
            sql.index("DELETE FROM zones"),
            sql.index("DELETE FROM kids"),
        ]
        self.assertEqual(order, sorted(order),
                         "007 must delete children before parents (FK-safe)")

    def test_no_placeholder_kid_references_in_manifest_or_store(self):
        for rel in ("apps/chores/manifest.yaml", "apps/chores/store.py"):
            text = _read(rel)
            for tok in ("kid1", "kid2", "kid3"):
                self.assertNotIn(tok, text, f"{rel} must not reference {tok}")

    def test_mock_seed_hide_hack_removed(self):
        text = _read("scripts/seed_mock_data.py")
        self.assertNotIn("cleanup_stale", text,
                         "the moot cleanup_stale hide-hack must be removed")


# ===========================================================================
# DB-backed migration + zero-kids-safety tests (skip when no live Postgres)
# ===========================================================================
def _db_available():
    try:
        import psycopg2  # noqa: F401
        from data_layer.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True, ""
    except Exception as e:  # pragma: no cover - environment dependent
        return False, f"{type(e).__name__}: {e}"


_DB_OK, _DB_REASON = _db_available()


@unittest.skipUnless(_DB_OK, f"no live Postgres — runs on the test host under validate ({_DB_REASON})")
class TestChoresCleanupMigration(unittest.TestCase):
    MIG = "apps/chores/migrations"

    def setUp(self):
        self.schema = f"test_chores_ev59_{uuid.uuid4().hex[:10]}"
        self._run(f"CREATE SCHEMA {self.schema}")
        self._run_file("001_initial.sql")

    def tearDown(self):
        try:
            self._run(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")
        except Exception:
            pass

    # -- helpers ------------------------------------------------------------
    def _run(self, sql, in_schema=False):
        from data_layer.db import get_conn
        with get_conn() as conn:
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    if in_schema:
                        cur.execute(f"SET search_path TO {self.schema}, public")
                    cur.execute(sql)
            finally:
                conn.autocommit = False

    def _run_file(self, name):
        self._run(_read(f"{self.MIG}/{name}"), in_schema=True)

    def _count(self, table, where=""):
        from data_layer.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET search_path TO {self.schema}, public")
                cur.execute(f"SELECT count(*) FROM {table} {where}")
                return cur.fetchone()[0]

    def _seed_legacy(self):
        self._run(LEGACY_SEED_SQL, in_schema=True)

    # -- (a) untouched seed removed, idempotent -----------------------------
    def test_untouched_seed_removed_and_idempotent(self):
        self._seed_legacy()
        self.assertEqual(self._count("kids"), 3)
        self._run_file("007_remove_placeholder_kids.sql")
        self.assertEqual(self._count("kids"), 0)
        self.assertEqual(self._count("zones"), 0)
        self.assertEqual(self._count("chores"), 0)
        self.assertEqual(self._count("zone_members"), 0)
        self.assertEqual(self._count("chore_completions"), 0)
        # Re-run is a clean no-op (idempotent).
        self._run_file("007_remove_placeholder_kids.sql")
        self.assertEqual(self._count("kids"), 0)

    # -- (b) adopted seed left intact, no RESTRICT abort --------------------
    def test_renamed_kid_left_intact(self):
        self._seed_legacy()
        self._run("UPDATE kids SET name='Tyler' WHERE id='kid-one'", in_schema=True)
        self._run_file("007_remove_placeholder_kids.sql")  # must NOT abort
        self.assertEqual(self._count("kids", "WHERE id='kid-one'"), 1)
        # Conservative guard: an adopted install is left ENTIRELY intact.
        self.assertEqual(self._count("kids"), 3)

    def test_completion_left_intact(self):
        self._seed_legacy()
        self._run(
            "INSERT INTO chore_completions (id, chore_id, kid_id, chore_date) "
            "VALUES ('cc-1','ch-bathtu0','kid-one','2024-01-02')",
            in_schema=True,
        )
        self._run_file("007_remove_placeholder_kids.sql")  # must NOT abort on RESTRICT
        self.assertEqual(self._count("kids", "WHERE id='kid-one'"), 1)
        self.assertEqual(self._count("chore_completions"), 1)

    def test_user_added_kid_and_member_left_intact(self):
        self._seed_legacy()
        # A real, user-added kid + a real user zone (adoption signal).
        self._run(
            "INSERT INTO kids (id, name, color, user_id) "
            "VALUES ('real-1','Katie','#abc','katie')",
            in_schema=True,
        )
        self._run(
            "INSERT INTO zones (id, name, rotation_start) "
            "VALUES ('z-real','Kitchen','2024-01-01')",
            in_schema=True,
        )
        self._run(
            "INSERT INTO zone_members (zone_id, kid_id, position) "
            "VALUES ('z-real','real-1',0)",
            in_schema=True,
        )
        self._run_file("007_remove_placeholder_kids.sql")  # must NOT abort
        # Real data untouched ...
        self.assertEqual(self._count("kids", "WHERE id='real-1'"), 1)
        self.assertEqual(self._count("zones", "WHERE id='z-real'"), 1)
        # ... and the seed is left intact too (conservative guard).
        self.assertEqual(self._count("kids", "WHERE id='kid-one'"), 1)

    # -- (c) fresh gutted 002 seeds zero kids -------------------------------
    def test_fresh_install_seeds_zero_kids(self):
        self._run_file("002_seed_from_sheet.sql")  # gutted — a no-op
        self._run_file("007_remove_placeholder_kids.sql")
        self.assertEqual(self._count("kids"), 0)
        self.assertEqual(self._count("zones"), 0)
        self.assertEqual(self._count("chores"), 0)

    # -- (d) zero active kids never crashes ---------------------------------
    def test_zero_active_kids_safe(self):
        from apps.chores import data as _dl
        from apps.chores import store
        orig = _dl.SCHEMA
        _dl.SCHEMA = self.schema
        try:
            self.assertEqual(_dl.list_kids(active_only=True), [])
            payload = store.today_by_kid(target_date=dt.date(2024, 1, 1))
            self.assertEqual(payload["kids"], [])
        finally:
            _dl.SCHEMA = orig


if __name__ == "__main__":
    unittest.main()
