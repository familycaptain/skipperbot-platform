-- Home App — Issues Tab
-- Ad-hoc defects/problems to fix (distinct from recurring maintenance tasks)

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_issues (
    id              TEXT PRIMARY KEY,           -- hi-{hex8}
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',   -- e.g. "Kitchen", "Master Bath"
    sub_location    TEXT NOT NULL DEFAULT '',   -- e.g. "Under sink", "South wall"
    category        TEXT NOT NULL DEFAULT 'General',
    severity        TEXT NOT NULL DEFAULT 'minor'
                    CHECK (severity IN ('minor', 'moderate', 'major', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'fixed')),
    date_noticed    DATE,
    date_fixed      DATE,
    fix_description TEXT NOT NULL DEFAULT '',
    cost            NUMERIC(10,2),
    notes           TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_home_issues_status   ON home_issues (status);
CREATE INDEX IF NOT EXISTS idx_home_issues_location ON home_issues (location);
CREATE INDEX IF NOT EXISTS idx_home_issues_severity ON home_issues (severity);
CREATE INDEX IF NOT EXISTS idx_home_issues_created  ON home_issues (created_at DESC);

-- Image join table (soft FK to public.images — no cross-schema constraint)
CREATE TABLE IF NOT EXISTS home_issue_images (
    image_id        TEXT NOT NULL,
    issue_id        TEXT NOT NULL REFERENCES home_issues(id) ON DELETE CASCADE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (image_id, issue_id)
);

CREATE INDEX IF NOT EXISTS idx_home_issue_images_issue ON home_issue_images (issue_id);
CREATE INDEX IF NOT EXISTS idx_home_issue_images_image ON home_issue_images (image_id);
