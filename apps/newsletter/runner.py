"""Newsletter Generation Pipeline

Orchestrates the full Systematic Market Brief generation for a given date.

Pipeline steps:
  1.  Load config + create/get edition record
  2.  Fetch pre-market futures data (ES, NQ, RTY, GC, CL)
  3.  Fetch 30-day performance data for portfolio tickers
  4.  Fetch sector performance data (11 SPDR ETFs)
  5.  Fetch market regime ratio data (SPY/TLT, GLD/SPY, DBC/TLT with HMA30)
  6.  Compute RRG data (RS-Ratio, RS-Momentum per sector ETF)
  7.  Identify top movers with 1-day returns
  8.  Load breadth snapshot (VIX, sector_breadth_pct, sector_momentum) from DB
  9.  Generate charts (mini candles, $10K line, regime ratios, RRG)
  10. Run LLM synthesis (Primary Signal, Market Regime label, Deep Dive prose)
  11. Assemble full market brief markdown
  12. Render HTML for email
  13. Save everything to DB, mark edition as 'generated'
"""

import logging
import math
import os
import re
import time
from datetime import date, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PRODUCT_NAME = "Systematic Market Brief"
DEFAULT_PRODUCT_TAGLINE = "Automated market intelligence for today's tape and the next 30 days."
DEFAULT_DISCLOSURE_SHORT = (
    "Fully AI-generated market intelligence. Published automatically without human review. "
    "Not financial advice."
)
DEFAULT_DISCLOSURE_LONG = (
    "Systematic Market Brief is fully AI-generated and published automatically without human review "
    "before delivery. Verify important facts independently before acting. Not financial advice."
)
DEFAULT_PRIMARY_SIGNAL_LABEL = "Primary Signal"
DEFAULT_OUTLOOK_LABEL = "30-Day Outlook"

FUTURES_SYMBOLS = {
    "ES=F": {"name": "S&P 500 Futures",     "currency": "pts"},
    "NQ=F": {"name": "Nasdaq 100 Futures",   "currency": "pts"},
    "RTY=F":{"name": "Russell 2000 Futures", "currency": "pts"},
    "GC=F": {"name": "Gold Futures",         "currency": "$"},
    "CL=F": {"name": "Crude Oil Futures",    "currency": "$"},
    "SI=F": {"name": "Silver Futures",       "currency": "$"},
    "ZB=F":  {"name": "30-Yr Bond Futures",   "currency": "pts"},
    "BTC-USD": {"name": "Bitcoin",            "currency": "$"},
}

SECTOR_ETFS = ["XLE", "XLU", "XLP", "XLF", "XLI", "XLV", "XLB", "XLRE", "XLC", "XLY", "XLK"]

# Writing style injected into every LLM section prompt.
_PROSE_STYLE = (
    "\n\nWRITING STYLE: Write like you are explaining this to a smart working adult who does NOT have a "
    "finance degree. Use plain, everyday language - short sentences, no Wall Street jargon unless necessary. "
    "When you do use a finance term (e.g. 'hawkish', 'dovish', 'yield curve', 'spread'), immediately explain "
    "it in plain English in parentheses, like: hawkish (meaning the Fed wants to keep rates high to fight "
    "inflation). Include real numbers and percentages, but always say what they mean in practice - for example, "
    "don't just say 'up 0.4%', say 'up 0.4%, which means stocks edged slightly higher'. "
    "Write in a clear, practical voice, not a professor lecturing a class. "
    "Don't assume that the reader will understand the implications of a piece of information. Don't make the reader "
    "think; think for them by just explaining so they don't have to think as much.  "
    "In general, get to the point and focus on the most relevant, recent, and impactful things you can say. "
    "Do NOT use em-dashes inside written paragraphs or sentences. Use a comma, period, or rewrite the sentence instead. "
    "VOICE: Write as a transparent automated market intelligence system. Do NOT pretend to be a human author, "
    "editor, analyst, or reviewer. Do NOT use first-person editorial claims such as 'I think', 'we believe', "
    "'our editorial view', or 'after reviewing the research'. Present conclusions directly and clearly. "
    "Do NOT reference the research process with phrases like 'your summaries', 'the sources provided', 'the data given', "
    "'based on the information provided', or anything that exposes an internal pipeline. "
    "However, DO cite real, named external sources when attributing specific facts, for example: "
    "'according to Bloomberg', 'per the AAII survey', 'the Fed said', 'Goldman Sachs noted'. "
    "That kind of attribution is good journalism and should be kept."
)
REGIME_RATIOS = [
    ("SPY", "TLT", "SPY/TLT"),
    ("GLD", "SPY", "GLD/SPY"),
    ("DBC", "TLT", "DBC/TLT"),
]


def _get_product_config(raw_cfg: dict | None) -> dict:
    """Return normalized product identity and disclosure settings."""

    cfg = raw_cfg or {}

    def _value(key: str, default: str) -> str:
        value = cfg.get(key)
        if isinstance(value, str):
            value = value.strip()
        return value or default

    product_name = _value("product_name", DEFAULT_PRODUCT_NAME)
    return {
        "product_name": product_name,
        "product_tagline": _value("product_tagline", DEFAULT_PRODUCT_TAGLINE),
        "disclosure_short": _value("disclosure_short", DEFAULT_DISCLOSURE_SHORT),
        "disclosure_long": _value("disclosure_long", DEFAULT_DISCLOSURE_LONG),
        "primary_signal_label": _value("primary_signal_label", DEFAULT_PRIMARY_SIGNAL_LABEL),
        "outlook_label": _value("outlook_label", DEFAULT_OUTLOOK_LABEL),
        "from_name": _value("from_name", product_name),
    }


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

def _fetch_premarket_data(symbols: list[str]) -> dict:
    """Fetch pre-market price + % change vs prior close for futures symbols.

    Uses yfinance with prepost=True on 5m interval.  Anchors the prev_close to
    the last regular-session bar (hour < 16 ET) on the most recent prior trading
    day so the dotted line aligns with that candle's close.  Fetches 5 days of
    history so Monday correctly anchors to Friday's 15:55 ET bar.

    Returns dict keyed by symbol with: price, prev_close, pct_change, candles.
    """
    import yfinance as yf
    import pandas as pd

    result = {}
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d", interval="5m", prepost=True)

            if hist.empty:
                continue

            # Ensure timezone-aware Eastern time
            if hist.index.tz is None:
                hist.index = hist.index.tz_localize("America/New_York")
            else:
                hist.index = hist.index.tz_convert("America/New_York")

            now_et = pd.Timestamp.now(tz="America/New_York")
            today_date = now_et.date()

            # Find anchor bar: last regular-session bar (hour < 16 ET) before today.
            # This gives the 15:55 ET bar from the most recent prior trading day,
            # including Friday when running on Monday.
            prior_bars = hist[hist.index.date < today_date]
            session_bars = prior_bars[prior_bars.index.hour < 16]

            if session_bars.empty:
                # Fallback: use whatever the last prior bar was
                if prior_bars.empty:
                    continue
                anchor_bar = prior_bars.iloc[-1]
            else:
                anchor_bar = session_bars.iloc[-1]

            prev_close = float(anchor_bar["Close"])
            anchor_ts = anchor_bar.name  # timestamp of the 15:55 ET close bar

            # Candles from that anchor bar forward (inclusive) — gives overnight + premarket
            candles_df = hist[hist.index >= anchor_ts]
            current_price = float(candles_df["Close"].iloc[-1]) if not candles_df.empty else prev_close

            candles = [
                {
                    "t": str(idx),
                    "o": float(row["Open"]),
                    "h": float(row["High"]),
                    "l": float(row["Low"]),
                    "c": float(row["Close"]),
                }
                for idx, row in candles_df.iterrows()
            ]

            pct_change = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0.0

            result[symbol] = {
                "symbol": symbol,
                "name": FUTURES_SYMBOLS.get(symbol, {}).get("name", symbol),
                "price": round(current_price, 2),
                "prev_close": round(prev_close, 2),
                "pct_change": round(pct_change, 4),
                "candles": candles,
            }

        except Exception as e:
            logger.warning("RUNNER: Failed to fetch premarket %s: %s", symbol, e)

    return result


