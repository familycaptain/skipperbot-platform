-- Meals App — rename dinner_log → meal_log, add meal_type column
-- Add lunch/dinner/any meal occasion tags

SET search_path TO app_meals, public;

-- Rename table (safe: created today, no data yet)
ALTER TABLE IF EXISTS dinner_log RENAME TO meal_log;

-- Add meal_type column: dinner | lunch
ALTER TABLE meal_log
    ADD COLUMN IF NOT EXISTS meal_type TEXT NOT NULL DEFAULT 'dinner';

CREATE INDEX IF NOT EXISTS idx_meal_log_type ON meal_log (meal_type);
CREATE INDEX IF NOT EXISTS idx_meal_log_date_type ON meal_log (logged_date, meal_type);

-- Drop the old unique constraint on logged_date (one dinner per day)
-- and replace with unique on (logged_date, meal_type) — one lunch AND one dinner per day
ALTER TABLE meal_log DROP CONSTRAINT IF EXISTS dinner_log_logged_date_key;
ALTER TABLE meal_log ADD CONSTRAINT meal_log_date_type_key UNIQUE (logged_date, meal_type);

-- Update entity_type registry
UPDATE public.entity_types
    SET name = 'Meal Log Entry', table_name = 'meal_log'
    WHERE prefix = 'dl';

-- Seed meal occasion tags
INSERT INTO meal_tags (id, name, sort_order) VALUES
    ('mtg-00000021', 'dinner',    210),
    ('mtg-00000022', 'lunch',     220),
    ('mtg-00000023', 'breakfast', 230),
    ('mtg-00000024', 'snack',     240),
    ('mtg-00000025', 'any meal',  250)
ON CONFLICT (name) DO NOTHING;
