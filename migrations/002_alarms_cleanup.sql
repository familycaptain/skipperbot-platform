-- Phase 5b demolition (specs/CONSCIOUSNESS.md §13 Phase 5, §18 Q3/Q8/Q10):
-- thinking_domains survives as the SCHEDULER (alarm) REGISTRY — cadence /
-- enabled / budget_priority are runtime-tunable state. Skill definitions are
-- versioned artifacts in app manifests, so the legacy per-domain tool columns
-- go; and the retired domain ROWS go:
--   * g-* rows: per-goal thinking domains — goals are DATA now; the pm sweep
--     routes work (oversight) and goal_work jobs execute (hands).
--   * self: never had a handler; if reflection is ever wanted it will be a
--     voice-layer skill, not a corpse row (Q10).
ALTER TABLE public.thinking_domains DROP COLUMN IF EXISTS observe_tool;
ALTER TABLE public.thinking_domains DROP COLUMN IF EXISTS evaluate_tool;
ALTER TABLE public.thinking_domains DROP COLUMN IF EXISTS act_tool;
DELETE FROM public.thinking_domains WHERE name LIKE 'g-%' OR name = 'self';