def _fetch_performance_data(tickers: list[str], lookback_days: int) -> dict:
    """Fetch daily close prices for each ticker over the lookback window.

    Returns dict keyed by ticker with: closes (list of {date, close}),
    start_price, current_price, pct_change, value_10k.
    """
    import yfinance as yf

    start_date = date.today() - timedelta(days=lookback_days + 5)
    result = {}

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(start=str(start_date))
            if hist.empty or len(hist) < 2:
                continue

            hist = hist.tail(lookback_days).dropna(subset=["Close"])
            if len(hist) < 2:
                continue
            start_price = float(hist["Close"].iloc[0])
            current_price = float(hist["Close"].iloc[-1])
            if not (start_price and start_price == start_price and current_price == current_price):
                continue
            pct_change = ((current_price - start_price) / start_price) * 100

            closes = [
                {"date": str(idx.date()), "close": float(row["Close"])}
                for idx, row in hist.iterrows()
            ]

            result[ticker] = {
                "ticker": ticker,
                "start_price": round(start_price, 4),
                "current_price": round(current_price, 4),
                "pct_change": round(pct_change, 4),
                "value_10k": round(10000 * (current_price / start_price), 2),
                "closes": closes,
            }
        except Exception as e:
            logger.warning("RUNNER: Failed to fetch performance %s: %s", ticker, e)

    return result


def _fetch_sector_data(etfs: list[str]) -> dict:
    """Fetch 1-week return for each sector ETF plus SMA20 status."""
    import yfinance as yf

    result = {}
    for ticker in etfs:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="60d")
            if hist.empty or len(hist) < 6:
                continue

            week_ago_price = float(hist["Close"].iloc[-6])
            current_price = float(hist["Close"].iloc[-1])
            week_return = ((current_price - week_ago_price) / week_ago_price) * 100

            sma20 = hist["Close"].tail(20).mean()
            above_sma20 = bool(current_price > sma20)

            result[ticker] = {
                "ticker": ticker,
                "price": round(current_price, 2),
                "week_return": round(week_return, 4),
                "sma20": round(float(sma20), 2),
                "above_sma20": above_sma20,
            }
        except Exception as e:
            logger.warning("RUNNER: Failed to fetch sector %s: %s", ticker, e)

    return result


_NEWSLETTER_ETF_NAMES = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000",
    "GLD": "Gold", "TLT": "20+ Yr Treasury", "DBC": "Broad Commodities",
    "XLE": "Energy", "XLU": "Utilities", "XLP": "Consumer Staples",
    "XLF": "Financials", "XLI": "Industrials", "XLV": "Healthcare",
    "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Svcs",
    "XLY": "Consumer Discretionary", "XLK": "Technology",
}


