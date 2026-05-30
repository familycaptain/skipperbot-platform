-- Migration 007: Allow multiple meal log entries of the same type per day.
-- Removes the UNIQUE (logged_date, meal_type) constraint so you can log
-- two snacks, two lunches, etc. on the same day.

ALTER TABLE app_meals.meal_log DROP CONSTRAINT IF EXISTS meal_log_date_type_key;
