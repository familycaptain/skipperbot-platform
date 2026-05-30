-- Migration 001: Create recipe tables in app_recipes schema
-- and copy existing data from the public schema.
--
-- The migrator runs this with search_path = app_recipes, public
-- so unqualified table names resolve to app_recipes first.
-- Public tables are left intact until the app package is verified.

-- ============================================================================
-- RECIPE CATEGORIES (predefined, managed via category editor)
-- ============================================================================

CREATE TABLE recipe_categories (
    id              TEXT PRIMARY KEY,           -- cat-{hex8}
    name            TEXT NOT NULL UNIQUE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- RECIPES
-- ============================================================================

CREATE TABLE recipes (
    id                    TEXT PRIMARY KEY,           -- re-{hex8}
    title                 TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    ingredients           JSONB NOT NULL DEFAULT '[]',  -- [{item, quantity, unit}]
    steps                 JSONB NOT NULL DEFAULT '[]',  -- [string]
    prep_time_min         INTEGER,
    cook_time_min         INTEGER,
    servings              INTEGER NOT NULL DEFAULT 1,
    categories            TEXT[] NOT NULL DEFAULT '{}',  -- category names
    source_url            TEXT NOT NULL DEFAULT '',
    rating                INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
    chef_comments         TEXT NOT NULL DEFAULT '',
    notes                 TEXT NOT NULL DEFAULT '',
    checked_ingredients   INTEGER[] NOT NULL DEFAULT '{}',  -- indices of struck-through ingredients
    last_opened_at        TIMESTAMPTZ,
    created_by            TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_recipes_categories ON recipes USING GIN (categories);
CREATE INDEX idx_recipes_created_at ON recipes (created_at DESC);

-- ============================================================================
-- RECIPE–IMAGE LINKS (many-to-many)
-- image_id is a soft FK to public.images (no REFERENCES to avoid cross-schema FK)
-- ============================================================================

CREATE TABLE recipe_images (
    recipe_id       TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    image_id        TEXT NOT NULL,              -- soft FK → public.images(id)
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (recipe_id, image_id)
);

CREATE INDEX idx_recipe_images_recipe ON recipe_images (recipe_id);
CREATE INDEX idx_recipe_images_image ON recipe_images (image_id);