def _fetch_symbol_news(symbols: list[str], lookback_days: int = 3) -> dict:
    """Fetch Finnhub company news for each symbol and distill per-symbol via LLM.

    Returns {ticker: "1-paragraph summary"} for any symbol that has recent news.
    Gracefully returns empty dict if FINNHUB_API_KEY is not set or on any error.
    """
    import os
    import requests as _req
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from config import openai_client, SMART_MODEL, TIMEZONE

    _tz = ZoneInfo(TIMEZONE)

    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        logger.warning("RUNNER: FINNHUB_API_KEY not set — skipping per-symbol news")
        return {}, {}

    to_date = datetime.utcnow().strftime("%Y-%m-%d")
    from_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    raw_by_symbol: dict[str, list] = {}
    logger.info("RUNNER: Fetching Finnhub symbol news for %d tickers (%s → %s)",
                len(symbols), from_date, to_date)

    for sym in sorted(set(symbols)):
        try:
            url = (
                f"https://finnhub.io/api/v1/company-news"
                f"?symbol={sym}&from={from_date}&to={to_date}&token={key}"
            )
            resp = _req.get(url, timeout=10)
            resp.raise_for_status()
            articles = resp.json()
            if not isinstance(articles, list):
                articles = []
            articles = articles[:10]
            headlines = []
            for a in articles:
                ts = a.get("datetime", 0)
                time_str = datetime.fromtimestamp(ts, _tz).strftime("%Y-%m-%d %H:%M") if ts else ""
                headlines.append({
                    "headline": a.get("headline", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "time": time_str,
                    "summary": (a.get("summary") or "")[:800],
                })
            raw_by_symbol[sym] = headlines
            if headlines:
                logger.info("RUNNER: Symbol news %s — %d articles", sym, len(headlines))
            time.sleep(0.2)
        except Exception as e:
            logger.warning("RUNNER: Symbol news fetch failed for %s: %s", sym, e)

    result: dict[str, str] = {}
    symbols_with_news = [s for s, h in raw_by_symbol.items() if h]
    logger.info("RUNNER: Distilling per-symbol news for %d symbols", len(symbols_with_news))

    for sym in symbols_with_news:
        headlines = raw_by_symbol[sym]
        etf_name = _NEWSLETTER_ETF_NAMES.get(sym, sym)
        sym_lines = [f"{sym} — {etf_name} ({len(headlines)} articles):"]
        for h in headlines:
            sym_lines.append(f"  [{h['time']}] {h['source']}: {h['headline']}")
            if h.get("summary"):
                sym_lines.append(f"    {h['summary']}")
        sym_text = "\n".join(sym_lines)
        try:
            sr = openai_client.chat.completions.create(
                model=SMART_MODEL,
                messages=[
                    {"role": "system", "content": (
                        "You are generating a per-ETF news digest for an automated market intelligence brief.\n\n"
                        "Write a SHORT PARAGRAPH (3-5 sentences) covering:\n"
                        "• What happened: the key developments from the news\n"
                        "• Why it matters: how this affects the ETF's sector or theme\n"
                        "• Signal: bullish, bearish, or neutral and why\n\n"
                        "Be concrete — name events, data releases, or sector dynamics. "
                        "Keep it under 120 words. Output ONLY the paragraph. "
                        "If the news is only generic spam with no market relevance, reply: SKIP"
                    )},
                    {"role": "user", "content": (
                        f"News for {sym} ({etf_name}), {from_date} to {to_date}:\n\n{sym_text}"
                    )},
                ],
                max_completion_tokens=300,
                temperature=0.2,
            )
            content = (sr.choices[0].message.content or "").strip()
            if content and content.upper() != "SKIP":
                result[sym] = content
                logger.info("RUNNER: Symbol news %s distilled (%d chars)", sym, len(content))
        except Exception as e:
            logger.warning("RUNNER: Symbol news LLM failed for %s: %s", sym, e)
            if headlines:
                result[sym] = headlines[0]["headline"]

    logger.info("RUNNER: Per-symbol news complete — %d/%d symbols have summaries",
                len(result), len(symbols_with_news))
    return result, raw_by_symbol


def _compute_hma(series, period: int):
    """Compute Hull Moving Average (HMA) for a pandas Series.

    HMA(n) = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
    """
    import math
    import pandas as pd

    half = period // 2
    sqrt_n = int(math.sqrt(period))

    def wma(s, p):
        weights = list(range(1, p + 1))
        return s.rolling(p).apply(
            lambda x: sum(w * v for w, v in zip(weights, x)) / sum(weights),
            raw=True,
        )

    wma_half = wma(series, half)
    wma_full = wma(series, period)
    diff = 2 * wma_half - wma_full
    return wma(diff, sqrt_n)


def _fetch_regime_data(ratios: list[tuple], hma_period: int = 30) -> dict:
    """Fetch price ratio data with HMA for regime analysis.

    ratios: list of (numerator_ticker, denominator_ticker, label)
    Returns dict keyed by label with ratio closes and HMA values.
    """
    import yfinance as yf
    import pandas as pd

    result = {}
    for num, den, label in ratios:
        try:
            df_num = yf.Ticker(num).history(period="180d")["Close"]
            df_den = yf.Ticker(den).history(period="180d")["Close"]

            df = pd.DataFrame({"num": df_num, "den": df_den}).dropna()
            if df.empty or len(df) < hma_period + 10:
                continue

            df["ratio"] = df["num"] / df["den"]
            df["hma"] = _compute_hma(df["ratio"], hma_period)

            tail = df.tail(90)
            current_ratio = float(df["ratio"].iloc[-1])
            hma_current = float(df["hma"].iloc[-1]) if not df["hma"].isna().all() else None
            # Trend: ratio above HMA30 = up (bullish), below = down (bearish)
            trend = "up" if (hma_current is not None and current_ratio > hma_current) else "down"

            result[label] = {
                "label": label,
                "numerator": num,
                "denominator": den,
                "current_ratio": round(current_ratio, 6),
                "hma_current": round(hma_current, 6) if hma_current is not None else None,
                "trend": trend,
                "closes": [
                    {"date": str(idx.date()), "ratio": round(float(row["ratio"]), 6),
                     "hma": round(float(row["hma"]), 6) if not pd.isna(row["hma"]) else None}
                    for idx, row in tail.iterrows()
                ],
            }
        except Exception as e:
            logger.warning("RUNNER: Failed to fetch regime ratio %s: %s", label, e)

    return result


def _compute_rrg_data(sector_etfs: list[str], benchmark: str = "SPY", period: int = 14) -> dict:
    """Compute JdK RS-Ratio and RS-Momentum for each sector ETF vs benchmark.

    Algorithm (simplified JdK methodology):
      1. Compute relative strength: RS = ETF_close / benchmark_close
      2. Normalize to 100 at start of period
      3. RS-Ratio = 14-day EMA of normalized RS, then rescaled to 100 center
      4. RS-Momentum = rate of change of RS-Ratio

    Uses daily bars. Tail = last 5 trading days (1 week of history).
    """
    import yfinance as yf
    import pandas as pd

    result = {}
    try:
        benchmark_hist = yf.Ticker(benchmark).history(period="1y")["Close"]
    except Exception as e:
        logger.warning("RUNNER: Failed to fetch RRG benchmark %s: %s", benchmark, e)
        return result

    for etf in sector_etfs:
        try:
            etf_hist = yf.Ticker(etf).history(period="1y")["Close"]
            combined = pd.DataFrame({"etf": etf_hist, "bench": benchmark_hist}).dropna()

            if len(combined) < period + 10:
                continue

            rs = combined["etf"] / combined["bench"]
            rs_norm = rs / rs.iloc[0] * 100

            rs_ratio_raw = rs_norm.ewm(span=period).mean()
            rs_ratio = (rs_ratio_raw / rs_ratio_raw.mean()) * 100

            rs_momentum = rs_ratio.pct_change(1) * 100 + 100

            tail_len = 5
            tail = []
            for i in range(-tail_len - 1, 0):
                try:
                    rr = float(rs_ratio.iloc[i])
                    rm = float(rs_momentum.iloc[i])
                    if not (rr != rr or rm != rm):
                        tail.append({"rs_ratio": round(rr, 4), "rs_momentum": round(rm, 4)})
                except Exception:
                    pass

            current_rr = float(rs_ratio.iloc[-1])
            current_rm = float(rs_momentum.iloc[-1])

            result[etf] = {
                "ticker": etf,
                "rs_ratio": round(current_rr, 4),
                "rs_momentum": round(current_rm, 4),
                "quadrant": _rrg_quadrant(current_rr, current_rm),
                "tail": tail,
            }
        except Exception as e:
            logger.warning("RUNNER: Failed to compute RRG for %s: %s", etf, e)

    return result


def _rrg_quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "Leading"
    elif rs_ratio >= 100 and rs_momentum < 100:
        return "Weakening"
    elif rs_ratio < 100 and rs_momentum < 100:
        return "Lagging"
    else:
        return "Improving"


def _identify_movers(performance_data: dict, sector_data: dict) -> list[dict]:
    """Combine performance + sector data to identify top/bottom movers by 1-week return.

    Universe = all 11 sector ETFs (from sector_data) PLUS any additional tickers in
    performance_data (e.g. SPY, QQQ, IWM, GLD, TLT, DBC) not already in sector_data.
    Week return for performance-only tickers is derived from their last 5 daily closes.
    """
    seen = set()
    movers = []

    for ticker, s in sector_data.items():
        seen.add(ticker)
        perf = performance_data.get(ticker, {})
        movers.append({
            "ticker": ticker,
            "week_return": s.get("week_return", 0),
            "day_return": perf.get("pct_change", 0),
            "price": s.get("price"),
            "above_sma20": s.get("above_sma20"),
        })

    for ticker, data in performance_data.items():
        if ticker in seen:
            continue
        closes = data.get("closes", [])
        if len(closes) >= 6:
            week_ago = closes[-6]["close"]
            current = closes[-1]["close"]
            week_return = round(((current - week_ago) / week_ago) * 100, 4)
        else:
            week_return = round(data.get("pct_change", 0), 4)
        movers.append({
            "ticker": ticker,
            "week_return": week_return,
            "day_return": data.get("pct_change", 0),
            "price": data.get("current_price"),
            "above_sma20": None,
        })

    movers.sort(key=lambda x: abs(x["week_return"]), reverse=True)
    return movers[:10]


# ---------------------------------------------------------------------------
# Deep Dive Research — per-section Brave search + LLM (mirrors market_research.py)
# ---------------------------------------------------------------------------

_BLOCKED_DOMAINS = {
    "wsj.com", "ft.com", "bloomberg.com", "economist.com", "washingtonpost.com",
    "reuters.com", "cnbc.com", "apnews.com", "bbc.com", "investopedia.com",
    "marketwatch.com", "morningstar.com", "etf.com", "congress.gov",
}


def _fetch_newsletter_page(url: str) -> dict:
    """Fetch a URL and return extracted plain text. Returns {text, error}."""
    import requests as _req
    from urllib.parse import urlparse
    from research_runner import _html_to_text

    domain = urlparse(url).hostname or ""
    for blocked in _BLOCKED_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return {"text": "", "error": f"Blocked domain: {blocked}"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = _req.get(url, headers=headers, timeout=20, allow_redirects=True)
        resp.raise_for_status()
        text = _html_to_text(resp.text)
        text = text.replace("\x00", "")
        text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
        return {"text": text[:30000], "error": ""}
    except _req.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        return {"text": "", "error": f"HTTP {code}"}
    except Exception as e:
        return {"text": "", "error": str(e)[:200]}


def _run_newsletter_research_leg(leg_name: str, leg_config: dict) -> dict:
    """Run one deep-dive research leg: Brave search → fetch pages → per-source LLM → leg LLM."""
    from research_runner import _brave_search
    from config import openai_client, SMART_MODEL

    result = {
        "leg": leg_name,
        "title": leg_config["title"],
        "summary": "",
        "error": "",
        "sources": [],
    }
    try:
        all_sources = []
        seen_urls: set = set()

        for i, query in enumerate(leg_config["queries"]):
            if i > 0:
                time.sleep(8)
            logger.info("NEWSLETTER LEG [%s]: Query %d: %s", leg_name, i + 1, query)

            search_results = _brave_search(query, num_results=4)
            logger.info("NEWSLETTER LEG [%s]:   → %d results", leg_name, len(search_results))

            for sr in search_results:
                if sr["url"] in seen_urls:
                    continue
                seen_urls.add(sr["url"])

                logger.info("NEWSLETTER LEG [%s]:   FETCH %s", leg_name, sr["url"][:80])
                fetch = _fetch_newsletter_page(sr["url"])
                if fetch["error"]:
                    logger.info("NEWSLETTER LEG [%s]:     ✗ %s", leg_name, fetch["error"])
                    continue
                text = fetch["text"]
                if len(text.strip()) < 100:
                    logger.info("NEWSLETTER LEG [%s]:     → too short, skip", leg_name)
                    continue
                logger.info("NEWSLETTER LEG [%s]:     ✓ %d words", leg_name, len(text.split()))
                all_sources.append({**sr, "text": text})

        if not all_sources:
            result["summary"] = f"*No sources found for {leg_config['title']}.*"
            result["error"] = "no_sources"
            return result

        result["sources"] = [
            {"title": s.get("title") or "Untitled source", "url": s.get("url", "")}
            for s in all_sources
            if s.get("url")
        ]

        # Per-source LLM summarization
        source_summaries = []
        for i, s in enumerate(all_sources, 1):
            logger.info("NEWSLETTER LEG [%s]: Summarizing source %d/%d — %s",
                        leg_name, i, len(all_sources), s["title"][:50])
            try:
                sr_resp = openai_client.chat.completions.create(
                    model=SMART_MODEL,
                    messages=[
                        {"role": "system", "content": (
                            f"Today is {date.today().isoformat()}. "
                            "Summarize this source with maximum information density. "
                            "Include all specific facts, numbers, dates, names, percentages, and forecasts. "
                            "If this source was published more than 7 days ago, begin your summary with [OUTDATED] "
                            "and note why the content is stale. Do not present old data as current. "
                            "Omit ads, navigation, and boilerplate. Write in dense paragraph form. "
                            "Use NO markdown bold or formatting — plain text only."
                        )},
                        {"role": "user", "content": (
                            f"Source: {s['title']}\nURL: {s['url']}\n\n{s['text'][:20000]}"
                        )},
                    ],
                    max_completion_tokens=8000,
                    temperature=0.2,
                )
                content = (sr_resp.choices[0].message.content or "").strip()
                if content:
                    source_summaries.append(
                        f"### {s['title']}\nURL: {s['url']}\n{content}"
                    )
            except Exception as e:
                logger.warning("NEWSLETTER LEG [%s]: Source %d summary failed: %s", leg_name, i, e)
                source_summaries.append(
                    f"### {s['title']}\nURL: {s['url']}\n{s['text'][:2000]}"
                )

        combined = "\n\n".join(source_summaries)
        logger.info("NEWSLETTER LEG [%s]: %d summaries (%d chars) → final analysis",
                    leg_name, len(source_summaries), len(combined))

        # Final per-leg analysis from bounded summaries
        resp = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {"role": "system", "content": leg_config["system_prompt"]},
                {"role": "user", "content": (
                    f"Today is {date.today().isoformat()}. "
                    f"Based on these {len(source_summaries)} source summaries, provide your analysis.\n\n"
                    f"{combined}\n\n"
                    "Write a detailed, specific, data-driven analysis with concrete facts, numbers, dates, "
                    "and named sources (firms, analysts, institutions). "
                    "IMPORTANT: Do NOT reference source numbers (e.g. 'Source 1', 'Source 2') — "
                    "they are meaningless to readers. "
                    "Exclude or discard any content marked [OUTDATED] — do not include stale data in your analysis. "
                    "Prioritize the most recent, market-moving information only. "
                    "FORMATTING: Use bold (**text**) ONLY for ticker symbols (e.g. **SPY**, **TLT**, **GLD**). "
                    "Do NOT bold headlines, phrases, names, numbers, or any other text. Plain prose only. "
                    "Do NOT include offers to do more analysis or conversational follow-ups."
                )},
            ],
            max_completion_tokens=16000,
            temperature=0.3,
        )
        result["summary"] = (resp.choices[0].message.content or "").strip()
        logger.info("NEWSLETTER LEG [%s]: Complete — %d chars", leg_name, len(result["summary"]))

    except Exception as e:
        logger.error("NEWSLETTER LEG [%s]: Failed: %s", leg_name, e, exc_info=True)
        result["error"] = str(e)
        result["summary"] = f"*Research failed for {leg_config['title']}: {e}*"

    return result


