# Behaviors — App Spec

## Purpose
Owns user-customizable if/then behavior rules. Each rule lives in a
single table (`app_behaviors.behaviors`) and is unconditionally injected
into every chat system prompt for its owner — unlike memories
(recalled only when semantically similar), behaviors are *always
present*, making them reliable for automation-style rules.

## Data model
`app_behaviors.behaviors` — single table, no FKs.

| Column                 | Type        | Notes                                                              |
|------------------------|-------------|--------------------------------------------------------------------|
| `id`                   | text PK     | `beh-XXXXXXXX`                                                     |
| `trigger_description`  | text        | Natural-language "if" condition                                    |
| `action_description`   | text        | Natural-language "then" action                                     |
| `scope`                | text        | `user` (personal) or `system` (everyone)                           |
| `enabled`              | boolean     | true by default; toggled without deleting                          |
| `created_by`           | text        | user_id who owns the rule                                          |
| `notes`                | text        | optional why-this-rule context                                     |
| `created_at`           | timestamptz | now() default                                                      |
| `updated_at`           | timestamptz | now() default; bumped by update/toggle                             |

Three btree indexes — `idx_behaviors_scope`, `idx_behaviors_created_by`,
`idx_behaviors_enabled`.

## Public surface

### Tools (MCP)
- `add_behavior(user_id, trigger, action, scope='user', notes='')`
- `list_behaviors(user_id, scope='')`
- `update_behavior(behavior_id, trigger='', action='', notes='')`
- `remove_behavior(behavior_id)`
- `toggle_behavior(behavior_id)`

### Platform shim — `app_platform.behaviors`
Re-exports the data layer. Stable cross-app contract.

- `create_behavior(...)`, `get_behavior(id)`, `list_behaviors(...)`,
  `update_behavior(...)`, `delete_behavior(id)`, `toggle_behavior(id)`
- `get_active_behaviors_for_user(user_id)` — used by `chat_domain.py`
  and `app_platform.voice.prompting` to inject enabled rules on every
  chat / voice turn.

### REST endpoints
Live in `agent.py` (kept under `/api/behaviors/*` so the existing
`BehaviorsApp.jsx` keeps working without a URL migration):

- `GET    /api/behaviors`
- `POST   /api/behaviors`
- `PATCH  /api/behaviors/{behavior_id}`
- `POST   /api/behaviors/{behavior_id}/toggle`
- `DELETE /api/behaviors/{behavior_id}`

## Notifications, events, jobs
- Emits `behavior.created`, `behavior.updated`, `behavior.deleted`,
  `behavior.toggled` (via `digest_record`).
- No job handlers.
- No thinking domain.

## Migrations
- `001_initial.sql` — `app_behaviors.behaviors` + 3 indexes.
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.behaviors` use private one-shot scripts (see
  `private/data_migrations/behaviors/` in each operator's local
  checkout — outside the public repo).

## What this app does NOT own
- Memory injection — `memory_store` owns semantic recall.
- The chat system prompt itself — `chat_domain.py` assembles it and
  asks this app for active rules.
