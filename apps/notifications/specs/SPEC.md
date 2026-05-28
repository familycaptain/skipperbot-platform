# Notifications — Spec

## Purpose

Cross-app notification fan-out. Every other app that needs to tell a
user something (a reminder fired, a job finished, the PM domain
detected something at-risk, a Trello card moved) records a notification
row here. A background delivery loop picks up undelivered rows and
dispatches them through the registered channels (Discord DM, Pushover,
WebSocket, chat log, FCM mobile push).

This is a **required core app** — almost every other Skipperbot app
depends on it. The platform refuses to start without it.

## Data Model

Schema: `app_notifications`. One table, one entity-type prefix.

### `notifications`

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `n-{hex8}` |
| `recipient` | `text NOT NULL` | canonical user name |
| `message` | `text NOT NULL` | what to tell the user |
| `source_type` | `text NOT NULL DEFAULT ''` | e.g. `"reminder"`, `"job"`, `"system"`, `"agent"` |
| `source_id` | `text NOT NULL DEFAULT ''` | id of the originating entity |
| `channel` | `text NOT NULL DEFAULT ''` | `"discord"`, `"pushover"`, `"chat"`, `"both"`, or empty (use defaults) |
| `delivered` | `boolean NOT NULL DEFAULT TRUE` | flipped by the delivery loop |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` | |

### Indexes

- `idx_notifications_recipient` on `(recipient)`
- `idx_notifications_source_id` on `(source_id)` `WHERE source_id <> ''`

### Cross-schema reads

Notifications reads from `public.users` only to validate recipients.
Delivery looks up `public.mobile_devices` for FCM push targets. No
writes outside this app's schema except the legacy delivery path.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `n` | Notification | `notifications` |

Declared in `manifest.yaml`; the platform loader registers this in
`public.entity_types` at app-load time.

## Public API for Other Apps

Other apps **do not** import this module directly. They use the
platform shim instead:

```python
from app_platform.notifications import create_notification

create_notification(
    recipient="alice",
    message="Trash day is tomorrow",
    source_type="reminder",
    source_id="r-abc12345",
    channel="discord",  # optional; default channels used if empty
)
```

The shim forwards to `apps.notifications.store.create_notification`.
That indirection lets us swap implementations without touching every
app's call sites.

## Tools

One read-only MCP tool:

- `get_recent_notifications(recipient="", limit=20)` — render the most
  recent notification rows as text. The chat agent uses this to answer
  "did Skipper tell me about X?".

Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/notifications/` by the platform.

- `GET /list?recipient=<user>&limit=<n>` — page through history
- `POST /{id}/delete` — soft-delete (administrative)
- `GET /undelivered` — used by the delivery loop's health check

The desktop NotificationsApp uses these routes; the LLM uses the MCP
tool above, not these routes.

## UI

- **`NotificationsApp`** — desktop app showing recent notifications,
  filterable by recipient + channel.

Lives under `apps/notifications/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `notification.created` | `{id, recipient, source_type, source_id, channel}` |
| `notification.delivered` | `{id, recipient, channel, delivered_at}` |
| `notification.deleted` | `{id, recipient}` |

### Subscribed

None in v1. Other apps publish notifications by direct call (via the
`app_platform.notifications` shim), not by emitting events.

## Delivery Channels

The delivery loop tries the channels in order based on either the
explicit `channel` column or the per-app `default_channels` config:

1. **`discord`** — Discord DM via the `DISCORD_BOT_TOKEN` capability.
   Skipped if Discord isn't configured.
2. **`pushover`** — Pushover push via the `PUSHOVER_USER_KEY` +
   `PUSHOVER_APP_TOKEN` capability (per user).
3. **`fcm`** — Firebase Cloud Messaging push to any registered mobile
   device in `public.mobile_devices`.
4. **`chat`** — Write into the user's chat-history log so the message
   appears the next time they open chat.
5. **`websocket`** — Push to any active web-UI session.

Delivery is fire-and-forget per channel: failures are logged but don't
roll back the notification row. Once any channel succeeds, the row is
marked `delivered = TRUE`.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_notifications.notifications`
- `platform.memory.digest_record` — fires after `create_notification` and `delete_notification`
- `platform.time.now()` — `created_at` + delivery timestamps
- `platform.config.get(key)` — per-app preferences
- `platform.capabilities.is_enabled(...)` — gates each channel at delivery time

## Thinking Domains

None. Notifications is passive infrastructure.

## Optional Dependencies

- **Discord** (`DISCORD_BOT_TOKEN`)
- **Pushover** (`PUSHOVER_USER_KEY` + `PUSHOVER_APP_TOKEN`)
- **FCM** (`FCM_SERVER_KEY`)

Without any of these, delivery falls back to chat-log writes only —
the app still records the notification, the user just sees it the next
time they open chat.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_notifications` schema +
  `notifications` table + indexes. Idempotent.
- `migrations/002_migrate_from_public.sql` (one-shot, idempotent) moves
  rows from `public.notifications` into `app_notifications.notifications`.
  Uses `INSERT ... SELECT ... ON CONFLICT (id) DO NOTHING` with a sanity
  check. Does NOT drop the source table.
- Subsequent migrations (`003+`) add columns, indexes, or constraints as
  the schema evolves.

## Why Notifications Is a Required App

Removing notifications would silently break every cross-app "tell the
user" code path: reminders never fire, jobs never report, the PM domain
never nudges. `core: true` enforces this.
