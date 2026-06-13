-- Replace the dead cron cadence on the seeded PM + goals thinking domains.
--
-- The thinking scheduler is interval + active-hours based — it never parsed the
-- cron in the seed cadence ({"trigger":"schedule","cron":"..."}), so PM/goals
-- silently ran on the default 5-minute interval and the cron was a no-op.
-- Point-in-time recurrence belongs to the schedules/jobs system, not thinking.
--
-- Set an explicit interval and OMIT active_hours so the scheduler default
-- (the household's notification waking hours) applies. PM is a continuous,
-- throughout-the-day manager (frequent, but its own pm_cadence_hours gate keeps
-- it from re-engaging the same project within 24h); the goals domain is
-- long-horizon, so it ticks far less often.
--
-- thinking_domains is platform infra in the public schema (see migration 003).

BEGIN;

UPDATE public.thinking_domains
   SET cadence = '{"interval_minutes": 30}'::jsonb
 WHERE name = 'pm';

UPDATE public.thinking_domains
   SET cadence = '{"interval_minutes": 720}'::jsonb
 WHERE name = 'goals';

COMMIT;
