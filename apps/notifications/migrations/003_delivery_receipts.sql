-- Per-surface delivery receipts.
--
-- `delivered` is a single boolean meaning "at least one channel worked". That is enough
-- to stop retrying and nothing else: it cannot answer whether the phone got it, whether
-- Discord failed while Pushover succeeded, or whether a person was actually reached at
-- all. Skipper needs to know what it managed to do before it can talk about it honestly
-- ("I sent that to your phone this morning") or decide someone is unreachable.
--
-- ONE UTTERANCE, MANY DELIVERIES. This is deliberately stored ON the notification row
-- rather than as extra consciousness-log entries. The log records WHAT was said, once,
-- before any fan-out; where it went is a set of receipts against that single row. A log
-- row per surface would put the same message in the web console two or three times,
-- which is exactly the duplicate this design exists to prevent.
--
-- Shape: {"discord": {"ok": true, "detail": "..."}, "mobile": {"ok": false, ...}, ...}
-- Empty {} means delivery has not run yet — distinct from "ran and reached nobody",
-- which is a populated object whose entries are all ok:false.

ALTER TABLE app_notifications.notifications
    ADD COLUMN IF NOT EXISTS receipts jsonb NOT NULL DEFAULT '{}'::jsonb;
