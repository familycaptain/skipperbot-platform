# Skipperbot — Platform Services

> **The reference for the `app_platform.*` service APIs every app may call.**
>
> These are the stable, backward-compatible service contracts an app package
> imports from the `app_platform` package — never from `data_layer/`, `tools/`,
> or another app directly. The platform guarantees these signatures: app code
> should not have to change because a platform internal changed.

For the broader app-authoring contract (package structure, manifest, extension
points, the memory/notifications/schedules/time *rules*), see
[APP_PACKAGES.md](APP_PACKAGES.md). For the event catalog see
[EVENTS.md](EVENTS.md); for semantic memory see [MEMORY.md](MEMORY.md).

---

## The dependency rule (why these exist)

Apps may depend on the platform; **the platform may not depend on any app.** An
app imports from `app_platform.*` and its own package — never from
`apps.<other>.*`. Cross-app **reads** go through
[`app_platform.entities`](#app_platformentities); cross-app **writes** go
through [`app_platform.events`](#app_platformevents). There is no third option.

Several `app_platform.*` modules are **thin facades** that re-export the public
surface of a core app or `data_layer/` module. The facade is the contract; the
implementation behind it can move. The "Forwards to" line in each subsection
below names the real owner. Apps must import the facade, not the owner.

---

## Service index

| Service | Import path | Forwards to | Purpose |
|---------|-------------|-------------|---------|
| [`db`](#app_platformdb) | `app_platform.db` | `data_layer.db` | Schema-scoped Postgres access |
| [`events`](#app_platformevents) | `app_platform.events` | (native) | At-least-once pub/sub event bus |
| [`entities`](#app_platformentities) | `app_platform.entities` | (native) | Read-only cross-app entity queries |
| [`memory`](#app_platformmemory) | `app_platform.memory` | memory queue / `memory_store` | Semantic memory ingestion (`digest_record`) |
| [`activity`](#app_platformactivity) | `app_platform.activity` | `app_timeline` (direct) | Auto personal-activity feed posts |
| [`time`](#app_platformtime) | `app_platform.time` | `app_platform.config` | Timezone-aware clock |
| [`config`](#app_platformconfig) | `app_platform.config` | `public.app_config` | Scoped key/value config |
| [`settings`](#app_platformsettings) | `app_platform.settings` | `config` + `secrets` | Config + transparent secret encryption |
| [`secrets`](#app_platformsecrets) | `app_platform.secrets` | (native, AES-256-GCM) | Encrypt/decrypt secrets at rest |
| [`capabilities`](#app_platformcapabilities) | `app_platform.capabilities` | (native registry) | Optional-integration gating (`is_enabled`) |
| [`auth`](#app_platformauth) | `app_platform.auth` | `data_layer.users` / `service_tokens` | Bearer-token principals + authorization |
| [`jobs`](#app_platformjobs) | `app_platform.jobs` | `apps.jobs.*` | Background job queue |
| [`schedules`](#app_platformschedules) | `app_platform.schedules` | `apps.schedules.data` | Recurring schedules |
| [`reminders`](#app_platformreminders) | `app_platform.reminders` | `apps.reminders.*` | User reminders + nags |
| [`notifications`](#app_platformnotifications) | `app_platform.notifications` | `apps.notifications.*` | Multi-surface user notifications |
| [`documents`](#app_platformdocuments) | `app_platform.documents` | `apps.documents.*` | Document store + search |
| [`folders`](#app_platformfolders) | `app_platform.folders` | `apps.folders.*` | Folders + folder knowledge |
| [`behaviors`](#app_platformbehaviors) | `app_platform.behaviors` | `apps.behaviors.data` | User behavior rules |
| [`backups`](#app_platformbackups) | `app_platform.backups` | `apps.backups.*` | Backup audit + run/verify |
| [`prioritize`](#app_platformprioritize) | `app_platform.prioritize` | `apps.prioritize.data` | Focus slots + cross-app backlog |
| [`timeline`](#app_platformtimeline) | `app_platform.timeline` | `apps.timeline.data` | Timeline posts |
| [`voice`](#app_platformvoice) | `app_platform.voice` | (native) | Server-side voice handlers (REST) |

> **What is *not* an `app_platform` service.** Three capabilities the older docs
> called `platform.*` do **not** live under `app_platform`:
> [links](#links-images-and-llmsearch-are-not-app_platform-modules),
> [images](#links-images-and-llmsearch-are-not-app_platform-modules), and LLM/web
> search. See that section for the real access paths so you don't import
> something that isn't there.

Each subsection gives the real signature(s), what the service **guarantees**,
what it does **not** guarantee, and a short working example. Examples use
generic placeholder users like `alice` / `bob`.

---

## `app_platform.db`

Thin wrapper around `data_layer.db`. Re-exports the plain helpers
(`fetch_one`, `fetch_all`, `execute`, `execute_returning`, `get_conn`) and adds
**schema-aware** helpers so an app reads/writes its own `app_<id>` schema with
unqualified table names.

```python
fetch_one_in_schema(schema: str, query: str, params: tuple = ()) -> dict | None
fetch_all_in_schema(schema: str, query: str, params: tuple = ()) -> list[dict]
execute_in_schema(schema: str, query: str, params: tuple = ()) -> int
execute_returning_in_schema(schema: str, query: str, params: tuple = ()) -> dict | None
fetch_all_vector_in_schema(schema: str, query: str, params: tuple = (), *, probes: int | None = None) -> list[dict]
scoped_conn(schema: str)   # context manager yielding a connection
```

**Guarantees**
- Each `*_in_schema` helper runs `SET LOCAL search_path TO <schema>, public`
  inside the same transaction as the query, so the app sees its own tables
  unqualified *and* can read platform tables in `public`.
- `SET LOCAL` resets when the connection returns to the pool — no search-path
  leakage across checkouts.
- Reads use a `RealDictCursor`, so rows come back as plain `dict`s.
- `execute_in_schema` returns the affected row count; `execute_returning_in_schema`
  commits and returns the single `RETURNING` row (or `None`).
- `fetch_all_vector_in_schema` additionally raises `ivfflat.probes` (defaults to
  `data_layer.db.VECTOR_SEARCH_PROBES`) so a pgvector `ORDER BY embedding` SELECT
  returns the true top-k rather than an approximate subset.

**Does NOT guarantee**
- No ORM, no migrations, no cross-schema write isolation enforced here — passing
  another app's schema name works, but is a contract violation (see the
  dependency rule). Use [`entities`](#app_platformentities) for cross-app reads.
- `schema` is interpolated into the SQL string (it is your app's own constant,
  not user input) — never pass a user-supplied schema name.

```python
from app_platform.db import execute_returning_in_schema, fetch_all_in_schema

SCHEMA = "app_recipes"

row = execute_returning_in_schema(
    SCHEMA,
    "INSERT INTO recipes (id, title) VALUES (%s, %s) RETURNING *",
    ("re-abc12345", "Weeknight Pasta"),
)
dinners = fetch_all_in_schema(
    SCHEMA, "SELECT id, title FROM recipes WHERE category = %s", ("dinner",)
)
```

---

## `app_platform.events`

The platform event bus. Apps `emit` events when things happen and `subscribe`
to react. Persistence-backed (`public.app_events` / `app_event_deliveries`) for
at-least-once delivery. See [EVENTS.md](EVENTS.md) for the event catalog.

```python
emit(event_type: str, payload: dict, emitted_by: str = "platform") -> str   # returns event id
subscribe(event_type: str)            # decorator; infers app_id from apps.<id>.* module path
register_subscriber(event_type: str, app_id: str, handler: callable)         # used by the loader
retry_failed_deliveries() -> int
get_subscriber_count() -> int
```

**Guarantees**
- `emit` writes one `app_events` row, creates a `pending` delivery row per
  registered subscriber, then dispatches synchronously. Returns an `ev-…` id.
- **Fault isolation:** a subscriber that raises is logged and its delivery is
  marked `failed` (with the error text) — it never propagates to the emitter or
  other subscribers.
- Each handler receives one merged dict: `{"event_id", "event_type", **payload}`.
- Failed deliveries are retried up to `MAX_ATTEMPTS` (3) by
  `retry_failed_deliveries` (the platform calls it periodically); an event flips
  to `completed` once every delivery is `delivered`.

**Does NOT guarantee**
- No ordering across event types, no partitions — this is not a full message
  queue. It guarantees no event is silently dropped, not strict sequencing.
- Dispatch is in-process and synchronous *within* `emit`; emitters effectively
  wait for the synchronous dispatch pass (retries are out-of-band). Keep
  handlers fast.
- `subscribe` only infers a real `app_id` from an `apps.<id>.*` module path;
  elsewhere it records `"unknown"`.

```python
# apps/recipes/tools.py — emit
from app_platform.events import emit
emit("recipe.created", {"id": "re-abc12345", "title": "Pasta", "created_by": "alice"},
     emitted_by="recipes")

# apps/meal_planner/handlers.py — subscribe
from app_platform.events import subscribe

@subscribe("recipe.created")
def on_recipe_created(event):
    recipe_id = event["id"]          # payload fields are merged in
    ...
```

---

## `app_platform.entities`

The **only** sanctioned way to read another app's data. Resolves an entity-type
prefix to its owning schema/table and runs a safe, parameterized `SELECT`.

```python
query_entities(prefix: str, filters: dict | None = None, fields: list[str] | None = None,
               limit: int = 100, order_by: str = "created_at", order_dir: str = "DESC") -> list[dict]
get_entity(prefix: str, entity_id: str) -> dict | None
invalidate_cache()   # call after app install/uninstall
```

**Guarantees**
- Prefix → `(table, schema)` resolution via the `entity_types` registry +
  `app_registry` (packaged apps resolve to `app_<id>`; legacy entities to
  `public`). Cached; `invalidate_cache()` clears it.
- All identifiers (schema, table, columns in `fields`/`filters`/`order_by`) are
  validated against `^[a-z_][a-z0-9_]*$` before interpolation; values are bound
  as parameters. `filters` are ANDed equality checks.
- `limit` is capped at **500**. `order_dir` other than `ASC`/`DESC` falls back to
  `DESC`. Unknown prefix raises `ValueError`.

**Does NOT guarantee**
- **Read-only.** No insert/update/delete path exists here — cross-app writes go
  through [events](#app_platformevents).
- No joins, no `OR`, no inequality filters, no field-level redaction — pass an
  explicit `fields` list to return only the columns you intend to expose.

```python
from app_platform.entities import query_entities, get_entity

dinners = query_entities(
    prefix="re",
    filters={"category": "dinner"},
    fields=["id", "title", "category", "prep_time"],
    limit=50,
)
one = get_entity("re", "re-abc12345")
```

---

## `app_platform.memory`

Semantic-memory ingestion. **Every app's `data.py` must call `digest_record`
after every successful create/update/delete/completion** — that is what makes an
app's entities recallable in chat. The full rationale and the per-app `_HINT`
pattern live in [APP_PACKAGES.md](APP_PACKAGES.md#required-memory-digestion-on-every-crud)
and [MEMORY.md](MEMORY.md).

```python
digest_record(
    app_id: str, entity_type: str, action: str, entity_id: str, record: dict,
    by: str = "", context_hint: str = "", blocking: bool = False,
) -> None
```

**Guarantees**
- For `created` / `updated` / `completed`: enqueues to the durable memory
  ingestion queue (`data_layer.memory_queue`); the memory thinking domain runs
  DUMB_MODEL fact extraction within ~30s and writes embedded memories to
  `memory_store`. If the queue is unavailable it falls back to a background
  thread.
- For `deleted` (or any action when `blocking=True` and `action="deleted"`):
  writes one direct "[deleted] …" memory synchronously — no LLM.
- Also fires a fire-and-forget personal [activity](#app_platformactivity) post.
- **Never raises** — all failures are logged and swallowed. Your CRUD keeps
  working if memory is briefly down.
- `blocking=True` runs synchronously (use it in backfill scripts to control rate).

**Does NOT guarantee**
- Not transactional with your DB write — call it *after* the row is committed so
  IDs/timestamps are present.
- Trivial records (fewer than two meaningful non-id fields) are skipped, as are
  the noise fields in `_SKIP_FIELDS` (`created_at`, `updated_at`, …).
- No de-dup of facts across calls; write a good `context_hint` so extraction
  stays focused.

```python
from app_platform.memory import digest_record

_RECIPE_HINT = "Focus on: title, cuisine, key ingredients, tags, prep time."

digest_record(app_id="recipes", entity_type="recipe", action="created",
              entity_id=recipe["id"], record=recipe, by="alice",
              context_hint=_RECIPE_HINT)
```

---

## `app_platform.activity`

Auto-posts a lightweight **personal** timeline entry whenever an app record
changes. You normally never call this directly — `digest_record` calls it for
you. It is documented here because it is part of the platform surface.

```python
log_activity(app_id: str, entity_type: str, action: str, entity_id: str,
             record: dict, by: str = "") -> None
```

**Guarantees**
- Writes one `app_timeline.timeline_posts` row (`visibility='personal'`,
  authored by `by`) titled like `"Added recipe: Weeknight Pasta"`.
- Writes **directly** to `app_timeline` via [`scoped_conn`](#app_platformdb) — it
  deliberately does **not** import `apps.timeline` (avoids a boot-time circular
  import). Contrast with the [`timeline`](#app_platformtimeline) facade, which is
  the contract for non-activity callers.
- **Never raises** — errors are logged and swallowed.

**Does NOT guarantee**
- Silently skips when `by` is empty or `"system"`, and skips `app_id="timeline"`
  (loop guard). So system-authored changes produce no activity post.

```python
from app_platform.activity import log_activity
# (almost always implicit — digest_record already calls this)
log_activity("recipes", "recipe", "created", "re-abc12345",
             {"title": "Weeknight Pasta"}, by="alice")
```

---

## `app_platform.time`

The single source of truth for "now", the timezone, and day boundaries. **Apps
must never call naive `datetime.now()` / `date.today()` / `datetime.utcnow()`.**
Full rule in [APP_PACKAGES.md](APP_PACKAGES.md#required-use-platform-time-never-naive-local-time).

```python
now(user_id: str | None = None) -> datetime          # aware, in configured zone
get_timezone(user_id: str | None = None) -> ZoneInfo
utcnow() -> datetime                                   # aware UTC — for DB storage
to_local(dt: datetime, user_id: str | None = None) -> datetime
invalidate_platform_timezone_cache() -> None
```

**Guarantees**
- Timezone resolution order: the user's `users.timezone` override (when
  `user_id` is given) → the platform-level `app_config(scope='platform',
  key='timezone')` → `Etc/UTC`.
- `utcnow()` is always aware UTC; `to_local` treats a naive input as UTC before
  converting.
- The platform zone *name* is cached in-process; a setter that changes it should
  call `invalidate_platform_timezone_cache()`. A "no timezone configured yet"
  outcome is intentionally **not** cached, so a freshly onboarded install starts
  working without a restart.

**Does NOT guarantee**
- Invalid zone strings fall back to UTC silently (logged nowhere as an error).
- `get_timezone` only consults the users table when `user_id` is passed; omit it
  for platform-wide timing.

```python
from app_platform.time import now, utcnow, to_local

created_at = utcnow()                         # store in a TIMESTAMPTZ column
today      = now().date()                     # user's "today", not the server's
shown      = to_local(row["created_at"], user_id="alice")
```

---

## `app_platform.config`

Scoped key/value config on `public.app_config`. `scope='platform'` for
platform settings; `scope='app:<id>'` for per-app settings declared in a
manifest `config:` array. The high-level helpers **auto-scope to the calling
app** by inspecting the caller's module path.

```python
get(key: str, default: Any = None, *, scope: str | None = None) -> Any
set(key: str, value: Any, *, scope: str | None = None, by: str = "") -> None
delete(key: str, *, scope: str | None = None) -> bool
list_keys(*, scope: str | None = None) -> dict[str, Any]
```

**Guarantees**
- When `scope` is omitted, the scope is inferred from the call stack:
  `apps.recipes.tools` → `app:recipes`; platform code → `platform`. So an app
  reads/writes its own scope without naming it.
- Values are stored as JSONB and returned deserialized; `set` is an upsert and
  stamps `updated_by` / `updated_at`.

**Does NOT guarantee**
- **No secret encryption** — store API keys/tokens through
  [`settings`](#app_platformsettings) with `secret=True`, not here.
- No cross-scope guard is enforced in code: passing an explicit `scope` for
  another app works, but violates the "don't read another app's scope" rule.

```python
from app_platform import config

config.set("default_servings", 4)            # → scope app:<calling-app>
servings = config.get("default_servings", 2)
```

---

## `app_platform.settings`

The single read/write path for **configurable values**, layered on
[`config`](#app_platformconfig) + [`secrets`](#app_platformsecrets). Use this
(not raw `config`) for anything a user sets in the Settings UI, especially
secrets.

```python
get(key: str, *, scope: str | None = None, secret: bool = False, default=None)
set(key: str, value, *, scope: str | None = None, secret: bool = False, by: str = "") -> None
is_configured(key: str, *, scope: str | None = None) -> bool
```

**Guarantees**
- App settings are **authoritative** — there is no `.env` fallback here.
  (Bootstrap values that must exist before the DB — OpenAI key, DB URL, the
  secret-encryption key — stay in `.env` and are read with `os.getenv`, not
  through this layer.)
- `secret=True` encrypts transparently on `set` and decrypts on `get`; callers
  always deal in plaintext. A value that can't be decrypted logs a warning and
  returns `default` rather than crashing.
- `is_configured` checks presence **without decrypting** — safe for "is this
  integration set up?" UI checks.
- Auto-scopes to the calling app when `scope` is omitted (same rule as `config`).

**Does NOT guarantee**
- `set(..., secret=True)` raises `app_platform.secrets.SecretKeyMissing` if
  `SKIPPERBOT_SECRET_KEY` is unset — surface that to the user rather than
  storing plaintext.

```python
from app_platform import settings

settings.set("discord_token", "xoxb-…", scope="platform", secret=True, by="alice")
token = settings.get("discord_token", scope="platform", secret=True)
if settings.is_configured("discord_token", scope="platform"):
    ...
```

---

## `app_platform.secrets`

AES-256-GCM encryption for secret-flagged values stored in `app_config`. You
rarely call this directly — [`settings`](#app_platformsettings) wraps it — but
it is part of the platform surface.

```python
encrypt(plaintext: str) -> str               # → "enc:1:<base64url(nonce||ct||tag)>"
decrypt(token: str) -> str                   # plaintext passthrough for non-tokens
is_encrypted(value: object) -> bool
secret_key_available() -> bool
generate_key() -> str
ensure_secret_key(env_path=None) -> str      # "present" | "generated" | "unpersisted"

class SecretError(Exception): ...
class SecretKeyMissing(SecretError): ...
class SecretDecryptError(SecretError): ...
```

**Guarantees**
- Authenticated encryption with a fresh random 96-bit nonce per value; tokens are
  versioned (`enc:1:`) and self-describing. A value without the prefix is
  returned unchanged by `decrypt` (plaintext passthrough for non-secret /
  pre-migration data).
- The key is `SKIPPERBOT_SECRET_KEY` from `.env` and **never enters the
  database** — a leaked DB backup yields only ciphertext.
- Failure is loud: `encrypt`/`decrypt` with no key raise `SecretKeyMissing`; a
  wrong/rotated key or corrupt data raises `SecretDecryptError`.
- `ensure_secret_key()` self-provisions a key at first startup (and hardens
  `.env` to owner-only), so a fresh install doesn't require manual key
  generation.

**Does NOT guarantee**
- No key rotation tooling — changing the key makes existing secrets undecryptable
  (a legacy bare-SHA256 passphrase key is tried as a fallback for old data, but a
  changed *random* key is not recoverable).

```python
from app_platform import secrets
token = secrets.encrypt("xoxb-secret")     # store the token in app_config
plain = secrets.decrypt(token)             # back to plaintext
```

---

## `app_platform.capabilities`

Registry + accessor for **optional integrations** (Discord, Brave, FCM, Gmail,
Pushover, Home Assistant, weather, …). A tool that depends on one checks
`is_enabled(...)` at the boundary and returns a clear "not configured" message
instead of crashing.

```python
is_enabled(name: str) -> bool
not_configured_message(name: str) -> str
status() -> dict[str, bool]
boot_banner() -> str
CAPABILITIES: tuple[Capability, ...]         # the registry
```

**Guarantees**
- `is_enabled(name)` is `True` only when the capability is fully configured.
  Capabilities migrated to the Settings UI (those with `settings_keys`) are
  checked through [`settings.is_configured`](#app_platformsettings) — so creds
  saved in the UI count, not just `.env`. Others fall back to an env-var check.
  An optional `extra_check` (e.g. file exists) must also pass.
- Unknown names return `False` (and log a warning) from `is_enabled`.
- Adding an integration is one row in `CAPABILITIES`; the boot banner and tool
  router pick it up automatically.

**Does NOT guarantee**
- It only reports *configured?* — it does not test live connectivity to the
  third-party service.

```python
from app_platform.capabilities import is_enabled, not_configured_message

def search_web(query: str) -> str:
    if not is_enabled("brave_search"):
        return not_configured_message("brave_search")
    ...
```

---

## `app_platform.auth`

Server-side authentication for the platform API. Two bearer credentials:
stateless **session tokens** (`tok:1:…`, AES-GCM, for logged-in humans) and
DB-backed **service tokens** (`st_…`, for the voice satellite / mobile).
Enforcement is unconditional — every mounted route requires a valid token.

```python
# FastAPI dependencies / extractors
require_user(request) -> dict                 # principal, or HTTP 401
require_admin(request) -> dict                # admin principal, or 401/403
enforce_admin(request) -> None
current_principal(request) -> dict | None
principal_from_request(request) -> dict | None
principal_from_ws(websocket) -> dict | None
# Authorization (IDOR guard)
scope_user(request, requested_user_id: str | None) -> str
resolve_target(principal: dict, requested_user_id: str | None) -> str
# Token lifecycle / verification
verify_token(token: str | None) -> dict | None
mint_session_token(user: dict) -> str
auth_key_available() -> bool
```

**Guarantees**
- A principal is `{"name", "role", "typ": "session"|"service", "is_service": bool}`.
- `verify_token` checks AES-GCM integrity, expiry (`exp`), and revocation
  (token `ver` vs the user's `token_version`) for session tokens; service tokens
  are verified against the hashed row in `public.service_tokens`.
- `require_user` reads `request.state.principal` (set by the auth middleware) and
  falls back to verifying the `Authorization: Bearer` header directly, so it
  works standalone.
- `scope_user` / `resolve_target` are the IDOR guard: a caller gets **their own**
  user id by default; targeting another user is allowed only for `admin`/`parent`
  roles, else HTTP 403.

**Does NOT guarantee**
- No login/session-store side effects here — `mint_session_token` requires
  `SKIPPERBOT_AUTH_KEY` (or `SKIPPERBOT_SECRET_KEY`) and raises if neither is set.
- Roles are resolved via `data_layer.users` (`has_role` / `has_any_role`); this
  module doesn't define the role model.

```python
from fastapi import Depends, Request
from app_platform.auth import require_user, scope_user

@router.get("/mine")
async def list_mine(request: Request, user: dict = Depends(require_user)):
    target = scope_user(request, None)        # always the caller's own id
    ...
```

---

## `app_platform.jobs`

Background job queue. **Facade** — re-exports the dispatcher engine, the data
layer, and the friendly store helpers. Forwards to `apps.jobs.dispatcher`,
`apps.jobs.data`, `apps.jobs.store`. Recurring work belongs in
[`schedules`](#app_platformschedules), **not** raw job rows — see the rule in
[APP_PACKAGES.md](APP_PACKAGES.md#required-recurring-work-goes-in-publicschedules-never-publicjobs).

```python
# dispatcher engine
submit_job(job_type: str, name: str = ..., created_by: str = ..., config: dict = ..., ...) -> dict
register_handler(job_type: str, handler, max_concurrent: int = ...) -> None
class JobContext: ...        # ctx.update_progress(pct), etc.
class RequeueRequested(Exception): ...
start_dispatcher(); request_shutdown(); is_shutting_down(); get_active_job_ids()
# data layer (CRUD)
get_job, list_jobs, list_running, count_running, is_cancelled, claim_queued_jobs,
update_progress, update_output, complete_job, fail_job, fail_stale_running,
append_log, get_logs, save_job, get_all_jobs, get_active_jobs, delete_job
# store layer (friendly — fires digest_record)
create_job, update_job, record_run, cancel_job, update_job_progress, format_jobs, …
```

**Guarantees**
- `submit_job` inserts a `public.jobs` row the dispatcher claims and runs against
  the handler registered (via the manifest `job_types`) for that `job_type`.
- The store-layer creators (`create_job`, …) fire `digest_record`/activity; the
  raw `data`-layer ones do not.
- Handler signature is `(job: dict, ctx: JobContext) -> str`; raising
  `RequeueRequested` asks the dispatcher to requeue.

**Does NOT guarantee**
- **Never `INSERT` into `public.jobs` directly** — always go through
  `submit_job`. **Never write `jobs.schedule_expr`** (deprecated). For *recurring*
  work, create a schedule, not a job.

```python
from app_platform.jobs import submit_job, register_handler, JobContext

def _handle_import(job: dict, ctx: JobContext) -> str:
    ctx.update_progress(50)
    return "Imported 12 recipes"

register_handler("recipe_import", _handle_import, max_concurrent=1)
job = submit_job(job_type="recipe_import", name="Import", created_by="alice",
                 config={"url": "https://…"})
```

---

## `app_platform.schedules`

Recurring schedules — *what to run* (recurrence rule + time-of-day), separate
from a single execution (a job row). **Facade** → `apps.schedules.data` (which
also houses the recurrence engine).

```python
create_schedule(title, created_by, *, recurrence_type, recurrence_rule, time_of_day,
                linked_entity_type, linked_entity_id, ...) -> dict
get_schedule(id) -> dict | None
list_schedules(active_only: bool = ...) -> list[dict]
update_schedule(...); delete_schedule(id) -> bool
complete_schedule(...)                 # advances next_due
get_completions(...); get_due_schedules(); get_calendar_events(...)
compute_next_due(...); describe_recurrence(...)
```

**Guarantees**
- A schedule row carries `recurrence_type` (`daily`/`weekly`/`monthly`/`interval`/
  `cron`/`rrule`) + `recurrence_rule` + `time_of_day` + `next_due`; the trigger
  submits a job when `next_due` passes, and `complete_schedule` advances it.
- `get_due_schedules` treats any `next_due <= now()` row as due — so a missed
  occurrence fires on the next poll after downtime (catch-up).

**Does NOT guarantee**
- Use **one schedule per cadence**; point it at a manifest `job_type` via
  `linked_entity_type="job"` + `linked_entity_id=<job_type>`. Don't encode two
  cadences in one row.

```python
from app_platform.schedules import create_schedule, list_schedules

if not any(s.get("linked_entity_id") == "chores_morning" for s in list_schedules(active_only=False)):
    create_schedule(
        title="Daily Chores Morning Push (9:00 AM)", created_by="system",
        recurrence_type="daily", recurrence_rule={"every": 1}, time_of_day="09:00",
        linked_entity_type="job", linked_entity_id="chores_morning",
        notify_channel="none",
    )
```

---

## `app_platform.reminders`

User reminders and nags. **Facade** → `apps.reminders.store` (high-level) +
`apps.reminders.data` (low-level CRUD).

```python
create_reminder(user_id: str, message: str, remind_at: str, recurrence: str | None = None, ...) -> dict
create_nag(...); list_reminders(...); get_reminder(id); cancel_reminder(id)
modify_reminder(...); snooze_reminder(...); get_due_reminders(); mark_delivered(...)
assign_nag_times(...); compute_next_occurrence(...)
# low-level data API (rarely needed): save_reminder, get_user_reminders, delete_reminder, …
```

**Guarantees**
- `create_reminder` stores a reminder due at `remind_at` (ISO 8601); `recurrence`
  accepts an RRULE string for repeats. The reminder scheduler delivers due
  reminders via [`notifications`](#app_platformnotifications).
- High-level store helpers are the intended API; the `data`-layer exports are an
  escape hatch for the rare bulk case.

**Does NOT guarantee**
- This is the per-user reminder model; for *job* recurrence use
  [`schedules`](#app_platformschedules) instead.

```python
from app_platform.reminders import create_reminder

create_reminder(user_id="alice", message="Trash day tomorrow",
                remind_at="2026-06-10T07:00:00+00:00", recurrence=None)
```

---

## `app_platform.notifications`

The **only** sanctioned way to fire a user notification. **Facade** →
`apps.notifications.store` / `apps.notifications.data`. Never call a
channel-specific sender (`discord_bot.send_dm`, `fcm_sender`, `pushover_tool`)
directly — that bypasses the audit record, multi-surface fan-out, chat-history
persistence, and async-safety. Full rationale + the channel matrix in
[APP_PACKAGES.md](APP_PACKAGES.md#required-notify-via-create_notification-not-channel-specific-senders).

```python
create_notification(recipient: str, message: str, source_type: str = "", source_id: str = "",
                    channel: str = "both", delivered: bool = False, ...) -> dict
get_notifications(...); format_notifications(...)
# read helpers: get_notification, get_notifications_for_user, get_undelivered,
#               get_all_undelivered, mark_delivered, delete_notification
```

**Guarantees**
- `create_notification` inserts one `public.notifications` row. A background
  delivery loop (`notification_delivery.deliver_pending_notifications`, polled
  ~30s) fans it out across the channels selected by `channel`
  (`discord`/`push`/`both`/`app`/`mobile`/`all`) and persists it to the
  recipient's chat log. Your handler is done the moment the row is inserted.
- `recipient` is a `public.users.name` (lowercased internally).

**Does NOT guarantee**
- It does not send synchronously — delivery is the loop's job. Don't `await`
  anything here; `create_notification` is plain sync.

```python
from app_platform.notifications import create_notification

create_notification(recipient="alice", message="Trash day tomorrow",
                    source_type="reminder", source_id="r-abc12345", channel="both")
```

---

## `app_platform.documents`

The platform document store (lives in `public`, available to all apps).
**Facade** → `apps.documents.store` (friendly helpers: `digest_record` +
embed-on-save + folder reprocess) and `apps.documents.data` (CRUD + semantic /
hybrid search).

```python
# store layer (preferred)
create_doc(title: str, content: str, tags: list[str] = ..., created_by: str = "", ...) -> dict
get_doc(id); get_doc_meta(id); list_docs(...); search_docs(query, ...)
update_doc(...); append_to_doc(...); update_doc_meta(...); delete_doc(id); format_doc_list(...)
# data layer (low-level)
save_document, get_document, get_document_content, get_all_documents, update_content,
delete_document, search_documents, search_documents_hybrid, update_embedding
```

**Guarantees**
- `create_doc` and the other store helpers fire memory digestion and embed the
  content on save, so docs are immediately searchable (`search_docs` /
  `search_documents_hybrid`).
- Documents are a **platform service, not an app** — call `create_doc` directly;
  don't query a "documents app" via [`entities`](#app_platformentities).

**Does NOT guarantee**
- The low-level `data` exports skip the digest/embed side effects — prefer the
  store layer unless you specifically want raw CRUD.

```python
from app_platform.documents import create_doc, search_docs

doc = create_doc(title="Research findings", content="…markdown…",
                 tags=["research"], created_by="alice")
hits = search_docs("market outlook", limit=5)
```

---

## `app_platform.folders`

Folders + folder knowledge (vector-searchable folder context). **Facade** →
`apps.folders.store` (CRUD + link management + intelligence-job dispatch),
`apps.folders.data` (CRUD + vector search), `apps.folders.intelligence`
(chat-side retrieval).

```python
# store
create_folder(...); get_folder(id); get_folder_detail(id); list_folders(root_only: bool = ...)
update_folder(...); delete_folder(id); restore_folder(id); search_folders(...)
get_breadcrumbs(id); add_item(...); remove_item(...); move_item(...)
get_folders_containing(entity_id); reorder_items(...)
ensure_folder_for_entity(entity_id, entity_type=...); create_doc_in_folder(...); get_full_tree()
# data: get_all_folders, get_child_folders, get_folder_by_related_entity, get_item_count,
#       save_knowledge_row, search_knowledge, get_knowledge_for_entity, …
# intelligence: process_folder_item, reprocess_folder_item, search_folder_knowledge,
#               get_relevant_folder_knowledge, format_folder_knowledge_for_context
```

**Guarantees**
- Store helpers fire `digest_record`, manage links, and dispatch the
  folder-intelligence job; `ensure_folder_for_entity` is idempotent (returns the
  existing folder if one already maps to that entity).
- `get_relevant_folder_knowledge` returns chat-ready folder context for prompt
  injection.

**Does NOT guarantee**
- The `data`-layer exports are low-level CRUD without the store-layer side
  effects.

```python
from app_platform.folders import list_folders, ensure_folder_for_entity

roots  = list_folders(root_only=True)
folder = ensure_folder_for_entity("vacation-2026", entity_type="project")
```

---

## `app_platform.behaviors`

User behavior rules (custom instructions injected into the system prompt).
**Facade** → `apps.behaviors.data`.

```python
create_behavior(...); get_behavior(id); list_behaviors(...)
update_behavior(...); toggle_behavior(id, ...); delete_behavior(id)
get_active_behaviors_for_user(user_id: str) -> list[dict]
```

**Guarantees**
- `get_active_behaviors_for_user` returns the enabled rules for a user — chat /
  voice prompting code injects them unconditionally into the system prompt.

**Does NOT guarantee**
- This module is storage + retrieval; it does not itself apply the rules — the
  prompting layer does.

```python
from app_platform.behaviors import get_active_behaviors_for_user
rules = get_active_behaviors_for_user("alice")
```

---

## `app_platform.backups`

Backup audit table + run/verify handlers, plus a small config helper for the
Backups settings UI. **Facade** → `apps.backups.data` (CRUD),
`apps.backups.runner` (job handlers), and `app_platform.config`.

```python
# data: create_backup, complete_backup, skip_backup, fail_backup, get_backup,
#       list_backups(limit=...), delete_backup, prune_old_records, list_today
# runner: run_backup, run_backup_check
# config
get_config() -> dict
set_config(updates: dict, *, by: str = "") -> dict
CONFIG_SCOPE = "app:backups"; CONFIG_KEYS = (...)
```

**Guarantees**
- `get_config` / `set_config` round-trip only the documented `CONFIG_KEYS`
  (`enabled`, `cron`, `retention`, `filesystem_*`, `gdrive_*`); `set_config`
  rejects unknown keys with `ValueError`.
- `run_backup` / `run_backup_check` are the job handlers, exposed so a "Run
  backup now" UI can call them synchronously.

**Does NOT guarantee**
- The Google-Drive service-account JSON is a **secret** and is *not* in
  `CONFIG_KEYS` — it's managed only through the encrypted Settings → Backups
  panel.

```python
from app_platform.backups import list_backups, get_config
recent = list_backups(limit=50)
cfg    = get_config()
```

---

## `app_platform.prioritize`

User focus slots + the cross-app backlog aggregator. **Facade** →
`apps.prioritize.data`. Other apps register their backlog contributions and
activity checks at load time.

```python
get_focus_slots(user_id); set_focus(...); promote_to_focus(...); clear_focus(...)
clear_focus_by_source(...); reorder_focus(...); cleanup_stale_focus(...)
get_backlog(user_id) -> list[dict]
get_focus_nag_enabled(user_id); set_focus_nag_enabled(user_id, enabled)
register_backlog_provider(source: str, fn); register_activity_checker(source: str, fn)
```

**Guarantees**
- `get_backlog` aggregates contributions from every registered backlog provider,
  so an app surfaces its own work in the shared backlog without prioritize
  importing it.
- `register_backlog_provider` / `register_activity_checker` are the inversion
  point — apps call them in `hooks.py`/load, keeping the dependency one-way.

**Does NOT guarantee**
- Providers must be registered before `get_backlog` runs (i.e. at app load), or
  their items won't appear.

```python
from app_platform.prioritize import register_backlog_provider, get_backlog

register_backlog_provider("auto_issues", _auto_issues_for_user)   # in the app's hooks
items = get_backlog("alice")
```

---

## `app_platform.timeline`

Timeline posts (the shared social feed). **Facade** → `apps.timeline.data`. This
is the contract for *non-activity-log* callers (chat tools, REST routes, future
apps); the auto-[activity](#app_platformactivity) log deliberately bypasses it to
avoid a boot-time circular import.

```python
create_post(...); get_post(id); list_posts(...); update_post(...); delete_post(id)
toggle_pin(id); add_photo(...); remove_photo(...); list_authors(); list_tags()
```

**Guarantees**
- Full CRUD over timeline posts plus photo attachment and the author/tag
  indexes used to filter the feed.

**Does NOT guarantee**
- Don't use this from inside the activity-log path — use
  [`activity.log_activity`](#app_platformactivity) (or let `digest_record` call
  it) so you don't reintroduce the circular import.

```python
from app_platform.timeline import create_post, list_posts

post  = create_post(author_id="alice", title="Beach day", tags=["vacation"])
feed  = list_posts(limit=20)
```

---

## `app_platform.voice`

Server-side support for the separate `skipperbot-voice` companion process
(wake-word + audio I/O run there; this subpackage is everything the *platform*
serves to it). Submodules: `session` (OpenAI Realtime ephemeral-token minting +
session state), `prompting` (system-prompt + tool-schema construction via the
app loader), `tool_runtime` (executes tool calls from the voice REST API),
`chatlog` (persists voice transcripts).

The platform exposes these over REST under **`/api/voice/*`**, authenticated with
a service token (`Authorization: Bearer <st_…>`, issued by
`python scripts/service_token.py create voice`):

| Endpoint | Body | Returns |
|----------|------|---------|
| `POST /api/voice/session_start` | `{user_id, device_info?}` | `{ephemeral_token, model, voice, initial_tools, initial_instructions, session_id}` |
| `POST /api/voice/switch_app` | `{session_id, app_name}` | `{tools, instructions, app}` |
| `POST /api/voice/tool_call` | `{session_id, call_id, tool_name, arguments}` | `{events}` |
| `POST /api/voice/session_end` | `{session_id}` | `{ok}` |

**Guarantees**
- The token-minting, prompt/tool-schema construction, tool execution, and
  transcript-logging building blocks are present and importable from
  `app_platform.voice.*`.

**Does NOT guarantee**
- **Status caveat:** the `app_platform.voice.routes` router is a documented
  **Phase 1e placeholder** — the live `/api/voice/*` routes are currently defined
  in `agent.py` (where voice was co-located before extraction). The table above
  is the target wire contract; treat the router module as not-yet-wired until
  Phase 1e moves the routes here. Ordinary apps don't import this subpackage — it
  exists for the voice companion service.

---

## Links, images, and LLM/search are NOT `app_platform` modules

Older notes referred to `platform.links`, `platform.images`, `platform.llm`, and
`platform.search`. **None of these exist under `app_platform`.** Use the real
paths:

| Capability | Real access path | Notes |
|------------|------------------|-------|
| Entity links | `link_registry` (`create_link`, `get_links`, `get_linked_ids`, `delete_link`, `get_blast_radius`, `format_links`) and `data_layer.links` (`create_link`, `ensure_edge`, `get_links`, `get_blast_radius`, …) | Live in the link layer, **not** `app_platform`. `entity.linked` / `entity.unlinked` [events](EVENTS.md) fire on link changes. |
| Image storage | `data_layer.images` | Not an `app_platform` facade. |
| LLM calls | `config` (`openai_client`, `SMART_MODEL`, `DUMB_MODEL`) | There is no `app_platform.llm` / `call_smart` / `call_dumb`. App-level memory extraction goes through [`digest_record`](#app_platformmemory); direct model calls use the `config` client. |
| Web search | the Brave search tool, gated by [`capabilities.is_enabled("brave_search")`](#app_platformcapabilities) | No `app_platform.search` module; check the capability before calling the tool. |

> [APP_PACKAGES.md](APP_PACKAGES.md)'s service index lists `app_platform.links`
> and `app_platform.images` in its overview table; those names describe the
> *capability*, but the importable code lives at the paths above, not under
> `app_platform`. If a future chunk promotes them to real `app_platform` facades,
> update this section.
