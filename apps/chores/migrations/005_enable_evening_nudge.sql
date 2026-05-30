-- Enable the 8:00 PM nudge for everyone by default.
-- The kids table column was originally created with DEFAULT FALSE (Phase-2 opt-in
-- per the original spec), but the evening nudge is now part of Phase 1.
-- Existing rows get flipped; future rows will need the column default updated.

ALTER TABLE kids ALTER COLUMN notify_evening SET DEFAULT TRUE;

UPDATE kids SET notify_evening = TRUE WHERE active = TRUE;
