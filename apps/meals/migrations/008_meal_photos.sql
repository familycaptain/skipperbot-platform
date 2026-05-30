-- Meal photos join table (soft FK to public.images — no cross-schema constraint)
CREATE TABLE IF NOT EXISTS meal_photos (
    image_id    TEXT NOT NULL,
    meal_id     TEXT NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (image_id, meal_id)
);

CREATE INDEX IF NOT EXISTS idx_meal_photos_meal  ON meal_photos (meal_id);
CREATE INDEX IF NOT EXISTS idx_meal_photos_image ON meal_photos (image_id);
