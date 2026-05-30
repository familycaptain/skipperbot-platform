-- Chores App — Initial migration
-- All tables in app_chores schema (created automatically by app loader).
-- No cross-schema foreign keys: kids.user_id and chore_completions.completed_by
-- are plain TEXT, soft references to public.users.name.

-- ============================================================================
-- KIDS
-- ============================================================================

CREATE TABLE IF NOT EXISTS kids (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    color           TEXT NOT NULL DEFAULT '#888888',
    sort_order      INT  NOT NULL DEFAULT 0,
    user_id         TEXT,                            -- soft ref to public.users.name (no FK)
    notify_morning  BOOLEAN NOT NULL DEFAULT TRUE,
    notify_evening  BOOLEAN NOT NULL DEFAULT FALSE,
    active          BOOLEAN NOT NULL DEFAULT TRUE,   -- soft-delete
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kids_sort_order ON kids (sort_order);
CREATE INDEX IF NOT EXISTS idx_kids_user_id    ON kids (user_id);

-- ============================================================================
-- ZONES (a chore "area" that rotates among an ordered set of kids)
-- ============================================================================

CREATE TABLE IF NOT EXISTS zones (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    rotation_start  DATE NOT NULL,                   -- anchor for networkdays() math
    sort_order      INT  NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- ZONE MEMBERS (ordered rotation membership)
-- ============================================================================

CREATE TABLE IF NOT EXISTS zone_members (
    zone_id   TEXT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    kid_id    TEXT NOT NULL REFERENCES kids(id)  ON DELETE RESTRICT,
    position  INT  NOT NULL,                         -- 0-based order within rotation
    PRIMARY KEY (zone_id, kid_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_zone_members_zone_pos ON zone_members(zone_id, position);

-- ============================================================================
-- CHORES (one row per zone+dow+slot)
-- ============================================================================

CREATE TABLE IF NOT EXISTS chores (
    id        TEXT PRIMARY KEY,
    zone_id   TEXT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    dow       SMALLINT NOT NULL,                     -- 0=Sun .. 6=Sat (matches Postgres extract(dow))
    position  SMALLINT NOT NULL,                     -- 0-based slot within the day
    name      TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (zone_id, dow, position)
);

CREATE INDEX IF NOT EXISTS idx_chores_zone_dow ON chores (zone_id, dow);

-- ============================================================================
-- CHORE COMPLETIONS (kid checked off a chore on a date)
-- ============================================================================

CREATE TABLE IF NOT EXISTS chore_completions (
    id            TEXT PRIMARY KEY,
    chore_id      TEXT NOT NULL REFERENCES chores(id) ON DELETE RESTRICT,
    kid_id        TEXT NOT NULL REFERENCES kids(id)   ON DELETE RESTRICT,
    chore_date    DATE NOT NULL,
    completed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_by  TEXT,                              -- soft ref to public.users.name
    status        TEXT NOT NULL DEFAULT 'done'
                  CHECK (status IN ('done', 'skipped', 'redo')),
    note          TEXT NOT NULL DEFAULT '',
    UNIQUE (chore_id, kid_id, chore_date)
);

CREATE INDEX IF NOT EXISTS idx_chore_completions_date     ON chore_completions (chore_date);
CREATE INDEX IF NOT EXISTS idx_chore_completions_kid_date ON chore_completions (kid_id, chore_date);
CREATE INDEX IF NOT EXISTS idx_chore_completions_chore    ON chore_completions (chore_id);
