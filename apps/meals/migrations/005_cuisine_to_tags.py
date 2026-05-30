"""Migration 005: Convert meal cuisine values to tags.

For each meal with a non-null cuisine, add that cuisine (lowercased) to the
meal's tags JSONB array if not already present. This consolidates cuisine and
tags into a single unified tag system.
"""
import json
import os
from dotenv import load_dotenv
load_dotenv(override=True)

from app_platform.db import fetch_all_in_schema, execute_in_schema

SCHEMA = "app_meals"


def run():
    meals = fetch_all_in_schema(
        SCHEMA,
        "SELECT id, cuisine, tags FROM meals WHERE cuisine IS NOT NULL AND cuisine != ''",
    )
    updated = 0
    for row in meals:
        cuisine = (row.get("cuisine") or "").strip().lower()
        if not cuisine:
            continue
        tags = row.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        lower_tags = [t.lower() for t in tags]
        if cuisine not in lower_tags:
            tags.append(cuisine)
            execute_in_schema(
                SCHEMA,
                "UPDATE meals SET tags = %s::jsonb WHERE id = %s",
                (json.dumps(tags), row["id"]),
            )
            updated += 1

    print(f"005_cuisine_to_tags: migrated cuisine to tags for {updated} meal(s).")


if __name__ == "__main__":
    run()
