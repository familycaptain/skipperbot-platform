-- Medical App — initial migration
-- Creates all medical tracking tables in app_medical schema.

SET LOCAL search_path TO app_medical, public;

-- ============================================================================
-- FAMILY MEMBERS
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_members (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    notes       TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- MEDICATIONS (prescriptions + refill tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_medications (
    id              TEXT PRIMARY KEY,
    member_id       TEXT NOT NULL REFERENCES medical_members(id),
    name            TEXT NOT NULL,
    dosage_notes    TEXT DEFAULT '',
    prescriber      TEXT DEFAULT '',
    pharmacy        TEXT DEFAULT '',
    start_date      DATE,
    end_date        DATE,
    active          BOOLEAN DEFAULT TRUE,
    last_dose_date  DATE,
    duration_days   INT,
    reminder_days   INT NOT NULL DEFAULT 7,
    refill_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (refill_status IN ('active','nagging','ordered','filled')),
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_medical_meds_member  ON medical_medications(member_id);
CREATE INDEX IF NOT EXISTS ix_medical_meds_due     ON medical_medications(last_dose_date) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS ix_medical_meds_status  ON medical_medications(refill_status) WHERE active = TRUE;

-- ============================================================================
-- MEDICAL EVENTS (journal: visits, surgeries, labs, notes, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_events (
    id              TEXT PRIMARY KEY,
    member_id       TEXT NOT NULL REFERENCES medical_members(id),
    event_type      TEXT NOT NULL DEFAULT 'visit'
                    CHECK (event_type IN ('visit','surgery','procedure','lab','note','emergency')),
    title           TEXT NOT NULL,
    event_date      DATE NOT NULL,
    provider        TEXT DEFAULT '',
    summary         TEXT DEFAULT '',
    follow_up_date  DATE,
    follow_up_notes TEXT DEFAULT '',
    tags            TEXT[] DEFAULT '{}',
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_medical_events_member ON medical_events(member_id);
CREATE INDEX IF NOT EXISTS ix_medical_events_date   ON medical_events(event_date DESC);
CREATE INDEX IF NOT EXISTS ix_medical_events_type   ON medical_events(event_type);

-- ============================================================================
-- TREATMENTS (recurring procedures: injections, infusions, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_treatments (
    id              TEXT PRIMARY KEY,
    member_id       TEXT NOT NULL REFERENCES medical_members(id),
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    interval_days   INT NOT NULL,
    last_done_at    DATE,
    next_due_at     DATE,
    active          BOOLEAN DEFAULT TRUE,
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS medical_treatment_log (
    id              TEXT PRIMARY KEY,
    treatment_id    TEXT NOT NULL REFERENCES medical_treatments(id) ON DELETE CASCADE,
    done_at         DATE NOT NULL DEFAULT CURRENT_DATE,
    medication      TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    created_by      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_medical_treatments_member ON medical_treatments(member_id);
CREATE INDEX IF NOT EXISTS ix_medical_treatments_due    ON medical_treatments(next_due_at) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS ix_medical_treatment_log     ON medical_treatment_log(treatment_id, done_at DESC);

-- ============================================================================
-- LAB TESTS (master list)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_lab_tests (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    unit        TEXT DEFAULT '',
    normal_min  NUMERIC,
    normal_max  NUMERIC,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    notes       TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- LAB RESULTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_lab_results (
    id          TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL REFERENCES medical_members(id),
    event_id    TEXT REFERENCES medical_events(id) ON DELETE SET NULL,
    lab_test_id TEXT NOT NULL REFERENCES medical_lab_tests(id),
    result_date DATE NOT NULL,
    value       NUMERIC NOT NULL,
    notes       TEXT DEFAULT '',
    created_by  TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_medical_lab_results_member ON medical_lab_results(member_id, result_date DESC);
CREATE INDEX IF NOT EXISTS ix_medical_lab_results_test   ON medical_lab_results(lab_test_id, result_date DESC);
CREATE INDEX IF NOT EXISTS ix_medical_lab_results_event  ON medical_lab_results(event_id) WHERE event_id IS NOT NULL;
