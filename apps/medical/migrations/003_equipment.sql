-- Medical App — equipment maintenance migration
-- Adds medical equipment and recurring maintenance task tables.

SET LOCAL search_path TO app_medical, public;

-- ============================================================================
-- MEDICAL EQUIPMENT (devices: CPAP, nebulizer, glucose meter, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_equipment (
    id          TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL REFERENCES medical_members(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    brand       TEXT DEFAULT '',
    model       TEXT DEFAULT '',
    serial_no   TEXT DEFAULT '',
    active      BOOLEAN DEFAULT TRUE,
    notes       TEXT DEFAULT '',
    created_by  TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_med_equip_member ON medical_equipment(member_id);
CREATE INDEX IF NOT EXISTS ix_med_equip_active ON medical_equipment(active);

-- ============================================================================
-- EQUIPMENT MAINTENANCE TASKS (per device, interval-based)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_equipment_tasks (
    id            TEXT PRIMARY KEY,
    equipment_id  TEXT NOT NULL REFERENCES medical_equipment(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    description   TEXT DEFAULT '',
    interval_days INT,                      -- null = one-time/adhoc
    last_done_at  DATE,
    next_due_at   DATE,
    active        BOOLEAN DEFAULT TRUE,
    notes         TEXT DEFAULT '',
    created_by    TEXT DEFAULT '',
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_med_equip_tasks_equip ON medical_equipment_tasks(equipment_id);
CREATE INDEX IF NOT EXISTS ix_med_equip_tasks_due   ON medical_equipment_tasks(next_due_at) WHERE active = TRUE;

-- ============================================================================
-- MAINTENANCE LOG (completion history per task)
-- ============================================================================

CREATE TABLE IF NOT EXISTS medical_equipment_log (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES medical_equipment_tasks(id) ON DELETE CASCADE,
    completed_at DATE NOT NULL DEFAULT CURRENT_DATE,
    notes        TEXT DEFAULT '',
    created_by   TEXT DEFAULT '',
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_med_equip_log_task ON medical_equipment_log(task_id, completed_at DESC);

-- ============================================================================
-- ENTITY TYPES
-- ============================================================================

INSERT INTO public.entity_types(prefix, name, id_format, table_name)
VALUES
    ('meq',  'Medical Equipment',      'meq-',  'medical_equipment'),
    ('meqt', 'Equipment Maint Task',   'meqt-', 'medical_equipment_tasks'),
    ('meql', 'Equipment Maint Log',    'meql-', 'medical_equipment_log')
ON CONFLICT (prefix) DO NOTHING;
