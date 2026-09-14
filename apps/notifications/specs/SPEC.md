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
  "channel":    "",
  "deliver":    true
}
```

`recipient` (singular) is merged with `recipients` and de-duplicated;
either spelling alone is enough. Limits: 20 recipients, 4000 characters.

**Leave `channel` blank unless you mean it.** Blank takes Settings →
`default_channels` (`discord,pushover`), so a phone is reached whatever
the Discord policy decides for that person. Naming one channel STRIPS
the others — `"discord"` means Discord and nothing else, and a recipient
whose Discord copy is declined then has no push route at all. A
caretaker who wants every route asks for `"all"`
(`discord,pushover,mobile`).

Response — `results` carries one entry per recipient, with the delivery
receipts per surface:

```json
{
  "ok": true,
  "requested": 3,
  "succeeded": 3,
  "failed": 0,
  "channel": "",
  "delivered_via": ["discord", "pushover"],
  "results": [
    {"recipient": "jacob", "notification_id": "n-1a2b3c4d",
     "delivered": true, "channels_reached": ["pushover"],
     "receipts": {"pushover": {"ok": true, "detail": "Sent to jacob"},
                  "web": {"ok": false, "detail": "not connected — waiting in history"}},
     "error": null}
  ]
}
```

A recipient counts as unreachable only when **every** requested channel
is known to be dead for them — a missing `discord_id` does not make
somebody unreachable when Pushover is also being tried, and a channel
whose state cannot be determined is never assumed dead. Unreachable
recipients get no row: a record addressed to somebody with no route
would be a claim that they were told something.

**It sends to everyone it can reach.** One unreachable recipient does not
suppress the others — they get a `results` entry with `delivered: false`,
`notification_id: null` and an `error` naming the reason, and no row is
written for them. This is deliberate: the failure that bites an
escalation path is not a typo in a hardcoded list (which fails loudly on
its first smoke test) but *drift* — a `discord_id` quietly unset months
later, on a route nothing exercises until the emergency. One stale link
must not silence the alert to the other people, one of whom may be the
only person able to act on it.

So incompleteness is the thing that must never go **unnoticed**, rather
than the thing that must never happen:

| Condition | Status | `ok` |
|---|---|---|
| Every requested recipient reached | `200` | `true` |
| Some reached, some not | `207` | `false` |
| Nobody reached at all | `502` | `false` |
| Blank message, no recipients, over a limit | `400` | — |
| Caller is not an admin | `401`/`403` | — |

**The body is authoritative — `ok` and `results`, not the status code.**
`207` is "successful" to most HTTP clients (`requests`' `resp.ok` is
`True` for it), which is exactly why `ok` exists. The status is kept
honest anyway so that the one thing a careless caller cannot see is a
`200` over an alert that did not reach somebody; `200` continues to mean
every requested recipient was reached, and nothing less. `502` is kept
distinct from `207` so a caller can escalate a total failure differently
from a partial one.

`delivered` counts only surfaces the caller ASKED for — the web console
is always written to, so counting it would make every send look
successful.

**`results` is the contract — `ok` and `succeeded` are a summary of it.**
Every requested recipient appears in `results` exactly once, whatever
became of them, under the name their user record is keyed by (so a
request naming `"Jacob"` comes back as `"jacob"`). That matters because
recipients are not necessarily equivalent to the caller: where one of
them is the person who can actually act on the message and the others
are only being informed, `succeeded: 2` of 3 describes two outcomes that
are nothing like each other, and no count or single verdict can tell
them apart. Such a caller reads that person's own entry:

```python
body = resp.json()
critical = next((r for r in body["results"] if r["recipient"] == "jacob"), None)
if not critical or not critical["delivered"]:
    ...  # the person who can act was NOT reached — escalate elsewhere
elif not body["ok"]:
    ...  # degraded: they have it; note who was missed, and why
```

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
Discord recently. This is adaptive delivery, not suppression — it aims a
message at where a person actually is.

It removes **only** Discord from the target set. Every other channel the
notification carries is attempted unchanged, so one that also carries
`pushover` still buzzes a phone. Which is why naming a single channel is
not the safe choice it looks like: `channel: "discord"` means Discord and
nothing else, so a recipient whose Discord copy is declined has no push
route left — the *sender* removed the fallback. See
`notifications.channels.one-channel-is-not-a-fallback`.

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