def _run_data_synthesis(
    premarket_data: dict,
    performance_data: dict,
    regime_data: dict,
    rrg_data: dict,
    breadth: dict,
    movers: list,
) -> dict:
    """Single LLM call: derive the primary signal and regime label from technical market data only."""
    from config import openai_client, SMART_MODEL
    import json
    from decimal import Decimal

    def _json_default(o):
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    data_summary = {
        "premarket_top_movers": sorted(
            premarket_data.values(),
            key=lambda x: x.get("pct_change", 0),
            reverse=True,
        )[:5],
        "performance_30d": sorted(
            [{"ticker": k, "value_10k": v.get("value_10k"), "pct_change": v.get("pct_change")}
             for k, v in performance_data.items()],
            key=lambda x: x.get("pct_change", 0),
            reverse=True,
        ),
        "regime_data": {k: {"trend": v.get("trend"), "current_ratio": v.get("current_ratio")}
                        for k, v in regime_data.items()},
        "rrg_leading": [k for k, v in rrg_data.items() if v.get("quadrant") == "Leading"],
        "rrg_improving": [k for k, v in rrg_data.items() if v.get("quadrant") == "Improving"],
        "breadth": {
            "vix": breadth.get("vix"),
            "sector_breadth_pct": breadth.get("sector_breadth_pct"),
            "sector_momentum": breadth.get("sector_momentum"),
        },
        "top_movers": movers[:5],
    }

    prompt = f"""You are generating the primary signal for an automated market intelligence brief.
Based ONLY on the technical market data below, identify:
1. The Primary Signal — the single clearest ETF or asset-class setup the data supports over the next 5 to 30 trading days
2. The Market Regime label — a concise descriptive name for the current market environment

Market Data:
{json.dumps(data_summary, indent=2, default=_json_default)}

Return a JSON object with exactly these keys:
{{
  "best_bet_symbol": "<ticker e.g. GLD>",
  "best_bet_class": "<asset class name e.g. Commodities / Precious Metals>",
  "best_bet_reason": "<2-3 sentences citing specific data points from above>",
  "regime_label": "<named regime e.g. Risk-Off with Inflation Hedge Demand>"
}}

Return only valid JSON. No markdown fences."""

    try:
        response = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=600,
            temperature=0.3,
        )
        import json as _json
        return _json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        logger.error("RUNNER: Data synthesis failed: %s", e, exc_info=True)
        return {}


def _run_tldr_synthesis(synthesis: dict, premarket_data: dict, movers: list) -> str:
    """Generate a 3-bullet TL;DR summary of the entire newsletter edition."""
    from config import openai_client, SMART_MODEL

    top_pm = sorted(premarket_data.values(), key=lambda x: abs(x.get("pct_change", 0)), reverse=True)[:3]
    pm_summary = ", ".join(
        f"{d['symbol']} {'+' if d['pct_change'] >= 0 else ''}{d['pct_change']:.2f}%"
        for d in top_pm
    )
    top_movers = ", ".join(
        f"{m['ticker']} {'+' if m.get('week_return', 0) >= 0 else ''}{m.get('week_return', 0):.1f}% (1wk)"
        for m in movers[:3]
    )

    context = (
        f"Regime: {synthesis.get('regime_label', 'Unknown')}\n"
        f"Primary Signal: {synthesis.get('best_bet_symbol', 'N/A')} — {synthesis.get('best_bet_reason', '')}\n"
        f"Pre-market movers: {pm_summary}\n"
        f"Top ETF movers: {top_movers}\n"
        f"Overall Outlook: {synthesis.get('overall_outlook', '')[:800]}\n"
        f"Macro Pulse: {synthesis.get('macro_pulse', '')[:400]}\n"
        f"News Highlights: {synthesis.get('news_highlights', '')[:400]}\n"
    )

    try:
        resp = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are writing the TL;DR for a fully automated market intelligence brief. "
                    "Write exactly 3 short bullet points (1 sentence each, max 15 words per bullet) "
                    "that capture the single most important market signals for today's tape and the next 30 days. "
                    "Use plain text. Bold (**text**) ONLY for ticker symbols. "
                    "No headers, no intro, no outro — just the 3 bullets."
                )},
                {"role": "user", "content": context},
            ],
            max_completion_tokens=200,
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("RUNNER: TL;DR synthesis failed: %s", e, exc_info=True)
        return ""


