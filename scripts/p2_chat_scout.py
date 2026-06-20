"""Pass-2 deeper bug-scout (box2): drive realistic family-app chat operations, capture reply +
tool_calls, so I (Claude) can judge each for bugs. Bug-scout mode — findings get GitHub issues, no
fixes. Run on box 2 (uses ~/box2_drive.py)."""
import subprocess, json, sys, os
DRIVE = os.path.expanduser("~/box2_drive.py")

def say(msg):
    out = subprocess.run([sys.executable, DRIVE, "say", msg], capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except Exception:
        return {"skipper": (out.stdout or out.stderr)[:200], "tool_calls": []}

# (label, message). /clear resets the session between independent probes.
PROBES = [
    ("clear", "/clear"),
    ("create-reminder", "remind me to call the dentist next Tuesday at 3pm"),
    ("dup-check (low-signal after a write)", "thanks!"),
    ("clear", "/clear"),
    ("read-reminders", "what reminders do I have?"),
    ("missing-time", "remind me to water the plants"),
    ("clear", "/clear"),
    ("list-create", "add milk and eggs to the grocery list"),
    ("list-read", "what's on the grocery list?"),
    ("chores-read", "what chores do Emma and Jack have this week?"),
    ("chore-create", "add a chore: Jack takes out the trash on Mondays"),
    ("delete", "delete my dentist reminder"),
    ("ambiguous-that", "add that to my to-do list"),
]

for label, msg in PROBES:
    d = say(msg)
    rep = (d.get("skipper") or "").replace("\n", " ")
    print(f"[{label}] «{msg}»")
    print(f"   -> {rep[:220]}")
    if d.get("tool_calls"):
        print(f"   tool_calls: {d['tool_calls']}")
