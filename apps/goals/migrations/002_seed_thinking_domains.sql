-- Seed the goals app's declared thinking domains (pm, goals) into
-- public.thinking_domains.
--
-- They are declared in apps/goals/manifest.yaml, but the loader's
-- _register_thinking_domain() only LOGS the registration — it never inserts a
-- row. As a result auto_memory.py records PM observations under
-- skipper_state.domain='pm', which has a foreign key to thinking_domains(name)
-- that never existed: every goal/project/task create/update silently failed to
-- record its PM observation, and the onboarding seed made it visible on first
-- run (FK violation in the boot log).
--
-- Idempotent (ON CONFLICT DO NOTHING). Domains start disabled
-- (enabled_by_default: false in the manifest) — the row just needs to exist so
-- the FK is satisfiable; enabling the PM domain is a separate user action.

INSERT INTO public.thinking_domains
    (name, description, observe_tool, evaluate_tool, act_tool, knowledge_refs, cadence, budget_priority, enabled, created_by)
VALUES
    ('pm',
     'Project Manager — review at-risk items, nudge owners, surface what to work on.',
     '', '', '', '[]'::jsonb, '{"trigger": "schedule", "cron": "0 9 * * *"}'::jsonb, 'high', false, ''),
    ('goals',
     'Goal-level reasoning — long-horizon planning, gap detection.',
     '', '', '', '[]'::jsonb, '{"trigger": "schedule", "cron": "0 6 * * 0"}'::jsonb, 'low', false, '')
ON CONFLICT (name) DO NOTHING;
