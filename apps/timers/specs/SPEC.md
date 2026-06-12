# Timers — Spec

Short, in-memory countdown timers that fire a single notification when they
expire. Optional, headless (no UI), no database.

## Model

Timers are **ephemeral**. Each active timer is one `asyncio.Task` held in an
in-process registry (`store._TIMERS`), keyed by a `tm-xxxxxxxx` id. There is **no
database table** — timers evaporate on restart. The only persisted artifact is
the notification that fires on expiry. Because of that, this app has **no
migrations and owns no entity types**.

State is mutated only from the asyncio event loop, so no locking is needed.

## Modules

- `store.py` — the in-memory registry (`register` / `get` / `pop` /
  `list_active` / `seconds_remaining` / `clear`).
- `scheduler.py` — `start_timer` (creates the task), `_run_timer` (sleep → fire
  notification → immediate delivery), `cancel`, and `shutdown_all_timers`
  (graceful drain so nothing fires during shutdown).
- `tools.py` — the chat/voice tools: `start_timer`, `list_timers`,
  `cancel_timer`.

## Firing

On expiry, `_run_timer` calls `app_platform.notifications.create_notification`
(`source_type="timer"`, `channel="all"`) and then triggers
`apps.notifications.delivery.deliver_pending_notifications()` immediately, so a
sub-minute timer doesn't wait up to ~30s for the reminder loop's tick.

## Platform integration

- **Tools/routing**: discovered from `tools.py` + the manifest `tool_category`
  (no `tool_routes.json` entry needed).
- **Shutdown**: the platform's FastAPI lifespan calls
  `apps.timers.scheduler.shutdown_all_timers()` inside a guarded `try/except`, so
  the platform runs fine when this optional app isn't installed. No startup loop
  is needed — timers are created on demand by `start_timer`.

## Dependencies

- `app_platform.notifications` — to fire the expiry notification.
- `app_platform.time` — timezone-aware clock for `expires_at` / remaining time.
- `data_layer.users` — validates the recipient exists before starting a timer.

## Sizing guidance (for the agent)

Sub-minute / single-digit-minute countdowns → timer. Wall-clock times or
anything 30+ minutes out → reminder (durable). See `guide.md`.
