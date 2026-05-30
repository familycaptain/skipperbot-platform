-- Per-user Pushover opt-in. Replaces the old data/pushover_users.json file:
-- each person enables Pushover + stores their own user key (encrypted at rest)
-- through the Notifications app UI. The shared application token lives in the
-- notifications app config (app_config: pushover_app_token, encrypted).
--
-- Runs with search_path = app_notifications, public — unqualified name lands
-- in app_notifications.

CREATE TABLE IF NOT EXISTS pushover_subscriptions (
    user_id     TEXT PRIMARY KEY,            -- canonical user name (public.users.name)
    user_key    TEXT NOT NULL DEFAULT '',    -- encrypted Pushover user key (enc:1:...)
    device      TEXT NOT NULL DEFAULT '',    -- optional Pushover device name
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
