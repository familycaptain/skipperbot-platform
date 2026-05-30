-- Trello multi-account + multi-board configuration, moved out of the
-- hand-edited data/trello_boards.json into the lists app DB. Account
-- credentials (key + token) are encrypted at rest; configured through the
-- Lists app UI. Runs with search_path = app_lists, public.

CREATE TABLE IF NOT EXISTS trello_accounts (
    name        TEXT PRIMARY KEY,            -- friendly account name (e.g. "personal", "work")
    api_key     TEXT NOT NULL DEFAULT '',    -- encrypted (enc:1:...)
    api_token   TEXT NOT NULL DEFAULT '',    -- encrypted (enc:1:...)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trello_boards (
    name          TEXT PRIMARY KEY,          -- friendly board name used in tools
    account_name  TEXT NOT NULL REFERENCES trello_accounts(name) ON DELETE CASCADE,
    board_id      TEXT NOT NULL DEFAULT '',  -- Trello board id
    default_list  TEXT NOT NULL DEFAULT '',
    list_aliases  JSONB NOT NULL DEFAULT '{}',  -- {alias -> Trello list name}
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trello_boards_account ON trello_boards (account_name);
