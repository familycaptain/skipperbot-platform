# Skipperbot — Event Bus

> **The contract for the platform event bus.** Apps emit events when something
> happens; other apps (and the platform) subscribe and react. This is the
> *only* sanctioned channel for an app to influence another app's domain — the
> hard rule is never `import apps.<other>`; subscribe to its events instead.
>
> The bus lives at `app_platform.events`. For the broader app contract this
> sits inside, see [`APP_PACKAGES.md`](APP_PACKAGES.md).

---

## Why an event bus

Loose coupling via events is design principle #3 of the app platform: *apps
never import each other's code.* Without a bus, "when App B does X, App A
should do Y" forces App A to import and call into App B — and now the two are
welded together: you can't install, remove, or break one without the other.

The event bus inverts that. App B announces *what happened* (`bounty.approved`)
without knowing or caring who listens. App A declares *what it cares about*
and reacts. Neither imports the other. Either can be uninstalled and the
remaining one keeps working — emits with no subscribers are a no-op; a
subscriber whose emitter is gone simply never fires.

This is what keeps every app independently installable, removable, and **safe
to fail**.

---

## The contract

The whole public surface is two calls, both imported from the stable
`app_platform.events` namespace.

### Emit

```python
from app_platform.events import emit

emit("bounty.approved", {
    "id": bounty_id,
    "title": bounty["title"],
    "approved_by": approver,
}, emitted_by="bounties")
```

```python
def emit(event_type: str, payload: dict, emitted_by: str = "platform") -> str
```

| Arg | Meaning |
|-----|---------|
| `event_type` | The event name, `<domain>.<action>` (see naming below). |
| `payload` | A JSON-serializable dict. Persisted as `jsonb`; keep it to plain IDs + scalars the subscriber needs, not whole nested records. |
| `emitted_by` | The app id of the emitter (e.g. `"bounties"`). Defaults to `"platform"`. Recorded for the audit trail. |

`emit` returns the generated event id (`ev-XXXXXXXX`). It is effectively
**fire-and-forget from the caller's view** — the return value is the event id,
not a delivery result, and the caller does not wait on subscribers' outcomes.

### Subscribe

A handler lives in the app's `handlers.py` and is wired by the loader when the
app loads (extension point: it imports `apps/<id>/handlers.py`, and the
`@subscribe` decorators register themselves as a side effect of import).

```python
# apps/meal_planner/handlers.py
from app_platform.events import subscribe

@subscribe("bounty.approved")
def on_bounty_approved(event):
    # event = {"event_id", "event_type", **payload}
    bounty_id = event["id"]
    ...
```

```python
def subscribe(event_type: str)   # decorator
```

- The **app id is inferred from the module path** — `apps.<id>.handlers` →
  `<id>`. You don't pass it. (A handler defined outside an `apps.<id>.*`
  module registers under `app_id="unknown"`.)
- The handler receives **one dict argument**: the payload, with `event_id` and
  `event_type` merged in at the top level. So `event["event_type"]` and the
  payload keys (`event["id"]`, etc.) are siblings. A payload key named
  `event_id` or `event_type` would be shadowed — don't use those names in a
  payload.
- Handlers are plain functions. The dispatcher calls them **synchronously**
  inside `emit` (see Delivery below), so a handler that does heavy work blocks
  the emitter. Keep handlers fast; offload real work with
  `app_platform.jobs.submit_job`.

There is also a programmatic registration entry point the loader uses
internally:

```python
def register_subscriber(event_type: str, app_id: str, handler: callable)
```

`@subscribe` is sugar over `register_subscriber` with the app id inferred.
Apps use the decorator; you should not need to call `register_subscriber`
directly.

### Declaring intent in the manifest

`manifest.yaml` declares which events an app publishes and listens for. These
arrays are **documentation/intent** for store listings, review, and the
dependency picture — the actual wiring is the `emit()` calls in the app's code
and the `@subscribe` handlers in `handlers.py`, not the manifest.

```yaml
# apps/<id>/manifest.yaml
emits:
  - goal.created
  - goal.updated
  - goal.deleted

subscribes:
  - bounty.approved
```

Keep the manifest honest — list what the code actually emits/subscribes to.
Empty is fine: `emits: []`, `subscribes: []`.

---

## Naming convention: `<domain>.<action>`

Every event name is `<domain>.<action>`, lower-snake on each side:

- **domain** — the entity or area the event is about (`bounty`, `chore`,
  `goal`, `recipe`, `entity`, `job`).
- **action** — past-tense verb describing what happened (`created`,
  `updated`, `deleted`, `approved`, `completed`, `linked`).

Examples actually emitted by shipped apps:

| Event | Emitter | Payload (shape) |
|-------|---------|-----------------|
| `bounty.created` | bounties | `{id, title, ...}` |
| `bounty.approved` | bounties | `{id, title, approved_by, ...}` |
| `bounty.submitted` | bounties | `{id, title, submitted_by}` |
| `chore.completed` | chores | `{...chore fields, completed_by}` |
| `goal.created` / `goal.updated` / `goal.deleted` | goals | `{id, ...}` |

A domain owns its events. Don't emit another app's domain prefix — if the
meal planner wants the recipes app to act, it emits its *own*
`meal_planner.recipe_requested` and the recipes app may subscribe and decide
whether to act (cross-app *write* requests always go through events, never a
direct call — see [`APP_PACKAGES.md`](APP_PACKAGES.md#cross-app-data-access)).

---

## Standard platform events

These are the names reserved for **platform-level** events — entity lifecycle,
job lifecycle, notifications — emitted by platform services so any app can
react to platform activity uniformly:

| Event | Payload | When |
|-------|---------|------|
| `entity.created` | `{id, type, created_by}` | An entity is created via a platform service |
| `entity.updated` | `{id, type, fields, updated_by}` | An entity is updated |
| `entity.deleted` | `{id, type, deleted_by}` | An entity is deleted |
| `entity.linked` | `{source_id, target_id, relation}` | A link is created |
| `entity.unlinked` | `{source_id, target_id, relation}` | A link is removed |
| `job.completed` | `{job_id, job_type, result}` | A job finishes |
| `job.failed` | `{job_id, job_type, error}` | A job fails |
| `notification.sent` | `{user, channel, entity_id}` | A notification is delivered |

> **Status — reserved, not yet wired.** These names are the agreed contract,
> but platform services do not all emit them today. Don't assume a given
> standard event fires until you've confirmed an emitter exists. App-domain
> events (`bounty.*`, `chore.*`, `goal.*`) are the ones currently live. Treat
> this table as the namespace reservation: when a platform service starts
> emitting lifecycle events, these are the names and payloads it will use.

---

## Delivery: persisted, at-least-once-oriented

The bus is **not** purely in-process. Events are persisted to Postgres before
and during dispatch, so there is a durable audit trail and a basis for
retrying a subscriber that threw. Two tables in the `public` schema back it
(defined in `migrations/000_baseline.sql`):

```
app_events
  id           TEXT PRIMARY KEY          -- 'ev-XXXXXXXX'
  event_type   TEXT NOT NULL             -- e.g. 'bounty.approved'
  payload      JSONB NOT NULL DEFAULT '{}'
  emitted_by   TEXT NOT NULL             -- app_id of the emitter
  emitted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
  status       TEXT NOT NULL DEFAULT 'pending'   -- 'pending' | 'dispatched' | 'completed'
```

```
app_event_deliveries
  event_id     TEXT NOT NULL REFERENCES app_events(id) ON DELETE CASCADE
  subscriber   TEXT NOT NULL             -- app_id of the subscriber
  status       TEXT NOT NULL DEFAULT 'pending'   -- 'pending' | 'delivered' | 'failed'
  attempts     INT NOT NULL DEFAULT 0
  last_attempt TIMESTAMPTZ
  error        TEXT NOT NULL DEFAULT ''
  PRIMARY KEY (event_id, subscriber)
```

**What `emit()` actually does, in order:**

1. Generates the event id and inserts the `app_events` row with
   `status = 'dispatched'`.
2. Looks up the in-memory subscriber registry for `event_type` and inserts one
   `app_event_deliveries` row per subscriber with `status = 'pending'`. (Both
   inserts share one transaction, then commit.)
3. **Dispatches synchronously, in the calling thread** — there is no
   background dispatcher loop. For each subscriber it calls the handler:
   - success → that delivery row → `status = 'delivered'`, `attempts += 1`,
     `last_attempt = now()`.
   - the handler raises → the exception is **caught and logged, never
     propagated** (fault isolation), and the delivery row → `status =
     'failed'`, `attempts += 1`, `error = <message>`.
4. If **every** subscriber succeeded (or there were none), the event row →
   `status = 'completed'`.

Because dispatch runs inside `emit`, the emitter's thread does pay for its
subscribers' time — but never for their *failures*. One subscriber throwing
does not stop the others and does not raise back into the emitter.

> **Retry — present in code, not yet scheduled.** `events.py` defines
> `retry_failed_deliveries()` (re-runs `failed` deliveries whose `attempts <
> MAX_ATTEMPTS`, where `MAX_ATTEMPTS = 3`, and promotes an event to
> `completed` once all its deliveries are `delivered`). There is currently **no
> caller** wiring it onto a schedule, so in practice a failed delivery stays
> `failed` until something invokes the retry. The "at-least-once" guarantee is
> therefore *designed-for* but only as strong as the (not-yet-scheduled)
> retry pass. Document this as the reality: persistence + fault isolation are
> live; automatic retry is dormant.

---

## How apps emit

Emit from wherever the state change happens — the data layer, `store.py`,
`tools.py`, or a route handler — *after* the write succeeds. The common shipped
pattern wraps `emit` in a tiny guard so a bus hiccup can never break the
mutation that triggered it:

```python
# apps/<id>/store.py
import logging
logger = logging.getLogger("<id>")

def _emit(event: str, data: dict) -> None:
    """Emit a platform event; never let the bus break the caller."""
    try:
        from app_platform.events import emit
        emit(event, data)
    except Exception as e:
        logger.debug("<ID>: event emit failed (%s): %s", event, e)

def approve_bounty(bounty_id: str, approver: str) -> dict:
    bounty = _do_approve(bounty_id, approver)   # DB write first
    _emit("bounty.approved", {
        "id": bounty_id,
        "title": bounty["title"],
        "approved_by": approver,
    })
    return bounty
```

Note that pattern omits `emitted_by`, so those events record the default
`"platform"`. Pass `emitted_by="<id>"` when you want the emitter attributed in
the audit trail.

**Rules for payloads:**

1. **Emit after the write commits**, so IDs and computed fields are real.
2. **Payload is plain JSON** — IDs and scalars the subscriber needs to act,
   not a whole ORM record. Subscribers that need more should read it back via
   `app_platform.entities.query_entities`.
3. **Don't reuse `event_id` / `event_type` as payload keys** — the dispatcher
   merges those in and would shadow them.
4. **List the event in your manifest's `emits:`** so it shows up in reviews and
   the dependency picture.

---

## How apps subscribe

Drop a `handlers.py` in your app folder and decorate functions with
`@subscribe`. The loader imports the module on app load, which runs the
decorators and registers the handlers.

```python
# apps/<id>/handlers.py
import logging
from app_platform.events import subscribe

logger = logging.getLogger("<id>")

@subscribe("bounty.approved")
def on_bounty_approved(event):
    # event = {"event_id", "event_type", "id", "title", "approved_by"}
    try:
        _react_to_approval(event["id"])
    except Exception:
        logger.exception("<id>: failed handling %s", event.get("event_id"))
```

**Rules for handlers:**

1. **One dict argument.** It is the payload plus `event_id` + `event_type`.
2. **Be fast and side-effect-light.** Dispatch is synchronous in the emitter's
   thread; for real work, enqueue a job (`app_platform.jobs.submit_job`) and
   return.
3. **You don't have to catch your own exceptions for isolation** — the
   dispatcher already catches, logs, and marks the delivery `failed` without
   touching the emitter or other subscribers. Catch only when you want your
   own log context or partial-success handling.
4. **Declare the event in `subscribes:`** in your manifest to keep intent
   visible. (The manifest array is advisory; the live wiring is the
   `@subscribe` decorator.)
5. **A handler is the *only* way to react to another app's domain.** Never
   `from apps.<other> import ...`.

> Today no shipped app uses `@subscribe` yet — several apps *emit*
> (`bounties`, `chores`, `goals`), and the subscribe path is fully wired in the
> loader and bus, ready for the first consumer. If you're adding the first
> subscriber for an event, you're exercising a live but as-yet-unused path —
> verify end-to-end.

---

## The cross-app rule

This is the load-bearing reason the bus exists, so it bears repeating
alongside the rest of the dependency rule (see
[`APP_PACKAGES.md`](APP_PACKAGES.md#the-dependency-rule)):

- **Never `import apps.<other>`.** Not the data layer, not the store, not the
  tools. The loader treats apps as mutually invisible.
- **Cross-app reads** go through `app_platform.entities.query_entities`
  (read-only, field-scoped).
- **Cross-app writes / reactions** go through events: the other app emits, you
  subscribe. There is no third option.
- **The platform never imports an app either** — it reaches core apps through
  their `app_platform.*` facade, and reaches every app's reactions through the
  bus.

If you find yourself wanting to call into another app, the answer is almost
always: have that app emit an event, and subscribe to it here.

---

## See also

- [`APP_PACKAGES.md`](APP_PACKAGES.md) — the full app contract; the event bus
  is extension point #6, and the cross-app rules live under *Cross-App Data
  Access* and *The dependency rule*.
- [`APP_PACKAGES.md`](APP_PACKAGES.md#platform-services) — `app_platform.*`
  service catalog, including `app_platform.jobs` (offload work from handlers)
  and `app_platform.entities` (cross-app reads).
