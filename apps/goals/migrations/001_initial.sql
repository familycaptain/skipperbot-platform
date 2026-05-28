-- =============================================================================
-- Goals app — 001_initial.sql
-- =============================================================================
-- Creates the app_goals schema and the goals/projects/tasks tables.
--
-- The platform's app_platform/migrator.py invokes this with
-- search_path = app_goals, public already set within its transaction,
-- so unqualified table names resolve into the goals app's schema. The
-- CREATE SCHEMA + SET search_path + BEGIN/COMMIT lines at the top are
-- a defensive belt-and-suspenders so this file also applies cleanly if
-- run by hand:
--     psql -d skipperbot -f apps/goals/migrations/001_initial.sql
--
-- The whole migration runs in a single transaction so search_path
-- changes stick for every statement, and a failure rolls back cleanly.
--
-- Idempotent. Re-running is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_goals;
SET LOCAL search_path TO app_goals, public;

-- =============================================================================
-- goals — long-horizon outcomes, top of the hierarchy
-- =============================================================================

CREATE TABLE IF NOT EXISTS goals (
    id                  text NOT NULL,
    name                text NOT NULL,
    owners              text[] NOT NULL DEFAULT '{}'::text[],
    collaborators       text[] DEFAULT '{}'::text[],
    target_date         text NOT NULL DEFAULT ''::text,
    status              text NOT NULL DEFAULT 'not_started'::text,
    stack_rank          integer NOT NULL DEFAULT 0,
    notes               text NOT NULL DEFAULT ''::text,
    definition_of_done  text DEFAULT ''::text,
    history             jsonb NOT NULL DEFAULT '[]'::jsonb,
    artifacts           text[] NOT NULL DEFAULT '{}'::text[],
    created_by          text NOT NULL DEFAULT ''::text,
    created_at          timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE goals
        ADD CONSTRAINT goals_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE goals
        ADD CONSTRAINT goals_status_check CHECK (status = ANY (ARRAY[
            'not_started'::text, 'in_progress'::text, 'done'::text,
            'blocked'::text, 'deferred'::text, 'cancelled'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;


-- =============================================================================
-- projects — scoped work under a goal
-- =============================================================================

CREATE TABLE IF NOT EXISTS projects (
    id                  text NOT NULL,
    name                text NOT NULL,
    goal_id             text NOT NULL,
    owners              text[] NOT NULL DEFAULT '{}'::text[],
    due_date            text NOT NULL DEFAULT ''::text,
    priority            text NOT NULL DEFAULT 'medium'::text,
    status              text NOT NULL DEFAULT 'not_started'::text,
    stack_rank          integer NOT NULL DEFAULT 0,
    notes               text NOT NULL DEFAULT ''::text,
    definition_of_done  text DEFAULT ''::text,
    pm_cadence_minutes  integer,
    history             jsonb NOT NULL DEFAULT '[]'::jsonb,
    artifacts           text[] NOT NULL DEFAULT '{}'::text[],
    auto_nag            jsonb,
    trello              jsonb,
    created_by          text NOT NULL DEFAULT ''::text,
    created_at          timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE projects
        ADD CONSTRAINT projects_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE projects
        ADD CONSTRAINT projects_goal_id_fkey
        FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE projects
        ADD CONSTRAINT projects_priority_check CHECK (priority = ANY (ARRAY[
            'low'::text, 'medium'::text, 'high'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE projects
        ADD CONSTRAINT projects_status_check CHECK (status = ANY (ARRAY[
            'not_started'::text, 'in_progress'::text, 'done'::text,
            'blocked'::text, 'deferred'::text, 'cancelled'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_projects_goal_id ON projects (goal_id);


-- =============================================================================
-- tasks — unit of work under a project
-- =============================================================================

CREATE TABLE IF NOT EXISTS tasks (
    id                  text NOT NULL,
    name                text NOT NULL,
    project_id          text NOT NULL,
    parent_task_id      text,
    assigned_to         text[] NOT NULL DEFAULT '{}'::text[],
    due_date            text NOT NULL DEFAULT ''::text,
    priority            text NOT NULL DEFAULT 'medium'::text,
    status              text NOT NULL DEFAULT 'not_started'::text,
    stack_rank          integer NOT NULL DEFAULT 0,
    depends_on          text[] NOT NULL DEFAULT '{}'::text[],
    trello_card_id      text NOT NULL DEFAULT ''::text,
    trello_list         text NOT NULL DEFAULT ''::text,
    trello_linked       boolean NOT NULL DEFAULT false,
    notes               text NOT NULL DEFAULT ''::text,
    definition_of_done  text DEFAULT ''::text,
    history             jsonb NOT NULL DEFAULT '[]'::jsonb,
    artifacts           text[] NOT NULL DEFAULT '{}'::text[],
    created_by          text NOT NULL DEFAULT ''::text,
    created_at          timestamp with time zone NOT NULL DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE tasks
        ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE tasks
        ADD CONSTRAINT tasks_project_id_fkey
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE tasks
        ADD CONSTRAINT tasks_parent_task_id_fkey
        FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE tasks
        ADD CONSTRAINT tasks_priority_check CHECK (priority = ANY (ARRAY[
            'low'::text, 'medium'::text, 'high'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE tasks
        ADD CONSTRAINT tasks_status_check CHECK (status = ANY (ARRAY[
            'not_started'::text, 'in_progress'::text, 'done'::text,
            'blocked'::text, 'deferred'::text, 'cancelled'::text
        ]));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_tasks_project_id      ON tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id  ON tasks (parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_trello_card_id  ON tasks (trello_card_id)
    WHERE trello_card_id <> ''::text;

COMMIT;
