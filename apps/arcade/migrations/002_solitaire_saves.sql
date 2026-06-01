-- Arcade — per-user saved Solitaire (Klondike) games. Lives in app_arcade
-- (the migrator runs with search_path = app_arcade, public). One in-progress
-- game per user; saving overwrites, finishing/abandoning clears.

CREATE TABLE IF NOT EXISTS solitaire_saves (
    player      TEXT PRIMARY KEY,            -- canonical user name (soft ref to public.users.name)
    state       JSONB NOT NULL,              -- serialized game state (stock/waste/foundations/tableau/moves)
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
