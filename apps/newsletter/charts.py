"""Newsletter Chart Generator

Generates all PNG charts for a Systematic Market Brief edition.

Chart inventory:
  premarket_mini_{symbol}  — Mini candlestick chart per futures symbol (mplfinance)
  normalized_growth_30d    — $10K normalized portfolio performance (matplotlib)
  market_regime            — 3-panel SPY/TLT, GLD/SPY, DBC/TLT ratio + HMA30 (matplotlib)
  sector_rrg               — Relative Rotation Graph scatter with tails (matplotlib)

All charts use a dark professional style and are exported as 150 DPI PNGs.
Non-interactive Agg backend is forced so this runs safely in server context.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

DARK_BG   = "#0f1117"
PANEL_BG  = "#1a1d27"
GRID_CLR  = "#2a2d3a"
TEXT_CLR  = "#e0e0e0"
MUTED_CLR = "#888888"
GREEN     = "#26a69a"
RED       = "#ef5350"
GOLD      = "#ffd700"
BLUE      = "#5c9bd6"
PURPLE    = "#9c6cce"

TICKER_COLORS = {
    "SPY": BLUE, "QQQ": PURPLE, "IWM": "#aaaaaa", "GLD": GOLD,
    "TLT": GREEN, "XLE": "#ff9800", "XLU": "#26c6da", "DBC": "#a1887f",
    "XLK": PURPLE, "XLP": "#66bb6a", "XLF": "#42a5f5", "XLI": "#ff7043",
    "XLV": "#ab47bc", "XLB": "#8d6e63", "XLRE": "#ec407a", "XLC": "#7e57c2",
    "XLY": "#ffa726",
}

DPI = 150


def _apply_dark_style(fig, ax_list):
    """Apply consistent dark background style to a figure and its axes."""
    fig.patch.set_facecolor(DARK_BG)
    for ax in ax_list:
        ax.set_facecolor(PANEL_BG)
        ax.tick_params(colors=TEXT_CLR, labelsize=8)
        ax.xaxis.label.set_color(TEXT_CLR)
        ax.yaxis.label.set_color(TEXT_CLR)
        ax.title.set_color(TEXT_CLR)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_CLR)
        ax.grid(True, color=GRID_CLR, linewidth=0.5, alpha=0.7)
        ax.set_axisbelow(True)


def _save(fig, path: str) -> str:
    """Save figure to path and close it."""
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)
    logger.debug("CHARTS: Saved %s", path)
    return path


# ---------------------------------------------------------------------------
# 1. Pre-market mini candlestick charts
# ---------------------------------------------------------------------------

def chart_premarket_mini(symbol: str, data: dict, chart_dir: str) -> Optional[str]:
    """Generate a mini pre-market candlestick chart for a futures symbol.

    Uses raw mpl bar drawing (no mplfinance dependency required).
    Each candle is an OHLC bar. Support/resistance horizontal lines drawn.
    """
    candles = data.get("candles", [])
    if len(candles) < 5:
        logger.warning("CHARTS: Not enough candle data for %s (%d candles)", symbol, len(candles))
        return None

    try:
        import pandas as pd

        df = pd.DataFrame(candles)
        df["t"] = pd.to_datetime(df["t"])
        df = df.sort_values("t").reset_index(drop=True)

        opens  = df["o"].values
        highs  = df["h"].values
        lows   = df["l"].values
        closes = df["c"].values
        xs     = np.arange(len(df))

        fig, ax = plt.subplots(figsize=(7, 2.6))
        _apply_dark_style(fig, [ax])

        # Draw OHLC candles
        bar_width = 0.4
        for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
            color = GREEN if c >= o else RED
            ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=2)
            rect = plt.Rectangle(
                (i - bar_width / 2, min(o, c)),
                bar_width,
                abs(c - o) if abs(c - o) > 0 else (h - l) * 0.01,
                color=color, zorder=3,
            )
            ax.add_patch(rect)

        # Prior close horizontal line
        prev_close = data.get("prev_close")
        if prev_close:
            ax.axhline(prev_close, color=MUTED_CLR, linewidth=0.8, linestyle="--", alpha=0.7, zorder=1)

        # Current price label at right
        current_price = closes[-1]
        pct = data.get("pct_change", 0)
        sign = "+" if pct >= 0 else ""
        label_color = GREEN if pct >= 0 else RED
        ax.text(
            len(df) + 1, current_price,
            f"{current_price:,.1f} ({sign}{pct:.2f}%)",
            color=label_color, fontsize=7, va="center", ha="left",
            fontweight="bold",
        )

        clean_symbol = symbol.replace("=F", "")
        name = data.get("name", clean_symbol)
        ax.set_title(f"{clean_symbol}  ·  {name}  (5 Min)", fontsize=8, color=TEXT_CLR, loc="left", pad=4)
        ax.set_xlim(-1, len(df) + 14)

        # X-axis: HH:MM labels every 12 candles (= 1 hour at 5m bars)
        tick_step = 12
        tick_idxs = list(range(0, len(df), tick_step))
        tick_labels = [df["t"].iloc[i].strftime("%H:%M") for i in tick_idxs]
        ax.set_xticks(tick_idxs)
        ax.set_xticklabels(tick_labels, fontsize=6, color=TEXT_CLR)
        ax.tick_params(axis="x", colors=TEXT_CLR, length=2, pad=2)

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

        fig.tight_layout(pad=0.5)
        path = os.path.join(chart_dir, f"premarket_mini_{clean_symbol.lower()}.png")
        return _save(fig, path)

    except Exception as e:
        logger.error("CHARTS: premarket_mini failed for %s: %s", symbol, e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 2. Normalized $10K portfolio performance
# ---------------------------------------------------------------------------

def chart_normalized_growth(performance_data: dict, chart_dir: str) -> Optional[str]:
    """Generate the $10K normalized growth chart for all configured tickers.

    Each ticker's line starts at $10,000 on day 1 and grows by daily returns.
    Sorted legend by current value (best at top).
    """
    if not performance_data:
        return None

    try:
        import pandas as pd

        fig, ax = plt.subplots(figsize=(10, 5))
        _apply_dark_style(fig, [ax])

        sorted_tickers = sorted(
            performance_data.items(),
            key=lambda x: x[1].get("value_10k", 10000),
            reverse=True,
        )

        for ticker, data in sorted_tickers:
            closes = data.get("closes", [])
            if len(closes) < 2:
                continue

            dates  = [c["date"] for c in closes]
            prices = [c["close"] for c in closes]
            base   = prices[0]
            normed = [10000 * (p / base) for p in prices]

            color = TICKER_COLORS.get(ticker, "#cccccc")
            ax.plot(range(len(normed)), normed, color=color, linewidth=1.8,
                    label=ticker, zorder=3)

            # Label at right edge
            val = normed[-1]
            sign = "+" if val >= 10000 else ""
            ax.text(
                len(normed) - 1 + 0.3, val,
                f"{ticker}  ${val:,.0f}",
                color=color, fontsize=7.5, va="center", ha="left", fontweight="bold",
            )

        ax.axhline(10000, color=MUTED_CLR, linewidth=1.0, linestyle="--",
                   alpha=0.8, zorder=1, label="$10K breakeven")

        ax.set_title("$10,000 · Past 30 Days", fontsize=11, color=TEXT_CLR, pad=10)
        ax.set_ylabel("Portfolio Value ($)", fontsize=8, color=TEXT_CLR)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
        ax.set_xticks([])
        ax.set_xlim(-0.5, len(list(performance_data.values())[0].get("closes", [])) + 8)

        # Shading: above $10K = green tint, below = red tint
        ylim = ax.get_ylim()
        ax.fill_between(
            range(len(list(performance_data.values())[0].get("closes", []))),
            10000, ylim[1],
            alpha=0.04, color=GREEN, zorder=0,
        )
        ax.fill_between(
            range(len(list(performance_data.values())[0].get("closes", []))),
            ylim[0], 10000,
            alpha=0.04, color=RED, zorder=0,
        )

        fig.tight_layout(pad=0.8)
        path = os.path.join(chart_dir, "normalized_growth_30d.png")
        return _save(fig, path)

    except Exception as e:
        logger.error("CHARTS: normalized_growth failed: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 3. Market regime ratio charts (3-panel)
# ---------------------------------------------------------------------------

def chart_market_regime(regime_data: dict, chart_dir: str) -> Optional[str]:
    """Generate a 3-panel regime ratio chart.

    Each panel shows one ratio (SPY/TLT, GLD/SPY, DBC/TLT) as a line chart
    with HMA30 overlay and a trend direction label.
    """
    if not regime_data:
        return None

    try:
        labels = list(regime_data.keys())
        n = len(labels)
        if n == 0:
            return None

        fig, axes = plt.subplots(1, n, figsize=(4.5 * n, 3))
        if n == 1:
            axes = [axes]
        _apply_dark_style(fig, axes)

        for ax, label in zip(axes, labels):
            data = regime_data[label]
            closes_raw = data.get("closes", [])
            if not closes_raw:
                ax.set_title(label, fontsize=9, color=MUTED_CLR)
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", color=MUTED_CLR)
                continue

            xs     = range(len(closes_raw))
            ratios = [c.get("ratio", 0) for c in closes_raw]
            hmas   = [c.get("hma") for c in closes_raw]

            # Raw ratio line (thin, muted)
            ax.plot(xs, ratios, color=BLUE, linewidth=0.8, alpha=0.5, zorder=2)

            # HMA30 line (thick, colored by trend)
            valid_hmas = [(i, h) for i, h in enumerate(hmas) if h is not None]
            if valid_hmas:
                hx = [v[0] for v in valid_hmas]
                hy = [v[1] for v in valid_hmas]
                trend = data.get("trend", "flat")
                hma_color = GREEN if trend == "up" else RED if trend == "down" else MUTED_CLR
                ax.plot(hx, hy, color=hma_color, linewidth=2.0, zorder=3, label="HMA30")

                # Trend label
                trend_symbol = "↑" if trend == "up" else "↓" if trend == "down" else "→"
                ax.text(
                    0.97, 0.93, f"{trend_symbol} {trend.upper()}",
                    transform=ax.transAxes, ha="right", va="top",
                    color=hma_color, fontsize=9, fontweight="bold",
                )

            ax.set_title(label, fontsize=9, color=TEXT_CLR, pad=4)
            ax.set_xticks([])
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.3f}"))
            ax.yaxis.set_major_locator(mticker.MaxNLocator(4))

        fig.suptitle("Market Regime Ratios  ·  HMA30", fontsize=10,
                     color=TEXT_CLR, y=1.02)
        fig.tight_layout(pad=0.8)
        path = os.path.join(chart_dir, "market_regime.png")
        return _save(fig, path)

    except Exception as e:
        logger.error("CHARTS: market_regime failed: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 4. Per-ratio 1-minute mini charts  (replaces 3-panel market_regime)
# ---------------------------------------------------------------------------

def _hma_series(series, period: int):
    """Hull Moving Average on a pandas Series."""
    import math as _math
    half = max(period // 2, 1)
    sqrt_n = max(int(_math.sqrt(period)), 1)

    def wma(s, p):
        w = np.arange(1, p + 1, dtype=float)
        return s.rolling(p).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

    return wma(2 * wma(series, half) - wma(series, period), sqrt_n)


def chart_regime_ratio_mini(label: str, num_ticker: str, den_ticker: str, chart_dir: str) -> Optional[tuple]:
    """Generate a 1-hour bar ratio chart with HMA30 overlay.

    Fetches 60d of 1-hour data for both tickers so HMA30 is fully pre-populated
    before the visible display window. Trend = ratio above/below HMA30.

    Returns (file_path, trend_str) where trend_str is 'up' | 'down' | 'flat',
    or None on failure.
    """
    try:
        import yfinance as yf
        import pandas as pd
        import math as _math

        # Fetch 60d of 1h data — enough to pre-populate HMA30 before display window
        num_hist = yf.Ticker(num_ticker).history(period="60d", interval="1h")["Close"]
        den_hist = yf.Ticker(den_ticker).history(period="60d", interval="1h")["Close"]

        df = pd.DataFrame({"num": num_hist, "den": den_hist}).dropna()
        if len(df) < 35:
            logger.warning("CHARTS: Not enough 1h data for regime ratio %s", label)
            return None

        df = df.copy()
        df["ratio"] = df["num"] / df["den"]

        # Compute HMA30 on full history so it is populated at the start of display window
        hma_period = 30
        df["hma"] = _hma_series(df["ratio"], hma_period)

        # Trim to last 60 bars for display — HMA30 is already valid throughout
        display_bars = 60
        df = df.tail(display_bars)

        xs = np.arange(len(df))
        ratios = df["ratio"].values
        hma_vals = df["hma"].values

        fig, ax = plt.subplots(figsize=(5, 2.6))
        _apply_dark_style(fig, [ax])

        ax.plot(xs, ratios, color=BLUE, linewidth=0.8, alpha=0.5, zorder=2)

        trend_str = "flat"
        valid_idx = [i for i, v in enumerate(hma_vals) if v is not None and not _math.isnan(float(v))]
        if len(valid_idx) >= 2:
            hx = valid_idx
            hy = [float(hma_vals[i]) for i in hx]
            # Trend: ratio above HMA = bullish (green), below = bearish (red)
            ratio_last = float(ratios[-1])
            hma_last = hy[-1]
            above_hma = ratio_last > hma_last
            trend_str = "up" if above_hma else "down"
            hma_color = GREEN if above_hma else RED
            ax.plot(hx, hy, color=hma_color, linewidth=2.0, zorder=3)
            trend_sym = "\u2191" if above_hma else "\u2193"
            ax.text(0.97, 0.93, trend_sym, transform=ax.transAxes, ha="right", va="top",
                    color=hma_color, fontsize=11, fontweight="bold")

        ax.set_title(f"{label}  \u00b7  HMA{hma_period}  (1 Hr)", fontsize=8, color=TEXT_CLR, loc="left", pad=4)
        ax.set_xlim(-1, len(df) + 2)

        # X-axis: every 10 bars (~10 hours), show date + hour
        tick_step = 10
        tick_idxs = list(range(0, len(df), tick_step))
        tick_labels = [df.index[i].strftime("%m/%d %H:%M") for i in tick_idxs]
        ax.set_xticks(tick_idxs)
        ax.set_xticklabels(tick_labels, fontsize=6, color=TEXT_CLR, rotation=15, ha="right")
        ax.tick_params(axis="x", colors=TEXT_CLR, length=2, pad=2)

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.4f}"))
        ax.yaxis.set_major_locator(mticker.MaxNLocator(4))

        fig.tight_layout(pad=0.5)
        safe_label = label.lower().replace("/", "_")
        path = os.path.join(chart_dir, f"regime_{safe_label}.png")
        return _save(fig, path), trend_str

    except Exception as e:
        logger.error("CHARTS: regime_ratio_mini failed for %s: %s", label, e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 5. Sector Rotation RRG chart
# ---------------------------------------------------------------------------

_QUADRANT_META = {
    "Leading":   {"color": GREEN,  "x_range": (100, None), "y_range": (100, None), "label_pos": (101, 101)},
    "Weakening": {"color": GOLD,   "x_range": (100, None), "y_range": (None, 100), "label_pos": (101,  99)},
    "Lagging":   {"color": RED,    "x_range": (None, 100), "y_range": (None, 100), "label_pos": ( 99,  99)},
    "Improving": {"color": BLUE,   "x_range": (None, 100), "y_range": (100, None), "label_pos": ( 99, 101)},
}


def chart_sector_rrg(rrg_data: dict, chart_dir: str) -> Optional[str]:
    """Generate the Relative Rotation Graph (RRG) chart.

    Each sector ETF is plotted as a dot on the RS-Ratio (x) vs RS-Momentum (y)
    plane, centered at 100,100. 4 quadrants: Leading, Weakening, Lagging, Improving.
    Tails show the last 5 weekly positions as a fading line.
    """
    if not rrg_data:
        return None

    try:
        # --- Auto-scale: collect all x/y values across current + tail points ---
        all_x = [100.0]
        all_y = [100.0]
        for etf_d in rrg_data.values():
            if etf_d.get("rs_ratio") is not None:
                all_x.append(float(etf_d["rs_ratio"]))
            if etf_d.get("rs_momentum") is not None:
                all_y.append(float(etf_d["rs_momentum"]))
            for t in etf_d.get("tail", []):
                if t.get("rs_ratio") is not None:
                    all_x.append(float(t["rs_ratio"]))
                if t.get("rs_momentum") is not None:
                    all_y.append(float(t["rs_momentum"]))

        x_pad = 2.0
        y_pad = 0.75
        # Scale each axis independently to its own data range
        half_x = max((max(all_x) - min(all_x)) / 2 + x_pad, 1.0)
        half_y = max((max(all_y) - min(all_y)) / 2 + y_pad, 1.0)
        cx = (max(all_x) + min(all_x)) / 2
        cy = (max(all_y) + min(all_y)) / 2
        x_lo = cx - half_x
        x_hi = cx + half_x
        y_lo = cy - half_y
        y_hi = cy + half_y

        fig, ax = plt.subplots(figsize=(8, 7))
        _apply_dark_style(fig, [ax])

        # Quadrant background shading (uses dynamic bounds)
        for q, meta in _QUADRANT_META.items():
            x0 = 100 if meta["x_range"][0] == 100 else x_lo
            x1 = x_hi if meta["x_range"][0] == 100 else 100
            y0 = 100 if meta["y_range"][0] == 100 else y_lo
            y1 = y_hi if meta["y_range"][0] == 100 else 100
            ax.fill_between([x0, x1], [y0, y0], [y1, y1],
                            alpha=0.06, color=meta["color"], zorder=0)

        # Center lines
        ax.axhline(100, color=GRID_CLR, linewidth=1.2, zorder=1)
        ax.axvline(100, color=GRID_CLR, linewidth=1.2, zorder=1)

        # Quadrant labels — positioned near corners with independent x/y insets
        xi = (x_hi - x_lo) * 0.04
        yi = (y_hi - y_lo) * 0.06
        q_labels = [
            (x_hi - xi, y_hi - yi, "LEADING",   GREEN, "right", "top"),
            (x_hi - xi, y_lo + yi, "WEAKENING", GOLD,  "right", "bottom"),
            (x_lo + xi, y_lo + yi, "LAGGING",   RED,   "left",  "bottom"),
            (x_lo + xi, y_hi - yi, "IMPROVING", BLUE,  "left",  "top"),
        ]
        for qx, qy, qlabel, qcolor, ha, va in q_labels:
            ax.text(qx, qy, qlabel, color=qcolor, fontsize=8.5, alpha=0.5,
                    ha=ha, va=va, fontweight="bold", style="italic")

        # Plot each sector
        for etf, data in rrg_data.items():
            rr = data.get("rs_ratio")
            rm = data.get("rs_momentum")
            if rr is None or rm is None:
                continue

            quadrant = data.get("quadrant", "Lagging")
            color = _QUADRANT_META.get(quadrant, {}).get("color", MUTED_CLR)

            # Draw tail (fading line from oldest to newest)
            tail = data.get("tail", [])
            if len(tail) >= 2:
                tail_x = [t.get("rs_ratio", rr) for t in tail]
                tail_y = [t.get("rs_momentum", rm) for t in tail]
                # Full tail as faded line
                ax.plot(tail_x, tail_y, color=color, linewidth=1.2,
                        alpha=0.35, zorder=2)
                # Arrow from second-to-last to last tail point
                if len(tail_x) >= 2:
                    ax.annotate(
                        "", xy=(rr, rm),
                        xytext=(tail_x[-2], tail_y[-2]),
                        arrowprops=dict(
                            arrowstyle="->",
                            color=color,
                            lw=1.5,
                        ),
                        zorder=4,
                    )

            # Current dot
            ax.scatter([rr], [rm], color=color, s=90, zorder=5,
                       edgecolors="white", linewidths=0.5)

            # Label — offset scaled to axis range so labels stay close to dots
            x_range = x_hi - x_lo
            y_range = y_hi - y_lo
            lbl_dx = x_range * 0.015 if rr >= 100 else -x_range * 0.015
            lbl_dy = y_range * 0.025
            ax.text(
                rr + lbl_dx, rm + lbl_dy, etf,
                color=color, fontsize=7.5, fontweight="bold", zorder=6,
                ha="left" if rr >= 100 else "right", va="bottom",
            )

        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)
        ax.set_xlabel("RS-Ratio  (Relative Strength vs SPY)", fontsize=8.5, color=TEXT_CLR)
        ax.set_ylabel("RS-Momentum  (Rate of Change)", fontsize=8.5, color=TEXT_CLR)
        ax.set_title("Sector Rotation  ·  Relative Rotation Graph (RRG)",
                     fontsize=11, color=TEXT_CLR, pad=10)

        # Reference dot at center
        ax.scatter([100], [100], color=MUTED_CLR, s=30, zorder=1, marker="+")

        fig.tight_layout(pad=0.8)
        path = os.path.join(chart_dir, "sector_rrg.png")
        return _save(fig, path)

    except Exception as e:
        logger.error("CHARTS: sector_rrg failed: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_all_charts(
    edition_id: str,
    chart_dir: str,
    premarket_data: dict,
    performance_data: dict,
    regime_data: dict,
    rrg_data: dict,
) -> list[dict]:
    """Generate all charts for an edition. Saves PNGs to chart_dir.

    Returns list of {chart_type, file_path} for each chart successfully generated.
    Saves each chart to the DB via data.save_chart().
    """
    from apps.newsletter.data import save_chart

    os.makedirs(chart_dir, exist_ok=True)
    results = []

    # Pre-market mini candle charts (one per symbol, sorted by pct_change desc)
    sorted_pm = sorted(
        premarket_data.items(),
        key=lambda x: x[1].get("pct_change", 0),
        reverse=True,
    )
    for symbol, data in sorted_pm:
        clean = symbol.replace("=F", "").lower()
        chart_type = f"premarket_mini_{clean}"
        path = chart_premarket_mini(symbol, data, chart_dir)
        if path:
            save_chart(edition_id, chart_type, path)
            results.append({"chart_type": chart_type, "file_path": path})

    # $10K normalized growth
    path = chart_normalized_growth(performance_data, chart_dir)
    if path:
        save_chart(edition_id, "normalized_growth_30d", path)
        results.append({"chart_type": "normalized_growth_30d", "file_path": path})

    # Market regime ratios — one 1-min mini chart per ratio
    for label, rdata in regime_data.items():
        num = rdata.get("numerator")
        den = rdata.get("denominator")
        if not num or not den:
            continue
        safe = label.lower().replace("/", "_")
        chart_type = f"regime_{safe}"
        result = chart_regime_ratio_mini(label, num, den, chart_dir)
        if result:
            path, chart_trend = result
            save_chart(edition_id, chart_type, path)
            results.append({"chart_type": chart_type, "file_path": path, "trend": chart_trend})

    # Sector RRG
    path = chart_sector_rrg(rrg_data, chart_dir)
    if path:
        save_chart(edition_id, "sector_rrg", path)
        results.append({"chart_type": "sector_rrg", "file_path": path})

    logger.info("CHARTS: Generated %d charts for edition %s", len(results), edition_id)
    return results
