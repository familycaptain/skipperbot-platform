# Entity Links Guide

Use `link_entities` to create bidirectional cross-references between any entities.
For example, link a reminder to the task it's about, or an artifact to a project.
Include a `relation` label like "reminds_about", "attached_to", "blocks", "depends_on".

## Workflows

### Link two related entities
- "This task depends on that project" → link_entities(t-*, p-*, relation="depends_on")

### View all connections
- "What's connected to this goal?" → get_entity_links(g-*)

### Unlink entities
- "Remove the link between those" → unlink_entities(lnk-*)

### Common relation labels
- `reminds_about` — reminder → task/goal
- `attached_to` — artifact → entity
- `blocks` / `blocked_by` — dependency between tasks
- `depends_on` — softer dependency
- `supports` — job → goal
- `reference` / `reference_material` — knowledge → goal
- `shopping_list` — reminder → list
- `superseded_by` — artifact version chain
- `shared_doc` — artifact shared across projects
