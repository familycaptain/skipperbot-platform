"""Pure rendering helpers for the web-chat history (issue #8).

Turns the stored chat turns into a flat, render-ready message list in which every
message carries a ``ts`` and a ``date_separator`` row is inserted at each calendar-date
boundary. All date bucketing + the relative ``Today``/``Yesterday`` labels are computed
in ONE timezone (the user's browser zone, passed in) so the live view and a reload agree.

This module is intentionally stdlib-only (no DB / no third-party imports) so it is a pure,
deterministically unit-testable seam for an otherwise frontend feature — the box-2 bound
tests run under a stdlib `python -m unittest`.
"""

from __future__ import annotations

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

_UTC = ZoneInfo("Etc/UTC")


def _safe_zone(tz: str | None) -> ZoneInfo:
    """Resolve an IANA tz name, falling back to UTC on absent/invalid input.

    The tz comes from untrusted client input, so a bad value must never raise."""
    if not tz:
        return _UTC
    try:
        return ZoneInfo(tz)
    except Exception:
        return _UTC


def _local_date(iso_ts: str, zone: ZoneInfo) -> date | None:
    """The local calendar date (in ``zone``) of an ISO timestamp, or None if unparseable."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(zone).date()


def relative_label(sep_date: date, current_date: date) -> str:
    """Relative label for a separator date vs the current date.

    Pure function of the two calendar dates: 'Today', 'Yesterday', else an absolute
    date like 'June 14, 2026'. Because it depends on ``current_date``, an open window
    can re-derive labels when the clock rolls over midnight (operator's Gate-1 note)."""
    if sep_date == current_date:
        return "Today"
    if sep_date == current_date - timedelta(days=1):
        return "Yesterday"
    # Cross-platform absolute date ('June 14, 2026') without %-d / %B locale surprises.
    months = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")
    return f"{months[sep_date.month - 1]} {sep_date.day}, {sep_date.year}"


def _turn_messages(turn: dict) -> list[dict]:
    """Expand one stored turn into its render bubbles (without ts/separators)."""
    out: list[dict] = []
    um = (turn.get("user_message") or "").strip()
    am = turn.get("assistant_message") or ""
    # Bot-initiated turn: user_message is a '[reminder_notification]'-style marker.
    if um.startswith("[") and um.endswith("]"):
        if am:
            out.append({"role": "notification", "content": am, "source": um.strip("[]")})
        return out
    if um:
        out.append({"role": "user", "content": um})
    for tc in (turn.get("tool_calls") or []):
        out.append({"role": "tool_call", "toolName": tc.get("name"),
                    "toolArgs": tc.get("args") or {}})
    if am:
        out.append({"role": "bot", "content": am})
    return out


def render_chat_history(turns: list[dict], now: datetime, tz: str | None) -> list[dict]:
    """Flatten ``turns`` (oldest→newest, each with an ISO ``timestamp``) into a render
    list where every message has a ``ts`` and a ``date_separator`` precedes the first
    message of each calendar date (in ``tz``), including a leading one.

    Pure: no DB / network — operates only on its arguments.
    """
    zone = _safe_zone(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_UTC)
    current_date = now.astimezone(zone).date()

    messages: list[dict] = []
    prev_key: str | None = None
    for turn in turns:
        ts = turn.get("timestamp") or ""
        d = _local_date(ts, zone)
        key = d.isoformat() if d else ""
        bubbles = _turn_messages(turn)
        if not bubbles:
            continue
        if key != prev_key:
            label = relative_label(d, current_date) if d else key
            messages.append({"role": "date_separator", "date": key, "label": label})
            prev_key = key
        for b in bubbles:
            b["ts"] = ts
            messages.append(b)
    return messages
