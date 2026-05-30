# Newsletter App Guide

The Newsletter app generates **Systematic Market Brief**.
It is a fully automated ETF and asset-class focused market-intelligence brief
covering pre-market conditions, market breadth, portfolio performance, sector
rotation, and macro research for today's tape and the next 30 days.

## Job Types

- `newsletter_breadth` — Collect VIX, BPNYA, NYSI after market close (~5 PM CT)
- `newsletter_generate` — Run the full generation pipeline (~6 AM CT)
- `newsletter_send` — Send the generated edition via email (manual or automatic)

## Pipeline Summary

1. Pre-market futures data (ES, NQ, RTY, GC, CL) via yfinance
2. 30-day $10K portfolio performance for configured tickers
3. Sector performance for all 11 SPDR ETFs
4. Market regime ratios (SPY/TLT, GLD/SPY, DBC/TLT) with HMA30
5. RRG (Relative Rotation Graph) — RS-Ratio + RS-Momentum per sector
6. Top movers identified from sector data
7. Breadth snapshot loaded from DB (collected previous evening)
8. LLM synthesis: Primary Signal, regime label, 30-Day Outlook and deep-dive prose
9. Markdown assembled, stored in DB

## Key Tables (app_newsletter schema)

- `newsletter_editions` — one row per day; content_md holds the full document
- `newsletter_breadth` — nightly VIX / BPNYA / NYSI snapshots
- `newsletter_market_snapshots` — raw JSONB data per edition
- `newsletter_charts` — generated PNG file paths per edition
- `newsletter_config` — singleton settings (recipients, tickers, delivery time, product identity, disclosures)

## Email Delivery

Uses **Resend** (resend.com). Set `RESEND_API_KEY` in .env.
Charts are base64 inline CID attachments — no external image hosting required.
Configure `email_recipients` in newsletter_config to set delivery addresses.

## Adding Recipients

```sql
UPDATE app_newsletter.newsletter_config
SET email_recipients = '["you@example.com"]'::jsonb
WHERE id = 1;
```

## Triggering Manually

```python
from apps.newsletter.runner import run_newsletter_pipeline
from datetime import date
result = run_newsletter_pipeline(edition_date=date.today())
```

To run the full generate-and-email flow from the command line, use:

```bash
python apps/newsletter/scripts/run_now.py
python apps/newsletter/scripts/run_now.py --date 2026-04-25
```

## Chart Generation Status

Chart generation (`apps/newsletter/charts.py`) is stubbed in the runner.
The pipeline will complete without charts. Implement `generate_all_charts()`
as the next phase using `mplfinance` (mini candle charts) and `matplotlib`
(normalized growth, regime ratios, RRG scatter).
