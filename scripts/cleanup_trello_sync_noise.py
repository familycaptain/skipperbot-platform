#!/usr/bin/env python3
"""One-time cleanup of accumulated Trello sync-noise memories (issue #24).

The ~30s Trello poller used to bake a ``last_sync`` clock into a list memory on every
no-op poll, accumulating ~13k near-duplicate "…synced to the Trello board… (last_sync …)"
rows. The source fix (lists.trello-boards.sync-list no-op skip + platform.memory
digest noise-filter) stops NEW noise; this drains the historical backlog.

PRECONDITION: run only AFTER the source fix is deployed, or the poller regenerates noise
between runs and the "safe to re-run" property breaks.

Safety: selects ONLY rows that satisfy BOTH (a) the bookkeeping phrasing
"synced to the Trello board" AND (b) an ISO-8601 last_sync-style timestamp in the content.
Zero-false-positive is the design priority — a legitimate list memory ("Lowes is on the
shopping list"), an item/price note, or a memory that merely mentions a Trello board
WITHOUT a sync clock is NEVER matched. Low recall against oddly-worded variants is fine:
the source fix already stopped new noise, so any missed rows are bounded and harmless.

Usage:
    python3 scripts/cleanup_trello_sync_noise.py           # dry-run: print match count
    python3 scripts/cleanup_trello_sync_noise.py --apply   # actually delete
"""

import argparse
import os
import re
import sys

# Standalone run puts the script's dir on sys.path, not the repo root — add the repo root
# so `data_layer` imports resolve (`python scripts/cleanup_trello_sync_noise.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (a) bookkeeping phrasing (case-insensitive)
_SYNC_PHRASE = "synced to the trello board"
# (b) an ISO-8601 date-time with a numeric UTC offset or Z (the last_sync clock)
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


def is_sync_noise_memory(content: str) -> bool:
    """True ONLY when the content is Trello sync bookkeeping: it requires BOTH the
    'synced to the Trello board' phrasing AND a last_sync-style ISO timestamp, so it
    cannot over-match a legitimate list memory or a board mention without a clock."""
    if not content:
        return False
    return _SYNC_PHRASE in content.lower() and bool(_TS_RE.search(content))


def _find_matches():
    """Return [(id, content), …] for rows that match the precise predicate. Prefilters
    in SQL on the phrasing, then applies the full (phrase AND timestamp) predicate in
    Python so the timestamp requirement is enforced exactly."""
    from data_layer.db import fetch_all
    rows = fetch_all(
        "SELECT id, content FROM memories WHERE content ILIKE %s",
        ("%synced to the Trello board%",),
    )
    return [(r["id"], r["content"]) for r in rows if is_sync_noise_memory(r["content"])]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Remove accumulated Trello sync-noise memories.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete the matched rows (default: dry-run).")
    args = ap.parse_args(argv)

    matches = _find_matches()
    print(f"Matched {len(matches)} sync-noise memories (precise predicate).")
    if not matches:
        return 0

    for mid, content in matches[:5]:
        print(f"  e.g. {mid}: {content[:100]}")
    if len(matches) > 5:
        print(f"  …and {len(matches) - 5} more.")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to delete.")
        return 0

    from data_layer.db import execute
    ids = [mid for mid, _ in matches]
    deleted = execute("DELETE FROM memories WHERE id = ANY(%s)", (ids,))
    print(f"\nDeleted {deleted} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
