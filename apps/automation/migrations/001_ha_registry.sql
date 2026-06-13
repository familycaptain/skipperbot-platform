-- Home Assistant device + entity-alias registry for the automation app.
--
-- Replaces the on-disk apps/automation/devices.json and aliases.json caches so
-- per-install home data lives in the app_automation schema, never on the
-- filesystem (where it risked being committed to source control).
--
-- The migrator runs this with search_path = app_automation, public, so the
-- unqualified table names land in app_automation.

BEGIN;

-- Device registry snapshot + hand-curated friendly aliases (was devices.json).
-- device_id is Home Assistant's stable device id; aliases is a JSON array of
-- normalized friendly names ("kitchen lamp", "tv").
CREATE TABLE IF NOT EXISTS ha_devices (
    device_id    text PRIMARY KEY,
    name         text NOT NULL DEFAULT '',
    manufacturer text NOT NULL DEFAULT '',
    model        text NOT NULL DEFAULT '',
    aliases      jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Entity-level aliases the user trains via chat (was aliases.json):
-- "tv" -> media_player.lg_webos_tv...  Keyed by the normalized alias.
CREATE TABLE IF NOT EXISTS ha_aliases (
    alias      text PRIMARY KEY,
    entity_id  text NOT NULL,
    notes      text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
