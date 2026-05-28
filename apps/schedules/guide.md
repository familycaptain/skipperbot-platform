# Schedules — Tool Guide

> **Sub-chunk 8a placeholder.** Real content lands in sub-chunk 8e when
> `prompts/guides/schedules.md` moves here.

## What this app owns

Recurring events + chores + maintenance + auto + school + medical +
general. The recurrence engine (RRULE, cron, daily/weekly/monthly/
yearly, interval, usage-based) and the completion log.

## When to reach for these

Schedules currently has **no chat tools** — its chat surface lives
inside the goals / reminders / todo tools that reference schedules
via the `app_platform.schedules` shim. The desktop SchedulesApp and
the REST endpoints under `/api/apps/schedules/` are the direct
interaction surface.

If you're an LLM and the user says "what chores are due this week?",
prefer the goals / reminders queries — they pull from schedules
under the hood.

## What this app does NOT own

- **One-shot reminders** with a fire time → that's the **Reminders** app.
- **Tasks** with assignees + due dates → that's the **Goals** app.
- **Notifications delivery** → that's the **Notifications** app. The
  schedules notifier writes notification rows through
  `app_platform.notifications.create_notification`; the notifications
  delivery loop on the same tick dispatches them.
