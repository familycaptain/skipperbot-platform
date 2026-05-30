-- Add responsible_user field to vehicles.
-- Defaults to empty string; at query time, empty falls back to created_by.
-- Backfill existing rows from created_by.

ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS responsible_user TEXT NOT NULL DEFAULT '';
UPDATE vehicles SET responsible_user = created_by WHERE responsible_user = '';
