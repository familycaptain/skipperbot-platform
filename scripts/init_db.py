"""
init_db.py — First-run database initialization.

Reads SKIPPERBOT_DB_DSN from .env, connects, creates the pgvector extension
if missing, and runs the platform baseline migration (migrations/000_baseline.sql)
plus any unrun per-app migrations discovered under apps/<id>/migrations/.

Usage:
    python scripts/init_db.py

This is what `docker compose up` runs internally before starting the agent;
native installs run it once before first `python agent.py`.

Placeholder — full implementation lands in Chunk 2.
"""

import sys


def main() -> int:
    print("scripts/init_db.py — placeholder. Full implementation in Chunk 2.")
    print("For now, the agent itself handles DB initialization on first boot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
