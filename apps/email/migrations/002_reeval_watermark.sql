-- ev-98: gate the whole-backlog re-evaluation on a per-account watermark + a
-- trigger-time snapshot, so a routine 15-min poll no longer re-scans all unmatched
-- history (and makes ~1 Gmail label API call per email) when rules are unchanged.
--   last_reeval_at            — advanced to the CAPTURED target watermark only when a
--                               triggered drain fully completes; NULL => never re-eval'd
--                               (pre-migration accounts re-eval once).
--   reeval_target_watermark   — max active-rule COALESCE(updated_at,created_at) captured
--                               at drain START (last_reeval_at advances to it on full
--                               drain); NULL when no drain is in flight.
--   reeval_upper_bound_at/_id — the frozen backlog upper bound (received_at, id) of the
--                               currently-unmatched set captured at drain START; the drain
--                               processes ONLY entries at/below this keyset (so mid-drain
--                               arrivals are not chased). NULL when idle.
--   reeval_cursor_at/_id      — the persisted drain cursor (received_at, id) of the last
--                               processed entry; the next poll continues strictly below it.
--                               NULL when idle / drain complete.
-- (upper_bound + cursor are stored as (received_at, id) keysets so they stay consistent
--  with the newest-first ORDER BY received_at DESC, id DESC — no boundary skip/dup.)
BEGIN;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS last_reeval_at          TIMESTAMPTZ NULL;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS reeval_target_watermark TIMESTAMPTZ NULL;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS reeval_upper_bound_at   TIMESTAMPTZ NULL;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS reeval_upper_bound_id   TEXT NULL;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS reeval_cursor_at        TIMESTAMPTZ NULL;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS reeval_cursor_id        TEXT NULL;
COMMIT;
