-- Migration 001: Create brainstorming tables (ideas + idea_parts) in the
-- public schema.
--
-- The migrator runs this with search_path = app_brainstorming, public, but the
-- data layer (data_layer/brainstorming.py) uses UNQUALIFIED table names against
-- the agent DB pool, whose default search_path is public. So these tables MUST
-- live in public. Everything below is fully schema-qualified so it lands in
-- public regardless of the migrator's search_path.
--
-- Columns are taken verbatim from the original migrations/021_brainstorming.sql.
-- Create-only: no legacy data copy.

CREATE TABLE IF NOT EXISTS public.ideas (
  id          TEXT PRIMARY KEY,                    -- bs-{hex8}
  title       TEXT NOT NULL,
  summary     TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'idea',        -- idea, exploring, developing, parked, graduated
  priority    TEXT NOT NULL DEFAULT 'medium',       -- high, medium, low
  tags        TEXT[] NOT NULL DEFAULT '{}',
  project_id  TEXT,                                -- FK to goals if graduated
  created_by  TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.idea_parts (
  id          TEXT PRIMARY KEY,                    -- bp-{hex8}
  idea_id     TEXT NOT NULL REFERENCES public.ideas(id) ON DELETE CASCADE,
  type        TEXT NOT NULL DEFAULT 'document',    -- document, flowchart, image, link
  title       TEXT NOT NULL DEFAULT '',
  is_main     BOOLEAN NOT NULL DEFAULT FALSE,      -- true for auto-created primary doc
  sort_order  INT NOT NULL DEFAULT 0,
  content     TEXT NOT NULL DEFAULT '',             -- markdown for docs
  meta        JSONB NOT NULL DEFAULT '{}',          -- type-specific data
  version     INT NOT NULL DEFAULT 1,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_idea_parts_idea ON public.idea_parts(idea_id);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON public.ideas(status);
CREATE INDEX IF NOT EXISTS idx_ideas_created_by ON public.ideas(created_by);
