-- Arcade — high-score board. Lives in the app_arcade schema (the migrator
-- runs with search_path = app_arcade, public, so unqualified names resolve
-- into app_arcade first). Create-only; no legacy data copy.

CREATE TABLE IF NOT EXISTS high_scores (
    id          TEXT PRIMARY KEY,            -- hs-{hex8}
    game        TEXT NOT NULL,               -- 'wardenfall' | 'aeldrift' | 'spinhazard'
    player      TEXT NOT NULL DEFAULT '',    -- canonical user name (soft ref to public.users.name)
    score       INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_high_scores_game_score
    ON high_scores (game, score DESC);
