# System

The platform admin panel — health, metrics, and version info, plus a graceful
restart/deploy control.

## What you can do
- **See platform health** — record counts, server status, version/build, jobs.
- **Restart & update** — the power control drains in-flight work, then (with the
  deploy watcher installed) pulls the latest code and recycles the stack.
- **Ask Skipper** — "how's the system doing?", or "how many records do we have?".

## Tips
- For configuration (timezone, models, integrations), use the **Settings** app —
  System is read-only telemetry plus the restart control.
