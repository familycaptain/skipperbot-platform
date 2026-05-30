-- Meals App — dinner log table
-- Tracks what was eaten each night for dinner.

SET search_path TO app_meals, public;

CREATE TABLE IF NOT EXISTS dinner_log (
    id          TEXT PRIMARY KEY,
    logged_date DATE NOT NULL,
    meal_id     TEXT REFERENCES meals(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    logged_by   TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    logged_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (logged_date)
);

CREATE INDEX IF NOT EXISTS idx_dinner_log_date ON dinner_log (logged_date DESC);

INSERT INTO public.entity_types (prefix, name, id_format, table_name) VALUES
    ('dl', 'Dinner Log Entry', 'dl-', 'dinner_log')
ON CONFLICT (prefix) DO NOTHING;
