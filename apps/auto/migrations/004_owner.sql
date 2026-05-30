-- Add owner field to vehicles.
-- Owner is the vehicle's legal/financial owner, separate from responsible_user
-- who receives maintenance notifications.
-- Backfill existing rows from responsible_user (which itself falls back to created_by).

ALTER TABLE app_auto.vehicles ADD COLUMN IF NOT EXISTS owner TEXT NOT NULL DEFAULT '';
UPDATE app_auto.vehicles SET owner = CASE WHEN responsible_user != '' THEN responsible_user ELSE created_by END WHERE owner = '';
