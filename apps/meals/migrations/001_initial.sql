-- Meals App — initial migration
-- Creates all tables in app_meals schema.

CREATE SCHEMA IF NOT EXISTS app_meals;
SET search_path TO app_meals, public;

-- ============================================================================
-- CUISINES (managed lookup)
-- ============================================================================

CREATE TABLE IF NOT EXISTS meal_cuisines (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- TAGS (managed lookup)
-- ============================================================================

CREATE TABLE IF NOT EXISTS meal_tags (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- COMPONENTS (reusable building blocks)
-- ============================================================================

CREATE TABLE IF NOT EXISTS meal_components (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    type        TEXT NOT NULL DEFAULT 'other',
    description TEXT NOT NULL DEFAULT '',
    tags        JSONB NOT NULL DEFAULT '[]',
    recipe_id   TEXT,                          -- optional re-* recipe link
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meal_components_type ON meal_components (type);
CREATE INDEX IF NOT EXISTS idx_meal_components_tags ON meal_components USING GIN (tags);

-- ============================================================================
-- MEALS
-- ============================================================================

CREATE TABLE IF NOT EXISTS meals (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    cuisine         TEXT,
    effort          TEXT NOT NULL DEFAULT 'medium',   -- low / medium / high
    prep_time_min   INTEGER,
    cook_time_min   INTEGER,
    tags            JSONB NOT NULL DEFAULT '[]',
    notes           TEXT NOT NULL DEFAULT '',
    rating          INTEGER,                           -- 1-5 stars
    recipe_doc_id   TEXT,                              -- optional d-* document link
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meals_cuisine    ON meals (cuisine);
CREATE INDEX IF NOT EXISTS idx_meals_effort     ON meals (effort);
CREATE INDEX IF NOT EXISTS idx_meals_tags       ON meals USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_meals_created_at ON meals (created_at DESC);

-- ============================================================================
-- MEAL–COMPONENT LINKS (join table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS meal_component_links (
    id              SERIAL PRIMARY KEY,
    meal_id         TEXT NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    component_id    TEXT NOT NULL REFERENCES meal_components(id) ON DELETE RESTRICT,
    role            TEXT NOT NULL DEFAULT 'side',      -- main / side / sauce / garnish / other
    sort_order      INTEGER NOT NULL DEFAULT 0,
    notes           TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_mcl_meal      ON meal_component_links (meal_id);
CREATE INDEX IF NOT EXISTS idx_mcl_component ON meal_component_links (component_id);

-- ============================================================================
-- SEED DATA — cuisines
-- ============================================================================

INSERT INTO meal_cuisines (id, name, sort_order) VALUES
    ('mcu-00000001', 'American',       10),
    ('mcu-00000002', 'Mexican',        20),
    ('mcu-00000003', 'Italian',        30),
    ('mcu-00000004', 'Asian',          40),
    ('mcu-00000005', 'Mediterranean',  50),
    ('mcu-00000006', 'Indian',         60),
    ('mcu-00000007', 'BBQ',            70),
    ('mcu-00000008', 'Breakfast',      80),
    ('mcu-00000009', 'Other',          90)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- SEED DATA — tags
-- ============================================================================

INSERT INTO meal_tags (id, name, sort_order) VALUES
    -- Dietary
    ('mtg-00000001', 'vegetarian',   10),
    ('mtg-00000002', 'vegan',        20),
    ('mtg-00000003', 'gluten-free',  30),
    ('mtg-00000004', 'dairy-free',   40),
    -- Audience
    ('mtg-00000005', 'kid-friendly', 50),
    ('mtg-00000006', 'crowd-pleaser',60),
    -- Context
    ('mtg-00000007', 'weeknight',    70),
    ('mtg-00000008', 'weekend',      80),
    ('mtg-00000009', 'date night',   90),
    ('mtg-00000010', 'meal prep',   100),
    ('mtg-00000011', 'comfort food',110),
    ('mtg-00000012', 'healthy',     120),
    ('mtg-00000013', 'indulgent',   130),
    -- Method
    ('mtg-00000014', 'grilled',     140),
    ('mtg-00000015', 'baked',       150),
    ('mtg-00000016', 'fried',       160),
    ('mtg-00000017', 'slow-cooker', 170),
    ('mtg-00000018', 'no-cook',     180),
    ('mtg-00000019', 'spicy',       190),
    ('mtg-00000020', 'mild',        200)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- ENTITY TYPES — register prefixes in the link system
-- ============================================================================

INSERT INTO public.entity_types (prefix, name, id_format, table_name) VALUES
    ('ml',  'Meal',           'ml-',  'meals'),
    ('mc',  'Meal Component', 'mc-',  'meal_components'),
    ('mcu', 'Meal Cuisine',   'mcu-', 'meal_cuisines'),
    ('mtg', 'Meal Tag',       'mtg-', 'meal_tags')
ON CONFLICT (prefix) DO NOTHING;
