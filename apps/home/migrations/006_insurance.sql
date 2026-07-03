-- Home App — Insurance Tab
-- Insurance policies with coverage/premium/renewal tracking (records, not tasks)

SET LOCAL search_path TO app_home, public;

CREATE TABLE IF NOT EXISTS home_insurance_policies (
    id              TEXT PRIMARY KEY,           -- hip-{hex8}
    provider        TEXT NOT NULL,
    policy_number   TEXT NOT NULL DEFAULT '',
    policy_type     TEXT NOT NULL DEFAULT 'Home',   -- e.g. "Home", "Auto", "Life"
    coverage_amount NUMERIC(12,2),
    premium         NUMERIC(10,2),
    premium_period  TEXT NOT NULL DEFAULT 'annual',  -- annual/semiannual/quarterly/monthly
    deductible      NUMERIC(10,2),
    renewal_date    DATE,
    insured_assets  TEXT NOT NULL DEFAULT '',   -- free text: what the policy covers
    notes           TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_home_insurance_policies_type    ON home_insurance_policies (policy_type);
CREATE INDEX IF NOT EXISTS idx_home_insurance_policies_renewal ON home_insurance_policies (renewal_date);
CREATE INDEX IF NOT EXISTS idx_home_insurance_policies_created ON home_insurance_policies (created_at DESC);

-- Image join table (soft FK to public.images — no cross-schema constraint)
CREATE TABLE IF NOT EXISTS home_insurance_policy_images (
    image_id        TEXT NOT NULL,
    policy_id       TEXT NOT NULL REFERENCES home_insurance_policies(id) ON DELETE CASCADE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (image_id, policy_id)
);

CREATE INDEX IF NOT EXISTS idx_home_insurance_policy_images_policy ON home_insurance_policy_images (policy_id);
CREATE INDEX IF NOT EXISTS idx_home_insurance_policy_images_image  ON home_insurance_policy_images (image_id);
