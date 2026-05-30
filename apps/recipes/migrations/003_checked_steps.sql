ALTER TABLE app_recipes.recipes
    ADD COLUMN IF NOT EXISTS checked_steps INTEGER[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS checked_steps_at TIMESTAMPTZ;
