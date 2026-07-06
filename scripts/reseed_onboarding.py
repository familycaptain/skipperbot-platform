#!/usr/bin/env python
"""Re-seed the onboarding GOAL into an EXISTING database (operator tool).

Tracked (unlike private/backpopulate_onboarding.py) so it deploys via git pull
and is runnable in the container without copying files around. It seeds the
onboarding goal + ordered agenda via apps.goals.onboarding.ensure_onboarding()
(the canonical first-run seeder, which needs a primary user to exist), in
addition to init_db._seed_onboarding()'s 'skipper' bot-user seed.

Run in the container:
    docker compose exec agent python scripts/reseed_onboarding.py
    docker compose exec agent python scripts/reseed_onboarding.py --reset

Default is idempotent (ensure_onboarding no-ops if already seeded). --reset
deletes the previously-seeded onboarding goal, clears the seed flag, and
releases the greet-once claim first, so the seed runs fresh AND a re-test
reproduces the first-run arrival greeting. --reset is NON-DESTRUCTIVE ON
FAILURE: if no primary user exists yet it changes nothing (run the first-run
wizard first).
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
                    help="Delete the prior onboarding goal + clear the seed flag + release the "
                         "greet-once claim, then re-seed. No-op if no primary user exists.")
    args = ap.parse_args()

    _NO_PRIMARY_MSG = ("No primary user yet; run the first-run wizard first — nothing reset, "
                       "onboarding goal not seeded.")

    from data_layer.users import get_primary_user
    has_primary = bool(get_primary_user())

    # --reset is NON-DESTRUCTIVE ON FAILURE: the delete/clear/release runs ONLY
    # when the goal will then be reseeded (i.e. a primary user exists). With no
    # primary user, leave the existing goal + flag INTACT rather than delete-then-skip.
    if args.reset:
        if not has_primary:
            print(f"reset: {_NO_PRIMARY_MSG}")
        else:
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
            # Release the greet-once claim so a re-test reproduces the first-run
            # arrival greeting instead of staying suppressed by a stale claim.
            try:
                from apps.goals.onboarding import release_onboarding_greeting
                release_onboarding_greeting()
                print("reset: released the onboarding greet-once claim")
            except Exception as e:  # noqa: BLE001
                print(f"reset: could not release the greet-once claim: {e}")

    # The 'skipper' bot-user seed is always safe + idempotent (by design).
    import init_db
    init_db._seed_onboarding(verbose=True)

    # Seed the onboarding GOAL itself — the whole point of this tool — via the
    # canonical seeder, which requires a primary user to resolve.
    if has_primary:
        from apps.goals.onboarding import ensure_onboarding
        gid = ensure_onboarding()
        print(f"seeded onboarding goal: {gid}")
    else:
        print(_NO_PRIMARY_MSG)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
