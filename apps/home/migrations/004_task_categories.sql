-- Home App: Maintenance Task Categories
-- Replaces hardcoded list in HomeApp.jsx with a configurable DB table.

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_task_categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT NOT NULL DEFAULT 'slate',
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_home_task_categories_sort ON home_task_categories(sort_order, name);

-- Seed with the previously-hardcoded categories
INSERT INTO home_task_categories (id, name, color, sort_order) VALUES
    ('htcat-general',  'General',      'slate',  0),
    ('htcat-hvac',     'HVAC',         'blue',   1),
    ('htcat-plumbing', 'Plumbing',     'cyan',   2),
    ('htcat-exterior', 'Exterior',     'green',  3),
    ('htcat-electric', 'Electrical',   'orange', 4),
    ('htcat-pest',     'Pest Control', 'purple', 5)
ON CONFLICT (id) DO NOTHING;
