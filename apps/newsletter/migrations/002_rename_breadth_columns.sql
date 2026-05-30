-- Migration 002: Rename breadth columns to reflect what is actually stored.
--
-- bpnya  → sector_breadth_pct  (pct of 11 SPDR sector ETFs above their 50-day SMA, 0-100)
-- nysi   → sector_momentum     (sum of price/SMA20 deviations across all sectors)
-- nymo   → dropped             (McClellan Oscillator — never populated, always NULL)

SET search_path TO app_newsletter, public;

ALTER TABLE newsletter_breadth
    RENAME COLUMN bpnya TO sector_breadth_pct;

ALTER TABLE newsletter_breadth
    RENAME COLUMN nysi TO sector_momentum;

ALTER TABLE newsletter_breadth
    DROP COLUMN nymo;
