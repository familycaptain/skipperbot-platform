# System

A health dashboard for your Skipper — how much data it holds, what's running, and
a graceful restart control.

## Overview

System is read-only telemetry plus the power button. It aggregates record counts
across every installed app, database size, the latest job and backup, the
doc-curation cursor, and a process-level snapshot — so you can see at a glance
that everything's healthy. It also hosts the graceful restart control. For
*changing* configuration (timezone, models, integrations), use the **Settings**
app; System just shows status and restarts.

## Screens

- **Health overview.** Record counts per app, DB size, server/version info, and
  the most recent job + backup.
- **Restart control.** A power button that drains in-flight work and restarts the
  agent on the **current code**. It does not pull or update — to pick up new
  code, run `skipper update` on the host (or use the deploy flow).

## Example workflows

**Check on Skipper**
- *In the app:* open System for counts, DB size, and recent job/backup status.
- *Through chat:* "how's the system doing?", "how many records do we have?",
  "when was the last backup?"

**Restart Skipper**
- *In the app:* use the restart control (drains in-flight work first, then
  restarts on the current code).
- *Through chat:* "restart Skipper" (Skipper confirms, then restarts).

## Tips

- System is **read-only** status + the restart control — change settings in **Settings**.
- The restart control is a *restart*, not an update: it bounces the agent on the
  code already on disk. To pull and rebuild new code, run `skipper update` on the
  host (or the deploy flow).

## Your data

System **owns no records of its own** — it reports live counts and status from
the other apps and the database. Nothing here is stored or added to Skipper's
memory; it's a real-time dashboard.