def _run_movers_synthesis(movers: list, synthesis: dict, ticker_news: dict = None) -> dict:
    """Single LLM call to generate 'What Happened' for each top mover.

    Uses deep dive context AND per-symbol Finnhub news digests as grounding.
    Returns {ticker: reason} dict where each reason is a plain-English 1-sentence
    explanation of the move. Falls back to empty dict on failure.
    """
    from config import openai_client, SMART_MODEL
    import json

    if not movers:
        return {}

    context_parts = []
    for key in ("news_highlights", "macro_pulse", "geopolitical", "analyst_consensus"):
        text = synthesis.get(key, "")
        if text and not text.startswith("*Research failed") and not text.startswith("*No sources"):
            context_parts.append(f"## {key.replace('_', ' ').title()}\n{text[:2000]}")

    context = "\n\n".join(context_parts) if context_parts else "No research context available."

    top_movers = movers[:6]
    movers_list = "\n".join(
        f"- {m['ticker']}: {'+' if m.get('week_return', 0) >= 0 else ''}{m.get('week_return', 0):.1f}% this week"
        for m in top_movers
    )

    # Build per-ticker Finnhub news block for the movers specifically
    _ticker_news = ticker_news or {}
    symbol_news_parts = []
    for m in top_movers:
        sym = m["ticker"]
        if sym in _ticker_news:
            etf_name = _NEWSLETTER_ETF_NAMES.get(sym, sym)
            symbol_news_parts.append(f"{sym} ({etf_name}): {_ticker_news[sym]}")
    symbol_news_block = (
        "\n\nPer-symbol Finnhub news (use as primary source for the reason):\n"
        + "\n\n".join(symbol_news_parts)
    ) if symbol_news_parts else ""

    try:
        resp = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {"role": "system", "content": (
                    f"Today is {date.today().isoformat()}. You are writing the 'What Happened' column "
                    "for an automated market intelligence brief's Movers & Why table. "
                    "For each ETF mover, write ONE plain-English sentence (under 25 words) explaining "
                    "the specific catalyst or macro theme driving the move this week. "
                    "Prefer the per-symbol Finnhub news digests as your primary source — they contain "
                    "the actual news events. Use the broader research context only to fill gaps. "
                    "Be concrete — name the actual event, data release, earnings, or sector dynamic. "
                    "Return ONLY valid JSON: {\"TICKER\": \"reason sentence\", ...}. No markdown fences."
                )},
                {"role": "user", "content": (
                    f"These ETFs are this week's top movers:\n{movers_list}"
                    f"{symbol_news_block}\n\n"
                    f"Broader research context:\n{context[:6000]}"
                )},
            ],
            max_completion_tokens=600,
            temperature=0.2,
        )
        raw = (resp.choices[0].message.content or "").strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logger.warning("RUNNER: Movers synthesis failed: %s", e)
        return {}


def _save_newsletter_archive(
    edition_date: date,
    content_md: str,
    charts_generated: list[dict],
) -> str:
    """Save a complete newsletter run to uploads/newsletter/<date>_<HHMMSS>/.

    Creates:
      newsletter.md   — raw markdown
      newsletter.html — self-contained HTML with base64-embedded chart images
      *.png           — all chart PNGs (for direct image viewing)

    Returns the archive folder path.
    """
    import base64
    import shutil
    from datetime import datetime as _dt
    from pathlib import Path
    from apps.newsletter.sender import _markdown_to_html

    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    base = Path(__file__).resolve().parents[2] / "uploads" / "newsletter" / f"{edition_date}_{ts}"
    base.mkdir(parents=True, exist_ok=True)

    # Save raw markdown
    (base / "newsletter.md").write_text(content_md, encoding="utf-8")

    # Copy PNGs and build cid→base64 map
    cid_b64: dict[str, str] = {}
    for chart in charts_generated:
        fp = Path(chart.get("file_path", ""))
        chart_type = chart.get("chart_type", fp.stem)
        if fp.exists():
            shutil.copy2(fp, base / fp.name)
            with open(fp, "rb") as fh:
                cid_b64[chart_type] = base64.b64encode(fh.read()).decode("utf-8")

    # Build HTML and substitute cid: → data URI so it is self-contained
    html = _markdown_to_html(content_md)
    for chart_type, b64 in cid_b64.items():
        html = html.replace(
            f'src="cid:{chart_type}"',
            f'src="data:image/png;base64,{b64}"',
        )

    (base / "newsletter.html").write_text(html, encoding="utf-8")
    logger.info("RUNNER: Newsletter archived to %s", base)
    return str(base)


def _build_perf_context(
    performance_data: dict,
    movers: list,
    regime_data: dict,
    ticker_news: dict = None,
) -> str:
    """Build a compact ground-truth block of actual market performance numbers and
    per-symbol Finnhub news digests.

    Injected into every deep-dive system prompt so LLM narratives cannot
    contradict actual price data. Where a narrative diverges from the data,
    the LLM is instructed to reconcile rather than ignore.
    """
    lines = [
        "\n\nACTUAL MARKET DATA — GROUND TRUTH:",
        ("The following numbers are computed directly from live market prices and must be "
         "treated as authoritative facts. Your narrative MUST be consistent with them. "
         "If research sources paint a different picture (e.g. calling gold a safe haven "
         "when GLD is actually down), do NOT repeat that narrative uncritically. "
         "Instead, explicitly acknowledge the divergence: explain why the narrative expectation "
         "differs from the actual price action. Never present an asset as performing well "
         "when the data shows it declining, or vice versa."),
        "",
    ]

    if performance_data:
        sorted_perf = sorted(
            performance_data.items(),
            key=lambda x: x[1].get("pct_change") or 0,
            reverse=True,
        )
        perf_parts = []
        for ticker, data in sorted_perf:
            pct = data.get("pct_change")
            if pct is not None:
                sign = "+" if pct >= 0 else ""
                perf_parts.append(f"{ticker} {sign}{pct:.1f}%")
        if perf_parts:
            lines.append(f"30-day ETF/asset returns: {', '.join(perf_parts)}")

    if movers:
        mover_parts = []
        for m in movers[:8]:
            ticker = m.get("ticker", "")
            week_r = m.get("week_return", 0)
            sign = "+" if week_r >= 0 else ""
            mover_parts.append(f"{ticker} {sign}{week_r:.1f}%")
        if mover_parts:
            lines.append(f"1-week ETF movers (biggest moves): {', '.join(mover_parts)}")

    if regime_data:
        regime_parts = []
        for label, data in regime_data.items():
            trend = data.get("trend", "flat")
            arrow = "\u2191" if trend == "up" else "\u2193" if trend == "down" else "\u2192"
            ratio = data.get("current_ratio")
            ratio_str = f" (ratio: {ratio:.4f})" if ratio else ""
            regime_parts.append(f"{label} {arrow} {trend}{ratio_str}")
        if regime_parts:
            lines.append(f"Market regime signals: {'; '.join(regime_parts)}")

    if ticker_news:
        lines.append("")
        lines.append("PER-SYMBOL NEWS DIGESTS (Finnhub, last 3 days):")
        lines.append("Use these to corroborate or challenge your web research findings.")
        for sym in sorted(ticker_news.keys()):
            etf_name = _NEWSLETTER_ETF_NAMES.get(sym, sym)
            lines.append(f"\n{sym} ({etf_name}): {ticker_news[sym]}")

    return "\n".join(lines)


