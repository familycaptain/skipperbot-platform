# Goals — Spec

## Purpose

The platform's project-management core. Owns the goals → projects → tasks
hierarchy that every other Skipperbot app links to for context. Includes
the **PM (Project Manager) thinking domain** that autonomously reviews
open items on a schedule and nudges the user about what's at risk or
slipping.

This is a **required core app** — the platform refuses to start without
it. Other apps may depend on goals being installed; goals depends only
on the platform.

## Data Model

Schema: `app_goals`. Three tables, three entity-type prefixes.

### `goals`

A long-horizon outcome — the top of the hierarchy. Owned by one or more
users. Has a target date or `'ongoing'`. Can be linked to documents,
knowledge sources, brainstorms, etc.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `g-{hex8}` |
| `name` | `text NOT NULL` | |
| `owners` | `text[] NOT NULL DEFAULT '{}'` | canonical user names |
| `target_date` | `text NOT NULL DEFAULT ''` | ISO date or `'ongoing'` |
| `status` | `text NOT NULL DEFAULT 'not_started'` | enum: `not_started`, `in_progress`, `done`, `blocked`, `deferred` |
| `stack_rank` | `integer NOT NULL DEFAULT 0` | user-controlled ordering |
| `notes` | `text NOT NULL DEFAULT ''` | markdown |
| `history` | `jsonb NOT NULL DEFAULT '[]'` | audit log of changes |
| `artifacts` | `text[]` | linked artifact IDs |
| `created_by` | `text` | |
| `created_at` | `timestamptz` | |

### `projects`

A scoped piece of work under a goal. Has a due date, priority, ownership
distinct from the parent goal. Has optional `auto_nag` config (the PM
domain uses it). May have a Trello link if Trello sync is enabled.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `p-{hex8}` |
| `name` | `text NOT NULL` | |
| `goal_id` | `text NOT NULL REFERENCES goals(id) ON DELETE CASCADE` | |
| `owners` | `text[]` | |
| `due_date` | `text` | |
| `priority` | `text` | enum: `low`, `medium`, `high` |
| `status` | `text` | same enum as goals |
| `stack_rank` | `integer` | |
| `notes` | `text` | |
| `history` | `jsonb` | |
| `artifacts` | `text[]` | |
| `auto_nag` | `jsonb` | `{enabled, user_id, nag_id, current_task_id}` or null |
| `trello` | `jsonb` | `{board, backlog_list, done_list, user_lists}` or null |
| `created_by` | `text` | |
| `created_at` | `timestamptz` | |

### `tasks`

The unit of work. Has an assignee, due date, dependencies, optional
parent task (sub-tasks). Status mirrors goals/projects.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` PK | `t-{hex8}` |
| `name` | `text NOT NULL` | |
| `project_id` | `text NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | |
| `parent_task_id` | `text REFERENCES tasks(id) ON DELETE SET NULL` | for sub-tasks |
| `assigned_to` | `text[]` | |
| `due_date` | `text` | |
| `priority` | `text` | |
| `status` | `text` | |
| `stack_rank` | `integer` | within-project ordering |
| `depends_on` | `text[]` | task IDs |
| `trello_card_id` | `text` | |
| `trello_list` | `text` | |
| `trello_linked` | `boolean` | |
| `notes`, `history`, `artifacts`, `created_by`, `created_at` | as above | |

### Indexes

- `idx_projects_goal_id`, `idx_tasks_project_id`, `idx_tasks_parent_task_id`
- `idx_tasks_trello_card_id` (partial, where set)

### Cross-schema reads

Goals reads from `public.users` to validate owner names. Goals reads from
`public.links` to surface "what is linked to this goal/project/task".
Goals writes to `public.notifications` via `platform.notifications.create_notification`
when the PM domain detects at-risk items.

## Entity Types

| Prefix | Name | Table |
|---|---|---|
| `g` | Goal | `goals` |
| `p` | Project | `projects` |
| `t` | Task | `tasks` |

Declared in `manifest.yaml`; the platform loader registers these in
`public.entity_types` at app-load time.

## Tools

~30 MCP tools, grouped:

- **Goals:** `create_goal`, `list_goals`, `get_goal`, `update_goal`, `delete_goal`, `set_goal_order`, `set_goal_dependency`
- **Projects:** `create_project`, `list_projects`, `get_project`, `update_project`, `delete_project`, `set_project_parent`, `set_project_order`, `set_project_dependency`
- **Tasks:** `create_task`, `list_tasks`, `get_task`, `update_task`, `complete_task`, `delete_task`, `set_task_parent`, `set_task_order`, `set_task_dependency`, `assign_task`
- **Search + queries:** `search_goals`, `list_at_risk_projects`, `list_slipping_tasks`, `list_blocked_items`, `list_user_tasks`
- **Nag control:** `disable_project_nag`, `enable_project_nag`
- **Trello:** `create_trello_task`, `adopt_trello_card` (only registered if Trello capability is enabled)

