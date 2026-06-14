---
name: notify
description: >
  Send the operator a Pushover push notification — use when you finish work and are
  about to stop (so an idle session doesn't sit unnoticed), or when something needs
  the operator's attention/decision. Credentials come from .env (PUSHOVER_TOKEN /
  PUSHOVER_USER / PUSHOVER_DEVICE).
allowed-tools: Bash(python3 scripts/notify.py*)
---

# Notify the operator (Pushover)

Sends a push straight to the operator's phone via the Pushover API, using the keys in
`.env`. No platform DB needed — works from box 1 and dev-mint.

Send a ping when you stop working:

```bash
python3 scripts/notify.py --title "Claude Code" "Done — feature/x is committed and the suite is green. Nothing is running."
```

Flag something that needs a human decision (higher priority shows through):

```bash
python3 scripts/notify.py --title "Evolve · Gate 2" --priority 1 "Weather ZIP fix validated on box 2 — approve to merge?"
```

Options: `--title`, `--priority -2..2` (2 = emergency, repeats until acknowledged),
`--url` / `--url-title` (deep link). The message can also be piped via stdin.

If you see "Pushover not configured", the operator needs to add `PUSHOVER_TOKEN` and
`PUSHOVER_USER` (and optionally `PUSHOVER_DEVICE`) to `.env`.
