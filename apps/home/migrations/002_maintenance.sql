-- Home App Maintenance Tab
-- Routine recurring and ad-hoc maintenance tasks with completion log

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_tasks (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    category        TEXT DEFAULT 'General',
    task_type       TEXT NOT NULL DEFAULT 'recurring'
                        CHECK (task_type IN ('recurring', 'adhoc')),
    interval_days   INT,                        -- null for adhoc; e.g. 90 = quarterly
    last_done_at    DATE,                       -- null until first completion
    next_due_at     DATE,                       -- set on create; recalculated on complete
    active          BOOLEAN DEFAULT TRUE,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_home_tasks_active   ON home_tasks(active);
CREATE INDEX IF NOT EXISTS ix_home_tasks_due      ON home_tasks(next_due_at) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS ix_home_tasks_category ON home_tasks(category);

CREATE TABLE IF NOT EXISTS home_task_log (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES home_tasks(id) ON DELETE CASCADE,
    completed_at    DATE NOT NULL DEFAULT CURRENT_DATE,
    completed_by    TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_home_task_log_task ON home_task_log(task_id, completed_at DESC);
