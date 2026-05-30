-- Medical App — appointments migration
-- Adds medical_appointments table to app_medical schema.

SET LOCAL search_path TO app_medical, public;

-- ============================================================================
-- APPOINTMENTS (upcoming scheduled visits)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_appointments (
    id               TEXT PRIMARY KEY,
    member_id        TEXT NOT NULL REFERENCES medical_members(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    appointment_at   TIMESTAMPTZ NOT NULL,
    provider         TEXT DEFAULT '',
    location         TEXT DEFAULT '',
    appointment_type TEXT NOT NULL DEFAULT 'visit'
                     CHECK (appointment_type IN
                            ('visit','specialist','procedure','lab','dentist','followup','other')),
    notes            TEXT DEFAULT '',
    cancelled        BOOLEAN DEFAULT FALSE,
    notified_24h     BOOLEAN DEFAULT FALSE,
    notified_2h      BOOLEAN DEFAULT FALSE,
    created_by       TEXT DEFAULT '',
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_medical_appts_member   ON medical_appointments(member_id);
CREATE INDEX IF NOT EXISTS ix_medical_appts_at       ON medical_appointments(appointment_at DESC);
CREATE INDEX IF NOT EXISTS ix_medical_appts_upcoming ON medical_appointments(appointment_at)
    WHERE NOT cancelled;

INSERT INTO public.entity_types(prefix, name, id_format, table_name)
VALUES ('mappt', 'Medical Appointment', 'mappt-', 'medical_appointments')
ON CONFLICT (prefix) DO NOTHING;
