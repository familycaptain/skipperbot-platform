"""Newsletter Data Layer — Schema-aware CRUD for editions, breadth snapshots,
market snapshots, charts, and config.

Uses the app_newsletter schema via app_platform.db helpers.
"""

import uuid
import logging
from datetime import date, datetime
from psycopg2.extras import Json
from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
)

logger = logging.getLogger(__name__)

SCHEMA = "app_newsletter"

DATETIME_KEYS = ("created_at", "updated_at", "generated_at", "sent_at", "fetch_at")
DATE_KEYS = ("edition_date", "snapshot_date")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _clean_for_json(obj):
    """Recursively coerce numpy scalars, Decimal, and NaN/Inf to JSON-safe Python types.

    PostgreSQL rejects NaN/Infinity as invalid JSON, so they become None (null).
    numpy scalars are converted via .item(). Decimal via float().
    """
    import math
    from decimal import Decimal

    def _sanitize(o):
        if isinstance(o, dict):
            return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_sanitize(v) for v in o]
        if isinstance(o, bool):
            return o
        if isinstance(o, Decimal):
            v = float(o)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if hasattr(o, "item"):  # numpy scalar — .item() returns Python native
            v = o.item()
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            return v
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
            return None
        return o

    return _sanitize(obj)


def _row(r: dict | None) -> dict | None:
    if not r:
        return None
    out = dict(r)
    for k in DATETIME_KEYS:
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = out[k].isoformat()
    for k in DATE_KEYS:
        if k in out and out[k] is not None:
            out[k] = str(out[k])
    return out


def _rows(rs: list[dict]) -> list[dict]:
    return [_row(r) for r in rs]


# ---------------------------------------------------------------------------
# Editions
# ---------------------------------------------------------------------------

def get_edition(edition_id: str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_editions WHERE id = %s",
        (edition_id,),
    ))


def get_edition_by_date(edition_date: date | str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_editions WHERE edition_date = %s",
        (str(edition_date),),
    ))


def list_editions(limit: int = 30) -> list[dict]:
    return _rows(fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_editions ORDER BY edition_date DESC LIMIT %s",
        (limit,),
    ))


def create_edition(edition_date: date | str) -> dict:
    edition_id = _new_id("nl")
    return _row(execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO newsletter_editions (id, edition_date)
           VALUES (%s, %s)
           ON CONFLICT (edition_date) DO UPDATE SET updated_at = now()
           RETURNING *""",
        (edition_id, str(edition_date)),
    ))


def update_edition_status(edition_id: str, status: str, error_msg: str = "") -> None:
    extra = ""
    if status == "generated":
        extra = ", generated_at = now()"
    elif status == "sent":
        extra = ", sent_at = now()"
    execute_in_schema(
        SCHEMA,
        f"UPDATE newsletter_editions SET status = %s, error_msg = %s{extra}, updated_at = now() WHERE id = %s",
        (status, error_msg, edition_id),
    )


def update_edition_content(
    edition_id: str,
    content_md: str = "",
    content_html: str = "",
    best_bet_symbol: str = "",
    best_bet_class: str = "",
    best_bet_reason: str = "",
    regime_label: str = "",
) -> None:
    execute_in_schema(
        SCHEMA,
        """UPDATE newsletter_editions
           SET content_md = %s, content_html = %s,
               best_bet_symbol = %s, best_bet_class = %s,
               best_bet_reason = %s, regime_label = %s,
               updated_at = now()
           WHERE id = %s""",
        (content_md, content_html, best_bet_symbol, best_bet_class,
         best_bet_reason, regime_label, edition_id),
    )


# ---------------------------------------------------------------------------
# Breadth Snapshots
# ---------------------------------------------------------------------------

def get_breadth(snapshot_date: date | str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_breadth WHERE snapshot_date = %s",
        (str(snapshot_date),),
    ))


def get_recent_breadth(days: int = 90) -> list[dict]:
    return _rows(fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM newsletter_breadth
           ORDER BY snapshot_date DESC LIMIT %s""",
        (days,),
    ))


