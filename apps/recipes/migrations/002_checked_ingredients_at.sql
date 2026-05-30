-- Add checked_ingredients_at to track when ingredients were last checked off
-- Used by the UI to auto-reset checked state after 24 hours of inactivity.

SET search_path TO app_recipes, public;

ALTER TABLE recipes
  ADD COLUMN IF NOT EXISTS checked_ingredients_at TIMESTAMPTZ;
