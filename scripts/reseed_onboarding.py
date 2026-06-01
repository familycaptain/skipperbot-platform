#!/usr/bin/env python
"""Re-seed the onboarding goal into an EXISTING database (operator tool).

Tracked (unlike private/backpopulate_onboarding.py) so it deploys via git pull
and is runnable in the container without copying files around. Reuses the exact
first-install seed from scripts/init_db.py so it stays in lockstep.

Run in the container:
    docker compose exec agent python scripts/reseed_onboarding.py
    docker compose exec agent python scripts/reseed_onboarding.py --reset

Default is idempotent (skips if onboarding is already seeded). --reset deletes
the previously-seeded onboarding goal and clears the seed flag first, so the
seed runs fresh — use it to re-test onboarding or pick up reworded seed content.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-seed onboarding into an existing database.")
    ap.add_argument("--reset", action="store_true",
                    help="Delete the prior onboarding goal + clear the seed flag, then re-seed.")
    args = ap.parse_args()

    if args.reset:
        from app_platform import config as pc
        flag = pc.get("onboarding_seeded", scope="app:goals") or {}
        gid = flag.get("goal_id")
        if gid:
            try:
                from apps.goals.store import delete_item
                print(f"reset: {delete_item(gid, 'skipper')}")
            except Exception as e:  # noqa: BLE001
                print(f"reset: could not delete prior onboarding goal {gid}: {e}")
        print("reset: cleared the onboarding_seeded flag"
              if pc.delete("onboarding_seeded", scope="app:goals")
              else "reset: no onboarding_seeded flag was set")

    import init_db
    init_db._seed_onboarding(verbose=True)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
