#!/usr/bin/env python3
"""One-time cleanup of EXACT-duplicate memories — keep the oldest, delete the copies.

Several paths re-generate byte-identical memories (same ``about`` + same ``content``) — most
visibly the Trello list metadata re-extracted on every digest ("X is a list named Y", "X is
synced to board Z", "X created by rodney"), in many phrasings the pattern-based cleanup
can't catch. This collapses each identical ``(about, content)`` group to a SINGLE row,
keeping the OLDEST by ``created_at``.

Safe: ONLY exact ``(about, content)`` duplicates are removed — a unique fact is never
deleted, only redundant copies of it; one copy of every distinct memory is always kept.

Scope note: this is table-wide (any source), not Trello-only. It does NOT touch the
timestamped ``…(last_sync …)`` rows — those have a unique clock per copy so they aren't
exact duplicates; run ``cleanup_trello_sync_noise.py`` for those.

Usage:
    python3 scripts/cleanup_duplicate_memories.py           # dry-run: count + sample
    python3 scripts/cleanup_duplicate_memories.py --apply   # delete the redundant copies
"""

import argparse
import os
import sys

# Run standalone (`python scripts/cleanup_duplicate_memories.py`): the script's own dir is on
# sys.path, not the repo root, so add the repo root to make `data_layer` importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Redundant copies = every row EXCEPT the oldest in each identical (about, content) group.
_SELECT_REDUNDANT = """
    SELECT id, about, content
    FROM (
        SELECT id, about, content,
               row_number() OVER (
                   PARTITION BY about, content
                   ORDER BY created_at ASC, id ASC
               ) AS rn
        FROM memories
    ) d
    WHERE d.rn > 1
"""

# Atomic equivalent for the actual delete (avoids a select-then-delete race on the live DB).
_DELETE_REDUNDANT = """
    DELETE FROM memories m USING (
        SELECT id FROM (
            SELECT id, row_number() OVER (
                       PARTITION BY about, content
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM memories
        ) t
        WHERE t.rn > 1
    ) d
    WHERE m.id = d.id
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Delete exact-duplicate memories, keeping the oldest of each.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete the redundant copies (default: dry-run).")
    args = ap.parse_args(argv)

    from data_layer.db import fetch_all, execute

    rows = fetch_all(_SELECT_REDUNDANT)
    print(f"Found {len(rows)} redundant duplicate copies "
          f"(keeping the oldest of each identical about+content group).")
    if not rows:
        return 0

    for r in rows[:5]:
        about = r.get("about") or "—"
        print(f"  e.g. [{about}] {(r['content'] or '')[:90]}")
    if len(rows) > 5:
        print(f"  …and {len(rows) - 5} more.")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to delete.")
        return 0

    deleted = execute(_DELETE_REDUNDANT)
    print(f"\nDeleted {deleted} redundant copies. One (oldest) of each distinct memory kept.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
