-- Home App — Appliances Tab
-- Household appliances with purchase/warranty tracking (records, not tasks)

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_appliances (
    id              TEXT PRIMARY KEY,           -- ha-{hex8}
    name            TEXT NOT NULL,
    appliance_type  TEXT NOT NULL DEFAULT 'General',   -- e.g. "Refrigerator", "Dishwasher"
    brand           TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    serial_number   TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',   -- free text, e.g. "Kitchen", "Garage"
    purchase_date   DATE,
    purchase_price  NUMERIC(10,2),
    warranty_expires DATE,
    notes           TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_home_appliances_type     ON home_appliances (appliance_type);
CREATE INDEX IF NOT EXISTS idx_home_appliances_location ON home_appliances (location);
CREATE INDEX IF NOT EXISTS idx_home_appliances_warranty ON home_appliances (warranty_expires);
CREATE INDEX IF NOT EXISTS idx_home_appliances_created  ON home_appliances (created_at DESC);

-- Image join table (soft FK to public.images — no cross-schema constraint)
CREATE TABLE IF NOT EXISTS home_appliance_images (
    image_id        TEXT NOT NULL,
    appliance_id    TEXT NOT NULL REFERENCES home_appliances(id) ON DELETE CASCADE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (image_id, appliance_id)
);

CREATE INDEX IF NOT EXISTS idx_home_appliance_images_appliance ON home_appliance_images (appliance_id);
CREATE INDEX IF NOT EXISTS idx_home_appliance_images_image     ON home_appliance_images (image_id);