def _run_deep_dive_research(
    edition_date: date,
    progress_fn=None,
    performance_data: dict = None,
    movers: list = None,
    regime_data: dict = None,
    ticker_news: dict = None,
) -> dict:
    """Run per-section Brave search + LLM for all 7 deep-dive newsletter sections."""
    _pfn = progress_fn or (lambda pct, msg: None)
    today = edition_date.isoformat()

    perf_context = _build_perf_context(
        performance_data or {},
        movers or [],
        regime_data or {},
        ticker_news=ticker_news,
    )

    legs = {
        "news_highlights": {
            "title": "Market News Highlights",
            "queries": [
                f"financial markets news today {today} premarket overnight",
                f"stock market breaking news {today} economic",
                f"ETF market moving news {today}",
            ],
            "system_prompt": (
                "Generate a market news section for an ETF-focused automated market intelligence brief. "
                "Summarize the key overnight and pre-market news events that matter for investors today.\n\n"
                "Format as a bullet list of 5-8 items. Each bullet: a plain-text headline, then 1-2 sentences "
                "on market impact. Focus on events that could move SPY, QQQ, TLT, GLD, oil, or sector ETFs. "
                "Be specific — cite actual events, names, numbers. No generic commentary. "
                "FORMATTING: Use bold (**text**) ONLY for ticker symbols (e.g. **SPY**, **TLT**). "
                "Do NOT bold headlines, phrases, numbers, or any other text."
            ) + _PROSE_STYLE,
        },
        "macro_pulse": {
            "title": "Macro Pulse",
            "queries": [
                f"global macro market outlook {today} risk appetite",
                f"equity market macro conditions credit spreads dollar {today}",
                f"market sentiment volatility macro themes {today}",
            ],
            "system_prompt": (
                "Generate a macro section for an ETF-focused automated market intelligence brief. "
                "Write 1 tight paragraph (5-7 sentences) on the current macro environment.\n\n"
                "Focus ONLY on the single most dominant macro theme right now. Include the most recent, relevant, "
                "and market-moving facts: risk appetite (risk-on vs risk-off), USD direction, yield curve, "
                "and what it means for ETF positioning. Be specific with levels and numbers. "
                "No generic observations. This will be used to make investment decisions for ETF portfolios."
            ) + _PROSE_STYLE,
        },
        "fed_summary": {
            "title": "Federal Reserve & Rate Policy",
            "queries": [
                f"federal reserve interest rate policy decision {today}",
                f"FOMC rate forecast fed funds futures probabilities {today}",
                f"Fed Chair Powell comments inflation rate path {today}",
            ],
            "system_prompt": (
                "Generate a monetary policy section for an ETF-focused automated market intelligence brief. "
                "Write 1 tight paragraph (5-7 sentences) on the current Fed stance.\n\n"
                "Include only the most recent and impactful: current fed funds rate, latest FOMC decision or "
                "Fed official comment (name + date), CME FedWatch cut probability, and what it means for "
                "TLT/IEF/BIL. Be specific with numbers. "
                "This will be used to make investment decisions for ETF portfolios."
            ) + _PROSE_STYLE,
        },
        "economic_picture": {
            "title": "Economic Picture",
            "queries": [
                f"US economic data CPI inflation jobs latest release {today}",
                f"GDP growth PMI consumer spending economic indicators {today}",
                f"recession probability leading indicators US economy {today}",
            ],
            "system_prompt": (
                "Generate an economic section for an ETF-focused automated market intelligence brief. "
                "Write 1 tight paragraph (5-7 sentences) on where the US economy stands right now.\n\n"
                "Lead with the single most recent and market-moving data release (CPI, jobs, GDP, PMI "
                "— whichever is freshest). Include the actual number, date, and what it means for "
                "equity/bond ETFs. Only add 1-2 additional data points if they are directly relevant. "
                "This will be used to make investment decisions for ETF portfolios."
            ) + _PROSE_STYLE,
        },
        "analyst_consensus": {
            "title": "What Analysts Are Saying",
            "queries": [
                f"wall street analyst market outlook forecast this week {today}",
                f"institutional investor sentiment equity market consensus {today}",
                f"bank strategist SPX target sector calls upgrades downgrades {today}",
            ],
            "system_prompt": (
                "Generate a Wall Street consensus section for an ETF-focused automated market intelligence brief. "
                "Write 1 tight paragraph (5-7 sentences) summarizing the most impactful Wall Street calls right now.\n\n"
                "Lead with the most notable recent call, upgrade/downgrade, or SPX target revision. "
                "Name the firm and strategist. Include 1-2 additional contrasting views if they are recent and meaningful. "
                "Be specific with numbers and targets. "
                "This will be used to make investment decisions for ETF portfolios."
            ) + _PROSE_STYLE,
        },
        "geopolitical": {
            "title": "Geopolitical Backdrop",
            "queries": [
                f"geopolitical risks financial markets tariffs trade war {today}",
                f"international conflict sanctions oil supply market impact {today}",
                f"US China trade policy tariffs economic impact {today}",
            ],
            "system_prompt": (
                "Generate a geopolitical section for an ETF-focused automated market intelligence brief. "
                "Write 1 tight paragraph (5-7 sentences) on the single most market-relevant geopolitical risk right now.\n\n"
                "Focus on the event most actively moving markets today — tariffs, conflict, sanctions, energy supply. "
                "Explain how it is being priced in and which ETFs are most vulnerable vs most protected. "
                "Be specific with numbers and dates. No hypothetical or generic risk descriptions. "
                "This will be used to make investment decisions for ETF portfolios."
            ) + _PROSE_STYLE,
        },
        "fund_flows": {
            "title": "Fund Flows & Positioning",
            "queries": [
                f"ETF fund flows weekly inflows outflows billions {today}",
                f"institutional positioning hedge fund allocation sector rotation {today}",
                f"equity bonds commodities money flow where is money going {today}",
            ],
            "system_prompt": (
                "Generate a fund flow section for an ETF-focused automated market intelligence brief. "
                "Write 1 tight paragraph (5-7 sentences) on where money is flowing right now.\n\n"
                "Lead with the largest or most surprising ETF inflow or outflow this week (name the ETF and $ amount). "
                "Add 1-2 additional rotation signals (equity vs bonds, growth vs value, sector shifts) if they are current and significant. "
                "Use specific dollar amounts and percentages. "
                "This will be used to make investment decisions for ETF portfolios."
            ) + _PROSE_STYLE,
        },
    }

    leg_order = [
        "news_highlights", "macro_pulse", "fed_summary", "economic_picture",
        "analyst_consensus", "geopolitical", "fund_flows",
    ]

    results = {}
    source_map = {}
    for idx, leg_name in enumerate(leg_order):
        pct = 75 + int((idx / len(leg_order)) * 20)
        _pfn(pct, f"Deep Dive [{idx + 1}/{len(leg_order)}]: {legs[leg_name]['title']}")
        if idx > 0:
            time.sleep(5)
        leg_cfg = dict(legs[leg_name])
        leg_cfg["system_prompt"] = leg_cfg["system_prompt"] + perf_context
        leg_result = _run_newsletter_research_leg(leg_name, leg_cfg)
        results[leg_name] = leg_result.get("summary") or f"*{legs[leg_name]['title']} unavailable.*"
        source_map[legs[leg_name]["title"]] = leg_result.get("sources") or []

    # Overall synthesis — combine all 7 leg summaries into a cohesive automated view
    _pfn(96, "Deep Dive: 30-Day Outlook synthesis")
    try:
        from config import openai_client, SMART_MODEL
        combined_research = "\n\n".join(
            f"## {legs[k]['title']}\n{results[k]}"
            for k in leg_order
            if results.get(k) and not results[k].startswith("*No sources")
               and not results[k].startswith("*Research failed")
        )
        overall_resp = openai_client.chat.completions.create(
            model=SMART_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are generating the 30-Day Outlook for an automated market intelligence product "
                    "called Systematic Market Brief. Write a cohesive 3-4 paragraph outlook that synthesizes "
                    "all the research below into the single most important narrative for ETF investors over the "
                    "next 30 days.\n\n"
                    "Cover: the dominant macro theme, the key risk, the clearest opportunity, and what today's "
                    "pre-market setup says about that broader 30-day view. "
                    "Be specific — name actual events, ETFs, and numbers from the research. "
                    "This is a system-generated outlook, not a personal column.\n\n"
                    "FORMATTING: Write in plain prose. Use bold (**text**) ONLY for ETF or stock ticker symbols "
                    "(e.g. **SPY**, **TLT**, **GLD**, **XLE**). Do NOT bold phrases, themes, numbers, dates, "
                    "named concepts, or any other text. No exceptions."
                ) + _PROSE_STYLE + perf_context},
                {"role": "user", "content": (
                    f"Today is {edition_date.isoformat()}.\n\n"
                    f"{combined_research}\n\n"
                    "Write the 30-Day Outlook section now."
                )},
            ],
            max_completion_tokens=16000,
            temperature=0.3,
        )
        results["overall_outlook"] = (overall_resp.choices[0].message.content or "").strip()
        logger.info("NEWSLETTER: Overall outlook — %d chars", len(results["overall_outlook"]))
    except Exception as e:
        logger.error("NEWSLETTER: Overall outlook synthesis failed: %s", e, exc_info=True)
        results["overall_outlook"] = ""

    results["source_map"] = source_map
    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_newsletter_pipeline(
    edition_date: Optional[date] = None,
    progress_fn: Optional[Callable] = None,
) -> dict:
    """Run the full newsletter generation pipeline.

    Args:
        edition_date: Date for the newsletter. Defaults to today.
        progress_fn: Optional callback(pct, msg) for job progress updates.

    Returns:
        dict with edition_id, edition_date, status.
    """
    from apps.newsletter.data import (
        create_edition, update_edition_status, update_edition_content,
        save_market_snapshot, get_breadth, get_config,
    )

    def _progress(pct, msg):
        logger.info("RUNNER [%d%%]: %s", pct, msg)
        if progress_fn:
            progress_fn(pct, msg)

    if edition_date is None:
        edition_date = date.today()

    cfg = get_config() or {}
    product_config = _get_product_config(cfg)
    performance_tickers = cfg.get("performance_tickers") or ["SPY", "QQQ", "IWM", "GLD", "TLT", "XLE", "XLU", "DBC"]
    lookback_days = int(cfg.get("performance_lookback_days") or 30)
    chart_dir = cfg.get("chart_output_dir") or "/tmp/newsletter_charts"
    os.makedirs(chart_dir, exist_ok=True)

    _progress(0, "Creating edition record")
    edition = create_edition(edition_date)
    edition_id = edition["id"]
    update_edition_status(edition_id, "generating")

    try:
        _progress(5, "Fetching pre-market futures data")
        premarket_data = _fetch_premarket_data(list(FUTURES_SYMBOLS.keys()))

        _progress(15, "Fetching 30-day portfolio performance")
        performance_data = _fetch_performance_data(performance_tickers, lookback_days)

        _progress(25, "Fetching sector performance (11 SPDR ETFs)")
        sector_data = _fetch_sector_data(SECTOR_ETFS)

        _progress(35, "Computing market regime ratios")
        regime_data = _fetch_regime_data(REGIME_RATIOS)

        _progress(45, "Computing RRG (Relative Rotation Graph)")
        rrg_data = _compute_rrg_data(SECTOR_ETFS)

        _progress(55, "Identifying top movers")
        movers = _identify_movers(performance_data, sector_data)

        _progress(58, "Fetching per-symbol Finnhub news")
        newsletter_universe = list(set(list(sector_data.keys()) + performance_tickers))
        ticker_news, _finnhub_raw = _fetch_symbol_news(newsletter_universe)
        logger.info("RUNNER: Per-symbol news: %d/%d symbols", len(ticker_news), len(newsletter_universe))

        _progress(60, "Loading breadth snapshot")
        breadth = get_breadth(edition_date) or get_breadth(edition_date - timedelta(days=1)) or {}

        _progress(65, "Saving market snapshot to DB")
        save_market_snapshot(
            edition_id=edition_id,
            premarket_data=premarket_data,
            performance_data=performance_data,
            sector_data=sector_data,
            regime_data=regime_data,
            rrg_data=rrg_data,
            movers=movers,
        )

        _progress(70, "Generating charts")
        from apps.newsletter.charts import generate_all_charts
        charts_generated = generate_all_charts(
            edition_id=edition_id,
            chart_dir=chart_dir,
            premarket_data=premarket_data,
            performance_data=performance_data,
            regime_data=regime_data,
            rrg_data=rrg_data,
        )
        logger.info("RUNNER: %d charts generated", len(charts_generated))

        _progress(72, "Data synthesis: Primary Signal + Market Regime")
        synthesis = _run_data_synthesis(
            premarket_data=premarket_data,
            performance_data=performance_data,
            regime_data=regime_data,
            rrg_data=rrg_data,
            breadth=breadth,
            movers=movers,
        )

        _progress(75, "Deep Dive research: starting 7 sections")
        deep_dive = _run_deep_dive_research(
            edition_date,
            progress_fn=_progress,
            performance_data=performance_data,
            movers=movers,
            regime_data=regime_data,
            ticker_news=ticker_news,
        )
        synthesis.update(deep_dive)

        # Merge Finnhub article URLs into source_map
        for sym in sorted(_finnhub_raw.keys()):
            articles = _finnhub_raw[sym]
            sources = [
                {"title": f"[{a['source']}] {a['headline']}", "url": a["url"]}
                for a in articles
                if a.get("url")
            ]
            if sources:
                etf_name = _NEWSLETTER_ETF_NAMES.get(sym, sym)
                synthesis.setdefault("source_map", {})[f"{sym} — {etf_name}"] = sources

        _progress(96, "TL;DR synthesis")
        synthesis["tldr"] = _run_tldr_synthesis(synthesis, premarket_data, movers)

        _progress(96, "Movers synthesis: What Happened")
        mover_reasons = _run_movers_synthesis(movers, synthesis, ticker_news=ticker_news)
        logger.info("RUNNER: Movers synthesis returned %d reasons", len(mover_reasons))

        chart_trends = {
            r["chart_type"]: r["trend"]
            for r in charts_generated
            if r.get("trend")
        }

        _progress(97, "Assembling market brief document")
        content_md = _assemble_markdown(
            edition_date=edition_date,
            product_config=product_config,
            synthesis=synthesis,
            premarket_data=premarket_data,
            performance_data=performance_data,
            sector_data=sector_data,
            breadth=breadth,
            movers=movers,
            regime_data=regime_data,
            rrg_data=rrg_data,
            mover_reasons=mover_reasons,
            chart_trends=chart_trends,
        )

        update_edition_content(
            edition_id=edition_id,
            content_md=content_md,
            best_bet_symbol=synthesis.get("best_bet_symbol", ""),
            best_bet_class=synthesis.get("best_bet_class", ""),
            best_bet_reason=synthesis.get("best_bet_reason", ""),
            regime_label=synthesis.get("regime_label", ""),
        )

        try:
            archive_path = _save_newsletter_archive(edition_date, content_md, charts_generated)
            _progress(99, f"Archived to {archive_path}")
        except Exception as arc_err:
            logger.warning("RUNNER: Archive save failed (non-fatal): %s", arc_err)

        update_edition_status(edition_id, "generated")
        _progress(100, "Market brief generated")

        return {"edition_id": edition_id, "edition_date": str(edition_date), "status": "generated"}

    except Exception as e:
        logger.error("RUNNER: Pipeline failed for %s: %s", edition_date, e, exc_info=True)
        update_edition_status(edition_id, "error", error_msg=str(e))
        raise


