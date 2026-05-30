"""Backfill memory records for seed data.

002_seed_from_sheet.sql inserts kids/zones/chores via raw SQL, which
bypasses the data.py functions that call digest_record. This migration
walks the seeded rows once and digests each one so semantic recall
("I dusted my room" → ch-XXX) works on a fresh install too.

Idempotent: skips per-entity if memories already exist for that entity id,
so re-running won't double-up. Run manually with:

    python apps/chores/migrations/004_backfill_memories.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../..")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../..", ".env"))


def _has_memory_for(entity_id: str) -> bool:
    from data_layer.db import get_conn
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM memories WHERE about = %s LIMIT 1",
            (entity_id,),
        )
        return cur.fetchone() is not None


def run():
    from apps.chores import data as _dl
    from app_platform.memory import digest_record

    counts = {"kids": 0, "zones": 0, "chores": 0, "skipped": 0}

    print("Backfilling kid memories...")
    for kid in _dl.list_kids(active_only=False):
        if _has_memory_for(kid["id"]):
            counts["skipped"] += 1
            continue
        digest_record(
            app_id="chores", entity_type="kid", action="created",
            entity_id=kid["id"], record=kid, by="system",
            context_hint="backfill", blocking=True,
        )
        counts["kids"] += 1

    print("Backfilling zone memories...")
    for zone in _dl.list_zones():
        if _has_memory_for(zone["id"]):
            counts["skipped"] += 1
            continue
        members = _dl.get_zone_members(zone["id"])
        rec = dict(zone)
        rec["members"] = [m["kid_name"] for m in members]
        digest_record(
            app_id="chores", entity_type="zone", action="created",
            entity_id=zone["id"], record=rec, by="system",
            context_hint="backfill", blocking=True,
        )
        counts["zones"] += 1

    print("Backfilling chore memories...")
    for chore in _dl.list_chores(active_only=False):
        if _has_memory_for(chore["id"]):
            counts["skipped"] += 1
            continue
        digest_record(
            app_id="chores", entity_type="chore", action="created",
            entity_id=chore["id"], record=_dl._chore_with_zone(chore),
            by="system", context_hint="backfill", blocking=True,
        )
        counts["chores"] += 1

    print(f"Done — backfilled {counts['kids']} kids, {counts['zones']} zones, "
          f"{counts['chores']} chores ({counts['skipped']} already had memories).")


if __name__ == "__main__":
    run()
