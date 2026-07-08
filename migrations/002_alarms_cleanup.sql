-- Phase 5b demolition (specs/CONSCIOUSNESS.md §13 Phase 5, §18 Q3/Q8/Q10):
-- thinking_domains survives as the SCHEDULER (alarm) REGISTRY — cadence /
-- enabled / budget_priority are runtime-tunable state. Skill definitions are
-- versioned artifacts in app manifests, so the legacy per-domain tool columns
-- go; and the retired domain ROWS go:
--   * g-* rows: per-goal thinking domains — goals are DATA now; the pm sweep
--     routes work (oversight) and goal_work jobs execute (hands).
--   * self: never had a handler; if reflection is ever wanted it will be a
--     voice-layer skill, not a corpse row (Q10).
--
-- DEPENDENTS FIRST (prod has rows a clean test box didn't — the first cut of
-- this migration failed there on skipper_state_domain_fkey):
--
-- 1. thinking_log: cycle HISTORY legitimately references retired domains — a
--    log should not FK its registry (history must outlive registry rows).
--    Drop the constraint; every g-*/self cycle row is KEPT.
ALTER TABLE public.thinking_log DROP CONSTRAINT IF EXISTS thinking_log_domain_fkey;

-- 2. skipper_state: legacy per-goal scratch state (pending-DM bookkeeping,
--    observations, per-goal working memory keyed by the g-* domain) is unread
--    under consciousness-v1 (goals working memory lives under domain='goals'
--    + subject_id). Archive zero-loss, then delete so the registry rows can go.
CREATE TABLE IF NOT EXISTS public.skipper_state_legacy_goal_domains
    (LIKE public.skipper_state INCLUDING DEFAULTS);
INSERT INTO public.skipper_state_legacy_goal_domains
    SELECT * FROM public.skipper_state
    WHERE domain LIKE 'g-%' OR domain = 'self';
DELETE FROM public.skipper_state WHERE domain LIKE 'g-%' OR domain = 'self';

-- 3. The registry itself: lean columns, retired rows.
ALTER TABLE public.thinking_domains DROP COLUMN IF EXISTS observe_tool;
ALTER TABLE public.thinking_domains DROP COLUMN IF EXISTS evaluate_tool;
ALTER TABLE public.thinking_domains DROP COLUMN IF EXISTS act_tool;
DELETE FROM public.thinking_domains WHERE name LIKE 'g-%' OR name = 'self';