# ---------------------------------------------------------------------------
# Markdown assembler
# ---------------------------------------------------------------------------

def _assemble_markdown(
    edition_date: date,
    product_config: dict,
    synthesis: dict,
    premarket_data: dict,
    performance_data: dict,
    sector_data: dict,
    breadth: dict,
    movers: list,
    regime_data: dict,
    rrg_data: dict,
    mover_reasons: dict = None,
    chart_trends: dict = None,
) -> str:
    """Assemble the full market brief markdown from data + LLM synthesis."""
    from apps.newsletter.breadth import get_breadth_signal
    import datetime

    try:
        day_str = edition_date.strftime("%A, %B %#d, %Y")   # Windows
    except ValueError:
        day_str = edition_date.strftime("%A, %B %-d, %Y")   # Linux/Mac

    tldr = synthesis.get("tldr", "")
    product_name = product_config["product_name"]
    product_tagline = product_config["product_tagline"]
    disclosure_short = product_config["disclosure_short"]
    disclosure_long = product_config["disclosure_long"]
    primary_signal_label = product_config["primary_signal_label"]
    outlook_label = product_config["outlook_label"]
    source_map = synthesis.get("source_map") or {}

    lines = [
        f"# {product_name}",
        f"### {day_str}",
        f"*{product_tagline}*",
        f"*{disclosure_short}*",
        "",
    ]

    if tldr:
        lines += [
            "> **TL;DR**",
            "> ",
        ]
        for bullet in tldr.splitlines():
            bullet = bullet.strip()
            if bullet:
                lines.append(f"> {bullet}")
        lines += ["", "---", ""]
    else:
        lines += ["---", ""]

    lines += [
        f"## {primary_signal_label}",
        "",
        "*Highest-scoring systematic setup from the current cross-asset, breadth, and rotation data.*",
        "",
        f"**Symbol:** `{synthesis.get('best_bet_symbol', 'N/A')}` — {synthesis.get('best_bet_reason', '')}",
        "",
        f"**Asset Class:** {synthesis.get('best_bet_class', 'N/A')}",
        "",
        "*This is a system-generated signal, not a discretionary trade recommendation.*",
        "",
        "---",
        "",
        "## 1. Pre-Market Snapshot",
        "*Sorted strongest to weakest pre-market move. Dashed line = previous close.*",
        "",
    ]

    sorted_pm = sorted(premarket_data.values(), key=lambda x: x.get("pct_change", 0), reverse=True)
    for item in sorted_pm:
        symbol = item["symbol"]
        price = item["price"]
        pct = item["pct_change"]
        sign = "+" if pct >= 0 else ""
        lines.append(f"**{symbol}** ({item.get('name', symbol)}) — {price:,.2f} · **{sign}{pct:.2f}%**  ")
        lines.append(f"[CHART: premarket_mini_{symbol.replace('=F','').lower()}]")
        lines.append("")

    lines += [
        "---",
        "",
        "## 2. Market Breadth & Metrics",
        "",
        "| Indicator | Value | Signal |",
        "|---|---|---|",
    ]

    vix = breadth.get("vix")
    sector_breadth_pct = breadth.get("sector_breadth_pct")
    sector_momentum = breadth.get("sector_momentum")

    lines.append(f"| VIX | **{vix:.1f}** | {'⚠️ Elevated' if vix and vix >= 20 else '✓ Normal'} |" if vix else "| VIX | N/A | — |")
    lines.append(f"| Sector Breadth | **{sector_breadth_pct:.0f}%** above SMA50 | {'🔴 Very narrow' if sector_breadth_pct and sector_breadth_pct < 36 else '⚠️ Minority' if sector_breadth_pct and sector_breadth_pct < 55 else '✓ Healthy'} |" if sector_breadth_pct else "| Sector Breadth | N/A | — |")
    lines.append(f"| Sector Momentum | **{sector_momentum:.1f}** | {'🔴 Declining' if sector_momentum and sector_momentum < -3 else '⚠️ Mild drift' if sector_momentum and sector_momentum < 0 else '✓ Positive'} |" if sector_momentum else "| Sector Momentum | N/A | — |")

    signal = get_breadth_signal(vix, sector_breadth_pct, sector_momentum)
    lines += [
        "",
        f"*{signal}*",
        "",
        "---",
        "",
        "## 3. Portfolio Performances",
        "",
        "*$10,000 invested 30 days ago in each asset:*",
        "",
        "[CHART: normalized_growth_30d]",
        "",
        "| Rank | Symbol | 30-Day Value | Return |",
        "|---|---|---|---|",
    ]

    sorted_perf = sorted(performance_data.items(), key=lambda x: x[1].get("value_10k") or 10000, reverse=True)
    for rank, (ticker, data) in enumerate(sorted_perf, 1):
        val = data.get("value_10k")
        pct = data.get("pct_change")
        if val is None or pct is None or (isinstance(val, float) and math.isnan(val)):
            continue
        sign = "+" if pct >= 0 else ""
        lines.append(f"| {rank} | {ticker} | ${val:,.0f} | {sign}{pct:.1f}% |")

    lines += [
        "",
        "---",
        "",
        "## 4. Movers & Why",
        "",
        "*Top movers in the ETF universe — with the reason behind the move.*",
        "",
        "| Symbol | 1-Week | What Happened |",
        "|---|---|---|",
    ]

    _mover_reasons = mover_reasons or {}
    for m in movers[:6]:
        ticker = m["ticker"]
        week_r = m.get("week_return", 0)
        sign = "+" if week_r >= 0 else ""
        reason = _mover_reasons.get(ticker, "*No data*")
        lines.append(f"| {ticker} | {sign}{week_r:.1f}% | {reason} |")

    lines += [
        "",
        "---",
        "",
        "## 5. Market Regime",
        "",
        f"**Current Regime: {synthesis.get('regime_label', 'Undetermined')}**",
        "",
        (
            "*Each chart below shows a **price ratio** — computed by literally dividing one asset's price by another. "
            "When the ratio rises, the numerator (top symbol) is outperforming the denominator (bottom symbol); "
            "when it falls, the denominator is winning. "
            "The smooth line is a **30-period Hull Moving Average (HMA30)** — a fast, low-lag trend smoother. "
            "When the ratio is above the HMA30 line, the trend is up ↑; below it, the trend is down ↓. "
            "Together, the three ratios tell you whether markets are risk-on (stocks beating bonds), "
            "whether gold is in demand relative to equities, and whether hard commodities are leading bonds.*"
        ),
        "",
    ]

    _chart_trends = chart_trends or {}
    for label, data in regime_data.items():
        safe = label.lower().replace("/", "_")
        chart_trend = _chart_trends.get(f"regime_{safe}")
        effective_trend = chart_trend if chart_trend else data.get("trend", "flat")
        trend_arrow = "↑" if effective_trend == "up" else "↓" if effective_trend == "down" else "→"
        lines.append(f"[CHART: regime_{safe}]  ")
        lines.append(f"*{label} ratio — {trend_arrow} {effective_trend}*")
        lines.append("")

    lines += [
        "---",
        "",
        "## 6. Sector Rotation",
        "",
        "*Relative Rotation Graph — where each sector is headed.*",
        "",
        "[CHART: sector_rrg]",
        "",
    ]

    leading = [k for k, v in rrg_data.items() if v.get("quadrant") == "Leading"]
    improving = [k for k, v in rrg_data.items() if v.get("quadrant") == "Improving"]
    lagging = [k for k, v in rrg_data.items() if v.get("quadrant") == "Lagging"]
    if leading:
        lines.append(f"**Leading:** {', '.join(leading)}")
    if improving:
        lines.append(f"**Improving (watch):** {', '.join(improving)}")
    if lagging:
        lines.append(f"**Lagging:** {', '.join(lagging)}")

    lines += [
        "",
        "---",
        "",
        "# Deep Dive",
        "",
        f"## {outlook_label}",
        "",
        "*Automated synthesis of the most relevant macro, policy, positioning, and market-news inputs.*",
        "",
        synthesis.get("overall_outlook", "*Overall outlook unavailable.*"),
        "",
        "---",
        "",
        "*Full section-by-section research below - scan the headlines, read what you want.*",
        "",
        "---",
        "",
        "## Market News Highlights",
        "",
        synthesis.get("news_highlights", "*News unavailable.*"),
        "",
        "---",
        "",
        "## Macro Pulse",
        "",
        synthesis.get("macro_pulse", "*Macro analysis unavailable.*"),
        "",
        "---",
        "",
        "## The Fed",
        "",
        synthesis.get("fed_summary", "*Fed analysis unavailable.*"),
        "",
        "---",
        "",
        "## Economic Picture",
        "",
        synthesis.get("economic_picture", "*Economic analysis unavailable.*"),
        "",
        "---",
        "",
        "## What Analysts Are Saying",
        "",
        synthesis.get("analyst_consensus", "*Analyst consensus unavailable.*"),
        "",
        "---",
        "",
        "## Geopolitical Backdrop",
        "",
        synthesis.get("geopolitical", "*Geopolitical analysis unavailable.*"),
        "",
        "---",
        "",
        "## Fund Flows & Positioning",
        "",
        synthesis.get("fund_flows", "*Fund flow data unavailable.*"),
        "",
    ]

    if source_map:
        lines += [
            "---",
            "",
            "## Source Map",
            "",
            "*Primary sources used by the automated research pipeline for this edition.*",
            "",
        ]
        for section_title, section_sources in source_map.items():
            if not section_sources:
                continue
            lines.append(f"### {section_title}")
            for source in section_sources[:6]:
                title = source.get("title", "Untitled source").strip() or "Untitled source"
                url = source.get("url", "").strip()
                if url:
                    lines.append(f"- [{title}]({url})")
            lines.append("")

    lines += [
        "---",
        "",
        f"*{disclosure_long}*",
        "",
        f"*{edition_date}*",
    ]

    return "\n".join(lines)
