-- Newsletter App — Initial migration
-- Creates the app_newsletter schema and all tables.

CREATE SCHEMA IF NOT EXISTS app_newsletter;
SET search_path TO app_newsletter, public;

-- ============================================================================
-- NEWSLETTER EDITIONS (one row per daily edition)
-- ============================================================================
-- Central record for each newsletter run. Tracks the full lifecycle:
-- pending → generating → generated → sent (or error).

CREATE TABLE IF NOT EXISTS newsletter_editions (
    id              TEXT PRIMARY KEY,
    edition_date    DATE NOT NULL,

    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'generating', 'generated', 'sent', 'error')),

    -- Generated content
    title           TEXT DEFAULT '',
    content_md      TEXT DEFAULT '',    -- Full rendered markdown
    content_html    TEXT DEFAULT '',    -- Rendered HTML for email delivery
    best_bet_symbol TEXT DEFAULT '',    -- e.g. 'GLD'
    best_bet_class  TEXT DEFAULT '',    -- e.g. 'Commodities / Precious Metals'
    best_bet_reason TEXT DEFAULT '',    -- LLM-generated rationale
    regime_label    TEXT DEFAULT '',    -- e.g. 'Risk-Off with Inflation Hedge Demand'

    -- Timestamps
    generated_at    TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,

    -- Error tracking
    error_msg       TEXT DEFAULT '',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(edition_date)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_editions_date
    ON newsletter_editions(edition_date DESC);
CREATE INDEX IF NOT EXISTS idx_newsletter_editions_status
    ON newsletter_editions(status);


-- ============================================================================
-- BREADTH SNAPSHOTS (daily market breadth indicators)
-- ============================================================================
-- Fetched nightly and stored for use in newsletter generation.
-- VIX, BPNYA (NYSE Bullish Percent), NYSI (McClellan Summation Index).

CREATE TABLE IF NOT EXISTS newsletter_breadth (
    id              SERIAL PRIMARY KEY,
    snapshot_date   DATE NOT NULL,

    -- Core breadth indicators
    vix             NUMERIC(8,3),       -- CBOE Volatility Index (^VIX)
    bpnya           NUMERIC(8,3),       -- NYSE Bullish Percent 0–100 (^BPNYA)
    nysi            NUMERIC(10,2),      -- McClellan Summation Index (^NYSI)
    nymo            NUMERIC(8,3),       -- McClellan Oscillator (^NYMO) — optional

    -- Advance / Decline raw data (used to compute NYSI if ^NYSI unavailable)
    adv_issues      INTEGER,            -- NYSE advancing issues
    dec_issues      INTEGER,            -- NYSE declining issues

    -- Fetch metadata
    fetch_source    TEXT DEFAULT 'yfinance',
    fetch_error     TEXT DEFAULT '',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_breadth_date
    ON newsletter_breadth(snapshot_date DESC);


-- ============================================================================
-- MARKET SNAPSHOTS (raw market data per edition)
-- ============================================================================
-- Stores all the raw price/performance data fetched for each edition.
-- Kept as JSONB so the schema stays flexible as we add new data sources.

CREATE TABLE IF NOT EXISTS newsletter_market_snapshots (
    id              SERIAL PRIMARY KEY,
    edition_id      TEXT NOT NULL REFERENCES newsletter_editions(id),

    -- Pre-market futures data (ES, NQ, RTY, GC, CL, etc.)
    premarket_data  JSONB NOT NULL DEFAULT '{}',

    -- 30-day performance data per ticker
    performance_data JSONB NOT NULL DEFAULT '{}',

    -- Sector performance data (all 11 SPDR ETFs)
    sector_data     JSONB NOT NULL DEFAULT '{}',

    -- Market regime ratios (SPY/TLT, GLD/SPY, DBC/TLT)
    regime_data     JSONB NOT NULL DEFAULT '{}',

    -- RRG data (RS-Ratio and RS-Momentum per sector)
    rrg_data        JSONB NOT NULL DEFAULT '{}',

    -- Top movers
    movers          JSONB NOT NULL DEFAULT '[]',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_snapshots_edition
    ON newsletter_market_snapshots(edition_id);


-- ============================================================================
-- CHARTS (generated PNG files per edition)
-- ============================================================================
-- One row per chart per edition. file_path points to the PNG on disk.
-- For email delivery, charts are base64-encoded at send time from file_path.

CREATE TABLE IF NOT EXISTS newsletter_charts (
    id              SERIAL PRIMARY KEY,
    edition_id      TEXT NOT NULL REFERENCES newsletter_editions(id),

    chart_type      TEXT NOT NULL,
    -- Known types:
    --   premarket_mini_{symbol}  (e.g. premarket_mini_es, premarket_mini_gc)
    --   normalized_growth_30d
    --   market_regime
    --   sector_rrg

    file_path       TEXT NOT NULL,      -- Absolute path to PNG on disk
    width_px        INTEGER,
    height_px       INTEGER,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_charts_edition
    ON newsletter_charts(edition_id, chart_type);


-- ============================================================================
-- CONFIG (singleton settings)
-- ============================================================================

CREATE TABLE IF NOT EXISTS newsletter_config (
    id                  INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled             BOOLEAN NOT NULL DEFAULT true,

    -- Delivery
    delivery_time_et    TEXT NOT NULL DEFAULT '08:00',  -- HH:MM in ET
    email_recipients    JSONB NOT NULL DEFAULT '[]',    -- list of email strings

    -- Email service (Resend)
    from_address        TEXT NOT NULL DEFAULT 'newsletter@example.com',
    from_name           TEXT NOT NULL DEFAULT 'Morning Edge',

    -- Chart output directory
    chart_output_dir    TEXT NOT NULL DEFAULT '/tmp/newsletter_charts',

    -- Tickers to include in the portfolio performance chart
    performance_tickers JSONB NOT NULL DEFAULT '["SPY","QQQ","IWM","GLD","TLT","XLE","XLU","DBC"]',

    -- Lookback window in calendar days for the $10K chart
    performance_lookback_days INTEGER NOT NULL DEFAULT 30,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO newsletter_config (id) VALUES (1) ON CONFLICT DO NOTHING;
