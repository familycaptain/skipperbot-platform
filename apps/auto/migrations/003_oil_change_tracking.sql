-- Oil change mileage-based tracking
-- One active row per vehicle representing the current oil change cycle.

CREATE TABLE IF NOT EXISTS oil_change_tracking (
    id                  TEXT PRIMARY KEY,
    vehicle_id          TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    service_record_id   TEXT,
    date_performed      DATE NOT NULL,
    odometer_at_service INTEGER NOT NULL,
    mileage_interval    INTEGER NOT NULL DEFAULT 5000,
    next_due_mileage    INTEGER NOT NULL,
    cooldown_months     INTEGER NOT NULL DEFAULT 3,
    cooldown_expires    DATE NOT NULL,
    last_mileage_check  DATE,
    last_reported_mileage INTEGER,
    is_due              BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(vehicle_id)
);
