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

Mounted at `/api/apps/notifications` by the platform.

- `GET ""?recipient=<user>&limit=<n>` — history for one recipient, newest
  first. Scoped by `scope_user`, so a member sees only their own.
- `POST ""` — record a message for one or more people and deliver it now.
  **Admin only.** See below.
- `GET|POST|DELETE /pushover`, `POST /pushover/test` — per-user Pushover
  opt-in.

The desktop NotificationsApp uses these routes; the LLM uses the MCP
tool above, not these routes.

### `POST /api/apps/notifications` — direct send

The only way to reach a person that does not require running code on the
box. Everything else raises a notification by importing
`app_platform.notifications.create_notification`, which an off-box
caretaker — a monitor loop on another machine, a cron elsewhere — cannot
do.

Auth: a bearer token with the **admin** role. Sending as Skipper to any
member of the household is not something a member's own credential should
be able to do. Off-box callers mint a service token:

```
python3 scripts/service_token.py create caretaker --role admin
# -> SKIPPERBOT_TOKEN=st_...   (shown once)
```

and present it as `Authorization: Bearer st_...`. Service tokens are
hashed at rest and revocable (`scripts/service_token.py revoke <id>`).

Request:

```json
{
  "recipients": ["jacob", "elijah", "caleb"],
  "recipient":  "jacob",
  "message":    "Trading system halted — position unwound.",
  "source_type": "system",
  "source_id":  "",
  "channel":    "discord",
  "deliver":    true
}
```

`recipient` (singular) is merged with `recipients` and de-duplicated;
either spelling alone is enough. Limits: 20 recipients, 4000 characters.

Response — `results` carries one entry per recipient, with the delivery
receipts per surface:

```json
{
  "ok": true,
  "requested": 3,
  "channel": "discord",
  "delivered_via": ["discord"],
  "results": [
    {"recipient": "jacob", "notification_id": "n-1a2b3c4d",
     "delivered": true, "channels_reached": ["discord"],
     "receipts": {"discord": {"ok": true, "detail": "DM sent to jacob successfully."},
                  "web": {"ok": false, "detail": "not connected — waiting in history"}},
     "error": null}
  ]
}
```

Failure behaviour is the point of the endpoint:

| Condition | Status |
|---|---|
| Recipient unknown, or unreachable on the requested channel | `400`, naming them; **nothing is recorded for anyone** |
| Blank message, no recipients, over a limit | `400` |
| Caller is not an admin | `401`/`403` |
| Recorded but not delivered to every recipient | `502`, with `ok: false` and the per-recipient reason |
| Delivered to every recipient | `200`, `ok: true` |

The status code agrees with the body deliberately: a caller that checks
only whether the request succeeded must not be able to mistake an
undelivered alert for a delivered one. `delivered` counts only surfaces
the caller ASKED for — the web console is always written to, so counting
it would make every send look successful.

`deliver: false` records the row and says so (`note`), delivering nothing.

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
roll back the notification row. The row is marked `delivered = TRUE`
once delivery has been ATTEMPTED, whatever each channel came back with —
it records the attempt and is not evidence that a person was reached.
What each surface actually said is kept separately in the row's
receipts, and `_deliver_one` returns them to its caller.

Discord is additionally narrowed by the conversation-mirroring rule
(`notifications.channels.discord-not-sent-half-a-conversation`): someone
who mainly talks on the web gets no Discord copy unless they have used
Discord recently. That rule does NOT apply to a caller that named the
surface itself — see `notifications.channels.named-surface-is-not-mirroring`
— because its safety net is that the web console always has the record,
which assumes somebody is watching it.

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
- No `migrations/002` — fresh installs use
  only `001_initial.sql`. Pre-packaging installs that need to copy
  data out of `public.notifications` use private one-shot scripts
  (see `private/data_migrations/notifications/` in each operator's
  local checkout — outside the public repo).
- Subsequent migrations (`003+`) add columns, indexes, or constraints as
  the schema evolves.

## Why Notifications Is a Required App

Removing notifications would silently break every cross-app "tell the
user" code path: reminders never fire, jobs never report, the PM domain
never nudges. `core: true` enforces this.
