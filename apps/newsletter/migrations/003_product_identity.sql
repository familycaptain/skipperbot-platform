-- Newsletter App - Product identity and disclosure config
-- Rebrands the product as Systematic Market Brief and adds configurable
-- identity/disclosure fields for fully automated delivery.

SET search_path TO app_newsletter, public;

ALTER TABLE newsletter_config
    ADD COLUMN IF NOT EXISTS product_name TEXT,
    ADD COLUMN IF NOT EXISTS product_tagline TEXT,
    ADD COLUMN IF NOT EXISTS disclosure_short TEXT,
    ADD COLUMN IF NOT EXISTS disclosure_long TEXT,
    ADD COLUMN IF NOT EXISTS primary_signal_label TEXT,
    ADD COLUMN IF NOT EXISTS outlook_label TEXT;

ALTER TABLE newsletter_config
    ALTER COLUMN from_name SET DEFAULT 'Systematic Market Brief';

UPDATE newsletter_config
SET
    product_name = COALESCE(NULLIF(product_name, ''), 'Systematic Market Brief'),
    product_tagline = COALESCE(
        NULLIF(product_tagline, ''),
        'Automated market intelligence for today''s tape and the next 30 days.'
    ),
    disclosure_short = COALESCE(
        NULLIF(disclosure_short, ''),
        'Fully AI-generated market intelligence. Published automatically without human review. Not financial advice.'
    ),
    disclosure_long = COALESCE(
        NULLIF(disclosure_long, ''),
        'Systematic Market Brief is fully AI-generated and published automatically without human review before delivery. Verify important facts independently before acting. Not financial advice.'
    ),
    primary_signal_label = COALESCE(NULLIF(primary_signal_label, ''), 'Primary Signal'),
    outlook_label = COALESCE(NULLIF(outlook_label, ''), '30-Day Outlook'),
    from_name = CASE
        WHEN from_name IS NULL OR from_name = '' OR from_name = 'Morning Edge'
            THEN 'Systematic Market Brief'
        ELSE from_name
    END,
    updated_at = now()
WHERE id = 1;

ALTER TABLE newsletter_config
    ALTER COLUMN product_name SET DEFAULT 'Systematic Market Brief',
    ALTER COLUMN product_tagline SET DEFAULT 'Automated market intelligence for today''s tape and the next 30 days.',
    ALTER COLUMN disclosure_short SET DEFAULT 'Fully AI-generated market intelligence. Published automatically without human review. Not financial advice.',
    ALTER COLUMN disclosure_long SET DEFAULT 'Systematic Market Brief is fully AI-generated and published automatically without human review before delivery. Verify important facts independently before acting. Not financial advice.',
    ALTER COLUMN primary_signal_label SET DEFAULT 'Primary Signal',
    ALTER COLUMN outlook_label SET DEFAULT '30-Day Outlook';

ALTER TABLE newsletter_config
    ALTER COLUMN product_name SET NOT NULL,
    ALTER COLUMN product_tagline SET NOT NULL,
    ALTER COLUMN disclosure_short SET NOT NULL,
    ALTER COLUMN disclosure_long SET NOT NULL,
    ALTER COLUMN primary_signal_label SET NOT NULL,
    ALTER COLUMN outlook_label SET NOT NULL;
