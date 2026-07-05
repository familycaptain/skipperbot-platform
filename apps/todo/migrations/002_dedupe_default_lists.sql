-- =============================================================================
-- Todo app — 002_dedupe_default_lists.sql  (ev-62)
-- =============================================================================
-- One-time, forward-only, idempotent cleanup of DUPLICATE "<user>'s To-Do"
-- default lists left behind by the pre-fix non-atomic ensure_default_list race
-- (the To-Do UI opened /config and /items concurrently, and each bootstrapped a
-- default list before the other persisted the pointer -> two identical lists).
-- The runtime race itself is fixed in apps/todo/data.py::claim_default_list.
--
-- CROSS-SCHEMA BY DESIGN: this migration lives in app_todo but deliberately
-- reaches app_lists.* BY QUALIFICATION. Only app_todo.todo_config knows which
-- lists are todo defaults, so the dedupe MUST live here — an app_lists migration
-- would need a forbidden lists->todo dependency. This is a one-time forward
-- cleanup, not runtime code (which still routes through apps.lists.store).
-- NOTE: a raw DELETE here bypasses apps.lists.store.delete_list, so it does not
-- emit the list-'deleted' entity event; acceptable because we only ever remove
-- brand-new EMPTY duplicate lists (no items, no memory/folder references).
--
-- ORDERING: app_lists migrates before app_todo (apps load alphabetically and
-- both are REQUIRED apps), so app_lists.lists is present when this runs; the
-- to_regclass() guard is belt-and-suspenders.
--
-- IDEMPOTENT: after one run each user has a single default list, so the
-- HAVING count(*) > 1 group is empty; re-runs and fresh installs are no-ops.
-- Wrapped in its OWN BEGIN/COMMIT so the repoint+delete is atomic under the
-- autocommit migrator.

BEGIN;

DO $dedupe$
DECLARE
  _removed integer;
BEGIN
  IF to_regclass('app_lists.lists') IS NULL THEN
    RAISE NOTICE 'ev-62 dedupe: app_lists.lists absent; skipping';
    RETURN;
  END IF;

  -- 1) Repoint each owner's default_list_id to the DATA-BEARING keeper FIRST
  --    (most active items, then oldest, then id), so no config is ever left
  --    pointing at a list we go on to delete.
  WITH auto AS (
    SELECT l.id, l.created_by, l.name, l.created_at,
           (SELECT count(*) FROM app_lists.list_items li
              WHERE li.list_id = l.id AND li.archived = false) AS live_items
      FROM app_lists.lists l
     WHERE l.name LIKE '%''s To-Do'
  ),
  grp AS (
    SELECT created_by, name FROM auto
     GROUP BY created_by, name HAVING count(*) > 1
  ),
  keeper AS (
    SELECT DISTINCT ON (a.created_by, a.name) a.created_by, a.id
      FROM auto a JOIN grp g USING (created_by, name)
     ORDER BY a.created_by, a.name, a.live_items DESC, a.created_at ASC, a.id ASC
  )
  UPDATE app_todo.todo_config c
     SET default_list_id = keeper.id, updated_at = now()
    FROM keeper
   WHERE c.user_id = keeper.created_by
     AND c.default_list_id IS DISTINCT FROM keeper.id;

  -- 2) Delete ONLY non-keeper sibling dups that have ZERO items (never any
  --    history) AND are not referenced (post-repoint) by any default_list_id
  --    or backlog_list_id. A twin with ANY items is left fully intact.
  WITH auto AS (
    SELECT l.id, l.created_by, l.name, l.created_at,
           (SELECT count(*) FROM app_lists.list_items li
              WHERE li.list_id = l.id AND li.archived = false) AS live_items,
           (SELECT count(*) FROM app_lists.list_items li
              WHERE li.list_id = l.id) AS total_items
      FROM app_lists.lists l
     WHERE l.name LIKE '%''s To-Do'
  ),
  grp AS (
    SELECT created_by, name FROM auto
     GROUP BY created_by, name HAVING count(*) > 1
  ),
  keeper AS (
    SELECT DISTINCT ON (a.created_by, a.name) a.created_by, a.name, a.id AS keep_id
      FROM auto a JOIN grp g USING (created_by, name)
     ORDER BY a.created_by, a.name, a.live_items DESC, a.created_at ASC, a.id ASC
  ),
  deletable AS (
    SELECT a.id
      FROM auto a
      JOIN keeper k ON k.created_by = a.created_by AND k.name = a.name
     WHERE a.id <> k.keep_id
       AND a.total_items = 0
  )
  DELETE FROM app_lists.lists l
   USING deletable d
   WHERE l.id = d.id
     AND NOT EXISTS (
           SELECT 1 FROM app_todo.todo_config c
            WHERE c.default_list_id = l.id OR c.backlog_list_id = l.id);
  GET DIAGNOSTICS _removed = ROW_COUNT;

  RAISE NOTICE 'ev-62 dedupe: removed % empty duplicate default list(s)', _removed;
END
$dedupe$;

COMMIT;