Each tool's docstring becomes the OpenAI function schema. Tool guide at `guide.md`.

## Routes

Mounted at `/api/apps/goals/` by the platform.

- `GET    /goals` — list with optional filters
- `POST   /goals` — create
- `GET    /goals/{id}` — get one with children
- `PUT    /goals/{id}` — update
- `DELETE /goals/{id}` — delete
- Same shape for `/projects/*` and `/tasks/*`.

These serve the Goals + Tasks desktop apps; the LLM uses the MCP tools above,
not these routes.

## UI

- **`GoalsApp`** — kanban-style view of goals and their projects, drag-to-reorder, drill into a goal to see its projects.
- **`TasksApp`** — task-focused view, filter by assignee/project/status, complete-from-the-list.

Both live under `apps/goals/ui/`.

## Events

### Emitted

| Event | Payload |
|---|---|
| `goal.created` | `{id, name, owners, created_by}` |
| `goal.updated` | `{id, fields_changed, updated_by}` |
| `goal.deleted` | `{id, deleted_by}` |
| `project.created` | `{id, name, goal_id, owners, created_by}` |
| `project.updated` | `{id, fields_changed, updated_by}` |
| `project.deleted` | `{id, deleted_by}` |
| `task.created` | `{id, name, project_id, assigned_to, created_by}` |
| `task.updated` | `{id, fields_changed, updated_by}` |
| `task.completed` | `{id, project_id, completed_by, completed_at}` |
| `task.deleted` | `{id, deleted_by}` |

### Subscribed

None in v1. Goals is foundational; it doesn't react to other apps' events.

## Platform Services Used

- `platform.db` — schema-scoped reads + writes against `app_goals.*` and platform tables
- `platform.memory.digest_record` — called after every create/update/delete (see `_HINT` constants in `data.py`)
- `platform.links` — exposes "what is linked to this goal/project/task" queries
- `platform.notifications.create_notification` — PM domain nudges
- `platform.events.emit` — fires the events listed above
- `platform.documents` — read/write linked docs
- `platform.time.now()` / `get_timezone()` — for due-date arithmetic + display
- `platform.config.get(key)` — reads this app's settings (pm_cadence_hours, pm_quiet_mode, etc.)

## Thinking Domains

### `pm` (Project Manager)

Daily review of open projects + tasks. Looks for:
- At-risk items (due date approaching, no recent activity)
- Slipping items (past due, status not updated)
- Blocked items (waiting on a dependency)
- Missing due dates or unclear definition-of-done

Notifies owners via `platform.notifications.create_notification`. Quiet
mode (`pm_quiet_mode=true`) logs without notifying.

Default schedule: daily 9 AM platform-local. User can override in Settings.

### `goals`

Weekly long-horizon review of goals. Identifies stalled goals, suggests
goal-level adjustments. Lower priority + cost than `pm`.

Default schedule: Sunday 6 AM. User-overridable.

Both thinking domains are **disabled by default** — onboarding asks the
user to opt in, or they enable later in Settings → Goals.

## Optional Dependencies

- **Trello** (Bucket 3, `TRELLO_KEY` + `TRELLO_TOKEN`): when enabled, tasks
  can be synced to a Trello board. The `trello_*` tools register only if
  `platform.capabilities.is_enabled("trello")` is true. Without Trello,
  goals/projects/tasks live entirely in the local DB.

## Migration Notes

- `migrations/001_initial.sql` creates the `app_goals` schema and the
  three tables, indexes, foreign keys.
- `migrations/002_migrate_from_public.py` (one-shot, idempotent) moves
  rows from `public.goals` / `public.projects` / `public.tasks` into
  `app_goals.*`. After the move, drops the public tables. Only relevant
  for installs that came from a pre-packaging Skipperbot — fresh installs
  skip this migration with no rows to move.
- Subsequent migrations (`003+`) add columns, indexes, or constraints as
  the schema evolves.

## Why Goals Is a Required App

Almost every other Skipperbot app links into the goals hierarchy:
- The Evolve app creates goals from spec gaps.
- The Prioritize app surfaces the top tasks across all projects.
- The Newsletter app reports on goal/project progress.
- The Scrum app references tasks in its daily digests.
- The Chat agent's "what should I work on" answer reads from tasks.

Removing goals would silently break all of these. `core: true` enforces this.
