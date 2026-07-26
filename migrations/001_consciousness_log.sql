-- 001_consciousness_log.sql — the consciousness log (specs/CONSCIOUSNESS.md §11)
--
-- The single serial event log: Skipper's one running memory. One row = one
-- EVENT (a chat exchange is TWO rows). Append-only; total order via `seq`
-- (bigserial — assigned inside the INSERT, atomic with the row, §11.9).
-- The log IS the attention queue: rows with needs_attention AND no attended_at
-- are the pending queue (§11.5). `lane` is DERIVED by log_event(), never
-- caller-supplied (§15). All external references are soft (no FKs, §11.7).
--
-- Idempotent; no BEGIN/COMMIT (the platform-migration runner wraps the file).

CREATE TABLE IF NOT EXISTS public.consciousness_log (
    id              text PRIMARY KEY,                       -- cl-<8hex>
    seq             bigserial NOT NULL UNIQUE,              -- total order; cursors/windows key on this
    created_at      timestamptz NOT NULL DEFAULT now(),
    kind            text NOT NULL
                    CHECK (kind IN ('message', 'activity', 'event', 'summary')),
    who_from        text NOT NULL,                          -- 'rodney' | 'skipper' | 'system'
    who_to          text,                                   -- recipient for messages; person concerned for connection events
    domain          text NOT NULL,                          -- producing/handling skill: chat, onboarding, goals, pm, chores, system, ...
    lane            text NOT NULL,                          -- derived serialization key: person:<who> | domain:<domain>
    surface         text,                                   -- web | voice | discord | mobile | NULL (internal)
    reply_to        text,                                   -- parent cl- id (soft ref)
    thread_id       text,                                   -- thread-root cl- id / logical thread key (soft ref)
    subject_id      text,                                   -- linked entity (g-, t-, ...) (soft ref)
    content         text NOT NULL,
    payload         jsonb,
    embedding       public.vector(1536),                    -- backfilled async by the subconscious; NULL until then
    needs_attention boolean NOT NULL DEFAULT false,         -- "a responder is owed and none is live" (§11.5)
    attended_at     timestamptz                             -- responder turn completed (or =created_at when pre-attended by a live/legacy channel)
);

-- Ordering + lens indexes (§11.2)
CREATE INDEX IF NOT EXISTS idx_cl_who_to    ON public.consciousness_log (who_to, seq DESC);
CREATE INDEX IF NOT EXISTS idx_cl_who_from  ON public.consciousness_log (who_from, seq DESC);
CREATE INDEX IF NOT EXISTS idx_cl_thread    ON public.consciousness_log (thread_id, seq) WHERE thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cl_domain    ON public.consciousness_log (domain, seq DESC);

-- The attention queue: oldest unattended per lane, one indexed scan (§11.5, §15)
CREATE INDEX IF NOT EXISTS idx_cl_attention ON public.consciousness_log (lane, seq)
    WHERE needs_attention AND attended_at IS NULL;

-- Semantic search over the log (retrieval source 2, §12.3)
-- SCHEMA-QUALIFIED on purpose (type above too): 000_baseline.sql is pg_dump output
-- and line 41 runs `set_config('search_path', '', false)` — session-wide, not
-- transaction-local. On a FRESH install the baseline and this file are applied over
-- the SAME connection, so by the time we get here the search_path is EMPTY and a
-- bare `vector` / `vector_cosine_ops` cannot resolve. (It "works" on an existing DB
-- only because the baseline is skipped there, leaving the default search_path.)
-- Qualify every extension-provided name, exactly as the baseline itself does.
CREATE INDEX IF NOT EXISTS idx_cl_embedding ON public.consciousness_log
    USING ivfflat (embedding public.vector_cosine_ops) WITH (lists = 10);

-- Backfill idempotency (§11.8): one log event per legacy source row, enforced by the DB
CREATE UNIQUE INDEX IF NOT EXISTS idx_cl_legacy_id ON public.consciousness_log ((payload->>'legacy_id'))
    WHERE payload ? 'legacy_id';

-- Register the cl- prefix so tools/resolvers can dereference log ids like any entity (§11.7)
INSERT INTO public.entity_types (prefix, name, id_format, table_name)
SELECT 'cl', 'consciousness event', 'cl-', 'consciousness_log'
WHERE NOT EXISTS (SELECT 1 FROM public.entity_types WHERE prefix = 'cl');

-- Q3 (§14): thinking_domains survives as the SCHEDULER registry; the legacy
-- three-phase tool columns are ignored (dropped in 002_alarms_cleanup). Loosen
-- them so legacy alarm rows need not carry dummy values.
--
-- GUARDED, and it must stay guarded: these columns exist ONLY on databases created
-- before the baseline was regenerated without them. A bare
-- `ALTER COLUMN ... DROP NOT NULL` is a no-op when a column is already nullable,
-- but it is a HARD ERROR ("column does not exist") when the column is absent —
-- which is every FRESH install. That aborts init_db before the agent starts, so a
-- brand-new user gets a permanent boot loop. Touch only columns that are really
-- there.
DO $$
DECLARE col text;
BEGIN
    FOR col IN
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'thinking_domains'
          AND column_name IN ('observe_tool', 'evaluate_tool', 'act_tool')
    LOOP
        EXECUTE format(
            'ALTER TABLE public.thinking_domains ALTER COLUMN %I DROP NOT NULL', col);
    END LOOP;
END $$;
