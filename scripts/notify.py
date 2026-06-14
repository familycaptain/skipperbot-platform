#!/usr/bin/env python
"""Send the operator a Pushover push from the command line.

Credentials come from .env (PUSHOVER_TOKEN / PUSHOVER_USER / PUSHOVER_DEVICE).
Used by the `notify` Claude skill, by the Evolve engine at a gate, and by anyone
who wants a quick ping ("Claude is done; nothing is running").

    python scripts/notify.py "Done — branch ready for review"
    python scripts/notify.py --title "Evolve · Gate 2" --priority 1 "Weather fix needs approval"
    echo "long message" | python scripts/notify.py --title "Report"
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for line in open(os.path.join(ROOT, ".env")) if os.path.exists(os.path.join(ROOT, ".env")) else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Load pushover_tool.py DIRECTLY (not `from tools...`): the tools package __init__
# eagerly imports every tool, which pulls in the DB stack (psycopg2) we don't have here.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("_pushover_direct", os.path.join(ROOT, "tools", "pushover_tool.py"))
_pd = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_pd)
send_pushover_direct = _pd.send_pushover_direct


def main():
    ap = argparse.ArgumentParser(description="Send a Pushover push (creds from .env).")
    ap.add_argument("message", nargs="?", help="message text (or pipe via stdin)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--priority", type=int, default=0, help="-2..2 (2=emergency)")
    ap.add_argument("--url", default=None)
    ap.add_argument("--url-title", default=None)
    args = ap.parse_args()
    message = args.message or (sys.stdin.read() if not sys.stdin.isatty() else "")
    if not (message or "").strip():
        ap.error("no message (give an argument or pipe via stdin)")
    status = send_pushover_direct(message, title=args.title, priority=args.priority,
                                  url=args.url, url_title=args.url_title)
    print(status)
    sys.exit(0 if status.startswith("Pushover sent") else 1)


if __name__ == "__main__":
    main()
