-- ev-84: gate backlog auto-bootstrap on a per-user flag so a DELIBERATE backlog
-- disconnect (Settings -> "— Select a list —") is respected and the user is not
-- silently re-provisioned on next access. Default false: existing users whose
-- backlog was never set get backfilled exactly once (the flag flips to true when
-- the Backlog list is created + connected).
BEGIN;
ALTER TABLE todo_config
    ADD COLUMN IF NOT EXISTS backlog_bootstrapped boolean NOT NULL DEFAULT false;
COMMIT;
