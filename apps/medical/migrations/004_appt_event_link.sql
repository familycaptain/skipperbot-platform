-- Link medical events back to the appointment they document.
-- Also adds an index for fast "which appointments have no event?" queries.

SET LOCAL search_path TO app_medical, public;

ALTER TABLE medical_events
    ADD COLUMN IF NOT EXISTS appointment_id TEXT
        REFERENCES medical_appointments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_medical_events_appt
    ON medical_events(appointment_id)
    WHERE appointment_id IS NOT NULL;
