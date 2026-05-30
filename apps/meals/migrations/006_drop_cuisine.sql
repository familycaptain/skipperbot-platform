-- Migration 006: Drop cuisine column from meals and drop meal_cuisines table.
-- Cuisine is now just a tag stored in meals.tags JSONB.

ALTER TABLE app_meals.meals DROP COLUMN IF EXISTS cuisine;

DROP TABLE IF EXISTS app_meals.meal_cuisines;
