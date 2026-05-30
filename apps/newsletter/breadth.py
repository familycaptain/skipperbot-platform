"""Newsletter Breadth Collector

Fetches market breadth indicators and stores them in app_newsletter.newsletter_breadth.

Indicators collected (all computed from yfinance data):
  - VIX              : CBOE Volatility Index (^VIX) — direct yfinance fetch
  - Sector Breadth   : % of 11 SPDR sector ETFs above their 50-day SMA
                       Stored in `sector_breadth_pct` column (0–100 range)
  - Sector Momentum  : Sum of (price/SMA20 - 1) across all 11 sectors × 100
                       Stored in `sector_momentum` column as a -N to +N score
                       Positive = sectors accelerating above 20-day average
                       Negative = sectors decelerating below 20-day average

NOTE: ^BPNYA, ^NYSI, and ^NYMO are NOT available on Yahoo Finance (confirmed 404).
The sector-based proxies are computed from the same 11 SPDR ETFs already fetched
by the newsletter runner, so no additional API calls are needed.

Scheduled as the 'newsletter_breadth' job type, run nightly after market close
(e.g. 5:00 PM CT).
"""

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

SECTOR_ETFS = ["XLE", "XLU", "XLP", "XLF", "XLI", "XLV", "XLB", "XLRE", "XLC", "XLY", "XLK"]


def _fetch_vix() -> Optional[float]:
    """Fetch current VIX level from Yahoo Finance."""
    import yfinance as yf
    try:
        hist = yf.Ticker("^VIX").history(period="5d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 3)
    except Exception as e:
        logger.warning("BREADTH: Failed to fetch ^VIX: %s", e)
        return None


def _compute_sector_breadth() -> tuple[Optional[float], Optional[float]]:
    """Compute sector breadth and momentum from the 11 SPDR sector ETFs.

    Returns:
        (sector_breadth_pct, sector_momentum_index)

        sector_breadth_pct : % of sectors above their 50-day SMA (0–100)
        sector_momentum_index : sum of (price/SMA20 - 1) * 100 across all sectors
                                Positive = above 20-day average, Negative = below
    """
    import yfinance as yf

    above_sma50 = 0
    momentum_sum = 0.0
    counted = 0

    for ticker in SECTOR_ETFS:
        try:
            hist = yf.Ticker(ticker).history(period="90d")["Close"]
            if len(hist) < 50:
                continue
            price = float(hist.iloc[-1])
            sma50 = float(hist.tail(50).mean())
            sma20 = float(hist.tail(20).mean())

            if price > sma50:
                above_sma50 += 1
            momentum_sum += ((price / sma20) - 1.0) * 100
            counted += 1

        except Exception as e:
            logger.warning("BREADTH: Failed to fetch %s: %s", ticker, e)

    if counted == 0:
        return None, None

    breadth_pct = round((above_sma50 / counted) * 100, 2)
    momentum_idx = round(momentum_sum, 2)

    logger.debug("BREADTH: %d/%d sectors above SMA50 (%.1f%%), momentum=%.2f",
                 above_sma50, counted, breadth_pct, momentum_idx)

    return breadth_pct, momentum_idx


def collect_breadth(target_date: Optional[date] = None) -> dict:
    """Compute all breadth indicators for target_date and upsert into DB.

    Args:
        target_date: The date to store the snapshot for. Defaults to today.

    Returns:
        The upserted breadth row dict.
    """
    from apps.newsletter.data import upsert_breadth

    if target_date is None:
        target_date = date.today()

    errors = []

    vix = _fetch_vix()
    if vix is None:
        errors.append("vix=unavailable")

    sector_breadth_pct, sector_momentum = _compute_sector_breadth()
    if sector_breadth_pct is None:
        errors.append("sector_breadth=unavailable")

    fetch_error = "; ".join(errors) if errors else ""

    logger.info(
        "BREADTH: date=%s vix=%s sector_breadth=%s sector_momentum=%s errors=%s",
        target_date, vix, sector_breadth_pct, sector_momentum, fetch_error or "none",
    )

    row = upsert_breadth(
        snapshot_date=target_date,
        vix=vix,
        sector_breadth_pct=sector_breadth_pct,
        sector_momentum=sector_momentum,
        fetch_source="yfinance+computed",
        fetch_error=fetch_error,
    )

    return row or {}


def get_breadth_signal(vix: Optional[float], sector_breadth_pct: Optional[float], sector_momentum: Optional[float]) -> str:
    """Return a plain-English breadth signal summary for newsletter Section 2 prose.

    sector_breadth_pct : pct of 11 SPDR sector ETFs above their 50-day SMA (0–100)
    sector_momentum    : sum of (price/SMA20 - 1)*100 across all sectors
    """
    signals = []

    if vix is not None:
        if vix < 15:
            signals.append(f"VIX {vix:.1f} — complacent, low fear")
        elif vix < 20:
            signals.append(f"VIX {vix:.1f} — normal range")
        elif vix < 25:
            signals.append(f"VIX {vix:.1f} — elevated, caution warranted")
        else:
            signals.append(f"VIX {vix:.1f} — fear zone, defensive posture")

    if sector_breadth_pct is not None:
        if sector_breadth_pct >= 73:
            signals.append(f"Sector Breadth {sector_breadth_pct:.0f}% above SMA50 — overbought, broad participation")
        elif sector_breadth_pct >= 55:
            signals.append(f"Sector Breadth {sector_breadth_pct:.0f}% above SMA50 — healthy majority")
        elif sector_breadth_pct >= 36:
            signals.append(f"Sector Breadth {sector_breadth_pct:.0f}% above SMA50 — minority of sectors trending up")
        else:
            signals.append(f"Sector Breadth {sector_breadth_pct:.0f}% above SMA50 — very narrow, most sectors in downtrend")

    if sector_momentum is not None:
        if sector_momentum > 3:
            signals.append(f"Sector Momentum +{sector_momentum:.1f} — sectors accelerating above 20-day average")
        elif sector_momentum > 0:
            signals.append(f"Sector Momentum +{sector_momentum:.1f} — mild positive drift")
        elif sector_momentum > -3:
            signals.append(f"Sector Momentum {sector_momentum:.1f} — mild negative drift")
        else:
            signals.append(f"Sector Momentum {sector_momentum:.1f} — sectors decelerating below 20-day average")

    if not signals:
        return "Breadth data unavailable."

    return " | ".join(signals)
