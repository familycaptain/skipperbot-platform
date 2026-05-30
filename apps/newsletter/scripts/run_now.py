#!/usr/bin/env python3
"""Run the newsletter generate-and-send flow immediately.

Uses the same newsletter handler path as the scheduled `newsletter_generate`
job, but runs it directly from the command line for convenience.

Lives inside the Newsletter app so the platform has no dependency on it —
removing the app removes this script with it.

Examples:
    python apps/newsletter/scripts/run_now.py
    python apps/newsletter/scripts/run_now.py --date 2026-04-25
    python apps/newsletter/scripts/run_now.py --date 2026-04-25 --notify-user user
"""

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

# Walk up to the project root so `from apps.newsletter.handlers ...` resolves
# and the .env file is found regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv


def _load_env() -> None:
    load_dotenv(_PROJECT_ROOT / ".env", override=True)


class _ConsoleJobContext:
    """Minimal job context for running a handler outside the job dispatcher."""

    def update_progress(self, pct: int, message: str = "") -> None:
        if message:
            print(f"[{pct:>3}%] {message}")
        else:
            print(f"[{pct:>3}%]")


async def _run(target_date: str | None, notify_user: str) -> str:
    from apps.newsletter.handlers import handle_generate

    job = {
        "id": "manual-newsletter-run",
        "job_type": "newsletter_generate",
        "created_by": notify_user or "manual",
        "notify_user": notify_user,
        "config": {"date": target_date} if target_date else {},
    }
    ctx = _ConsoleJobContext()
    return await handle_generate(job, ctx)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and email Systematic Market Brief immediately.",
    )
    parser.add_argument(
        "--date",
        help="Edition date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--notify-user",
        default="",
        help="Optional app username to receive the completion notification.",
    )
    args = parser.parse_args()

    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            print("ERROR: --date must be in YYYY-MM-DD format", file=sys.stderr)
            return 1

    _load_env()

    try:
        result = asyncio.run(_run(args.date, args.notify_user.strip()))
        print()
        print(result)
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
