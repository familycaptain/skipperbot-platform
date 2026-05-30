-- Add next_generate_at to bounty_templates for recurrence cooldown.
-- When a recurring bounty is approved, next_generate_at is set to
-- now() + recurrence_days. The next bounty instance is only created
-- once that timestamp is reached, enforcing a minimum cooldown.

ALTER TABLE bounty_templates
    ADD COLUMN IF NOT EXISTS next_generate_at TIMESTAMPTZ;

-- Backfill: any active template with no pending open bounty should be
-- eligible to generate immediately.
UPDATE bounty_templates SET next_generate_at = now()
WHERE is_active = TRUE AND next_generate_at IS NULL;
