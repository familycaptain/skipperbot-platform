#!/usr/bin/env python3
"""Backfill the consciousness log from historical chat_turns (§11.8 — zero loss).

One-time, IDEMPOTENT, resumable. Walks ``public.chat_turns`` in ``created_at``
order and appends ``cl-`` events so day one, the log already contains the
family's entire conversational past:

  - a normal pair-row  → TWO ``message`` events: user→skipper, then
    skipper→user (``reply_to``-linked), ``domain=chat``, ``surface=channel``.
  - a ``"[context]"`` pseudo-turn (a proactive/bot notification mirrored into
    chat history by ``chatlog_store.save_notification``) → ONE skipper→user
    ``message`` event, domain derived from the bracket marker.

Source = ``chat_turns`` ONLY. The ``notifications`` table is deliberately NOT
walked: its rows are delivered-mirrors of the same messages that appear in
chat_turns as pseudo-turns — a second source would double the events. (Noted
deviation from §11.8's original wording; single-source keeps events unique.
Bounty digests historically wrote to neither store and are unrecoverable.)

Idempotency: every backfilled event carries ``payload.legacy_id``
(``<c-id>#u`` / ``<c-id>#a``), enforced by the unique expression index
``idx_cl_legacy_id`` — re-running skips duplicates at the database level.

Backfilled rows are pre-attended (``attended_by='backfill'``): history is
record, nothing is owed. Embeddings stay NULL (§11.8 — pair-level embeddings
can't be split; the subconscious re-embeds later; retrieval keeps using
chat_turns' index meanwhile).

Usage (on the box with the DB, project venv):
    python scripts/backfill_consciousness_log.py [--batch 500] [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_layer.db import fetch_all  # noqa: E402
from app_platform.consciousness import (  # noqa: E402
    domain_for_source_type,
    log_event,
)

SKIPPER = "skipper"


def _marker_domain(user_message: str) -> str:
    """Map a '[context]' pseudo-turn marker to a domain tag."""
    marker = user_message.strip()[1:-1] if user_message.strip().startswith("[") else ""
    marker = marker.strip().lower()
    # markers seen in the wild: notification, pm_checkin, reminder_notification,
    # research/print contexts, chores..., onboarding...
    if marker.endswith("_notification"):
        marker = marker[: -len("_notification")]
    if marker in ("notification", "context", ""):
        return "system"
    return domain_for_source_type(marker)


def _insert(row: dict, *, dry: bool) -> int:
    """Emit the event(s) for one chat_turns row. Returns events written."""
    cid = row["id"]
    user_msg = row.get("user_message") or ""
    asst_msg = row.get("assistant_message") or ""
    surface = row.get("channel")
    user_id = row["user_id"]
    written = 0

    is_pseudo = user_msg.startswith("[") and user_msg.endswith("]")

    if is_pseudo:
        # proactive/bot message mirrored into chat history
        if asst_msg:
            if not dry:
                _safe_insert(
                    kind="message", who_from=SKIPPER, who_to=user_id,
                    domain=_marker_domain(user_msg), surface=surface,
                    content=asst_msg,
                    payload={"legacy_id": f"{cid}#a", "chat_turn_id": cid,
                             "marker": user_msg[:60]},
                )
            written += 1
        return written

    inbound_id = None
    if user_msg:
        if not dry:
            r = _safe_insert(
                kind="message", who_from=user_id, who_to=SKIPPER,
                domain="chat", surface=surface, content=user_msg,
                payload={"legacy_id": f"{cid}#u", "chat_turn_id": cid},
            )
            inbound_id = (r or {}).get("id")
        written += 1
    if asst_msg:
        if not dry:
            _safe_insert(
                kind="message", who_from=SKIPPER, who_to=user_id,
                domain="chat", surface=surface, content=asst_msg,
                reply_to=inbound_id,
                payload={"legacy_id": f"{cid}#a", "chat_turn_id": cid},
            )
        written += 1
    return written


def _safe_insert(**kwargs):
    """log_event that treats a legacy_id unique-violation as an idempotent skip."""
    try:
        return log_event(pre_attended_by="backfill", **kwargs)
    except Exception as exc:  # unique violation on idx_cl_legacy_id == already backfilled
        if "idx_cl_legacy_id" in str(exc) or "duplicate key" in str(exc):
            return None
        raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_rows = 0
    total_events = 0
    last_key = None  # (created_at, id) keyset pagination — stable, resumable

    while True:
        if last_key is None:
            rows = fetch_all(
                "SELECT id, user_id, user_message, assistant_message, channel, created_at "
                "FROM chat_turns ORDER BY created_at ASC, id ASC LIMIT %s",
                (args.batch,),
            )
        else:
            rows = fetch_all(
                "SELECT id, user_id, user_message, assistant_message, channel, created_at "
                "FROM chat_turns WHERE (created_at, id) > (%s, %s) "
                "ORDER BY created_at ASC, id ASC LIMIT %s",
                (last_key[0], last_key[1], args.batch),
            )
        if not rows:
            break
        for row in rows:
            total_events += _insert(row, dry=args.dry_run)
            total_rows += 1
        last_key = (rows[-1]["created_at"], rows[-1]["id"])
        print(f"  … {total_rows} chat_turns walked, {total_events} events "
              f"{'(dry-run, not written)' if args.dry_run else 'written/skipped-if-existing'}")

    print(f"DONE: {total_rows} chat_turns → {total_events} consciousness events"
          f"{' (DRY RUN)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
