-- Issues App — Initial schema
-- Runs with search_path = app_issues, public

CREATE TABLE issues (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    resolution      TEXT NOT NULL DEFAULT '',
    type            TEXT NOT NULL DEFAULT 'bug',
    status          TEXT NOT NULL DEFAULT 'open',
    reported_by     TEXT NOT NULL,
    assigned_to     TEXT NOT NULL DEFAULT 'user',
    screenshots     TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_issues_reported_by ON issues(reported_by);