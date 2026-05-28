# Skipperbot — Event Bus

> **Placeholder.** Full content lands in Chunk 2+.

## Scope

The platform's in-process event bus:

- Contract: `emit(name, payload)` is fire-and-forget; `@subscribe(name)` is sync or async.
- Fault isolation — a subscriber exception is logged, not propagated.
- Event naming convention: `<domain>.<action>` (`recipe.created`, `task.completed`).
- The standard platform events:

| Event | Payload | When |
|-------|---------|------|
| `entity.created` | `{id, type, created_by}` | Any entity created via a platform service |
| `entity.updated` | `{id, type, fields, updated_by}` | Any entity updated |
| `entity.deleted` | `{id, type, deleted_by}` | Any entity deleted |
| `entity.linked` | `{source_id, target_id, relation}` | Link created |
| `entity.unlinked` | `{source_id, target_id, relation}` | Link removed |
| `job.completed` | `{job_id, job_type, result}` | Job finished |
| `job.failed` | `{job_id, job_type, error}` | Job failed |
| `notification.sent` | `{user, channel, entity_id}` | Notification delivered |

- How apps emit their own events (per their manifest's `emits:` array).
- How apps subscribe via `handlers.py`.
- The rule: never reach across apps via `import apps.<other>`; subscribe to events instead.
- Persisted vs in-memory events: today the bus is purely in-process; durable events would be a future extension.