def upsert_breadth(
    snapshot_date: date | str,
    vix: float | None = None,
    sector_breadth_pct: float | None = None,
    sector_momentum: float | None = None,
    adv_issues: int | None = None,
    dec_issues: int | None = None,
    fetch_source: str = "yfinance",
    fetch_error: str = "",
) -> dict | None:
    return _row(execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO newsletter_breadth
               (snapshot_date, vix, sector_breadth_pct, sector_momentum,
                adv_issues, dec_issues, fetch_source, fetch_error)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (snapshot_date) DO UPDATE SET
               vix = EXCLUDED.vix,
               sector_breadth_pct = EXCLUDED.sector_breadth_pct,
               sector_momentum = EXCLUDED.sector_momentum,
               adv_issues = EXCLUDED.adv_issues,
               dec_issues = EXCLUDED.dec_issues,
               fetch_source = EXCLUDED.fetch_source,
               fetch_error = EXCLUDED.fetch_error
           RETURNING *""",
        (str(snapshot_date), vix, sector_breadth_pct, sector_momentum,
         adv_issues, dec_issues, fetch_source, fetch_error),
    ))


# ---------------------------------------------------------------------------
# Market Snapshots
# ---------------------------------------------------------------------------

def save_market_snapshot(
    edition_id: str,
    premarket_data: dict,
    performance_data: dict,
    sector_data: dict,
    regime_data: dict,
    rrg_data: dict,
    movers: list,
) -> dict | None:
    return _row(execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO newsletter_market_snapshots
               (edition_id, premarket_data, performance_data, sector_data,
                regime_data, rrg_data, movers)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (edition_id,
         Json(_clean_for_json(premarket_data)), Json(_clean_for_json(performance_data)),
         Json(_clean_for_json(sector_data)), Json(_clean_for_json(regime_data)),
         Json(_clean_for_json(rrg_data)), Json(_clean_for_json(movers))),
    ))


def get_market_snapshot(edition_id: str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_market_snapshots WHERE edition_id = %s",
        (edition_id,),
    ))


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def save_chart(
    edition_id: str,
    chart_type: str,
    file_path: str,
    width_px: int | None = None,
    height_px: int | None = None,
) -> dict | None:
    return _row(execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO newsletter_charts (edition_id, chart_type, file_path, width_px, height_px)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING *""",
        (edition_id, chart_type, file_path, width_px, height_px),
    ))


def get_charts(edition_id: str) -> list[dict]:
    return _rows(fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_charts WHERE edition_id = %s ORDER BY generated_at",
        (edition_id,),
    ))


def get_chart(edition_id: str, chart_type: str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_charts WHERE edition_id = %s AND chart_type = %s",
        (edition_id, chart_type),
    ))


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------

def list_subscribers(include_inactive: bool = True) -> list[dict]:
    sql = "SELECT * FROM newsletter_subscribers"
    if not include_inactive:
        sql += " WHERE active = true"
    sql += " ORDER BY created_at DESC"
    return _rows(fetch_all_in_schema(SCHEMA, sql))


def get_subscriber(sub_id: str) -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_subscribers WHERE id = %s",
        (sub_id,),
    ))


def add_subscriber(email: str, name: str = "", level: str = "free", notes: str = "") -> dict:
    sub_id = _new_id("ns")
    return _row(execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO newsletter_subscribers (id, email, name, level, notes)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (email) DO UPDATE
               SET active = true, name = EXCLUDED.name, level = EXCLUDED.level,
                   notes = EXCLUDED.notes, updated_at = now()
           RETURNING *""",
        (sub_id, email.strip().lower(), name.strip(), level, notes.strip()),
    ))


def update_subscriber(sub_id: str, **kwargs) -> None:
    allowed = {"name", "level", "active", "notes"}
    sets, params = [], []
    for key, val in kwargs.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        params.append(val)
    if not sets:
        return
    params.append(sub_id)
    execute_in_schema(
        SCHEMA,
        f"UPDATE newsletter_subscribers SET {', '.join(sets)}, updated_at = now() WHERE id = %s",
        tuple(params),
    )


def delete_subscriber(sub_id: str) -> bool:
    execute_in_schema(
        SCHEMA,
        "DELETE FROM newsletter_subscribers WHERE id = %s",
        (sub_id,),
    )
    return True


def get_active_subscriber_emails() -> list[str]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT email FROM newsletter_subscribers WHERE active = true ORDER BY email",
    )
    return [r["email"] for r in rows]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config() -> dict | None:
    return _row(fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM newsletter_config WHERE id = 1",
    ))


def update_config(**kwargs) -> None:
    if not kwargs:
        return
    allowed = {
        "enabled", "delivery_time_et", "email_recipients", "from_address",
        "from_name", "chart_output_dir", "performance_tickers",
        "performance_lookback_days", "product_name", "product_tagline",
        "disclosure_short", "disclosure_long", "primary_signal_label",
        "outlook_label", "test_email",
    }
    sets = []
    params = []
    for key, val in kwargs.items():
        if key not in allowed:
            continue
        if isinstance(val, (list, dict)):
            val = Json(val)
        sets.append(f"{key} = %s")
        params.append(val)
    if not sets:
        return
    params.append(None)
    execute_in_schema(
        SCHEMA,
        f"UPDATE newsletter_config SET {', '.join(sets)}, updated_at = now() WHERE id = 1",
        tuple(params[:-1]),
    )
