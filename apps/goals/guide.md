# Goals, Projects & Tasks Guide

Hierarchical productivity tracking: Goals → Projects → Tasks (with subtask trees).

- Each entity has structured data (JSON) and narrative notes (markdown).
- Use `update_entity_notes` / `get_entity_notes` to read/write the markdown notes.
- Use `set_due_reminder` to automatically create a reminder linked to an entity's due date.
- When creating goals/projects/tasks, use `initial_notes` for any descriptive content
  (there is no description field — narrative lives in notes).
- **First-class arrays:** Goals have a `projects[]` array, projects have a `tasks[]` array,
  and goals/projects/tasks all have an `artifacts[]` array. These are maintained automatically
  when you create child entities or attach artifacts.

## Stopping onboarding ("Get started with Skipper")

Onboarding is a real skipper-owned goal with a thinking domain that proactively
reaches out. When the user asks to **stop / end / pause / skip / be done with the
onboarding** — or, in that context, to **stop the questions / stop the reminders /
stop reaching out** — the correct action is to call the **`stop_onboarding`** tool.

- `stop_onboarding(requested_by)` durably closes the onboarding goal out (cancels
  the goal and its open projects/tasks, disables its thinking domain, clears its
  pending PM nudges), so the proactive messages actually stop. It resolves the
  onboarding goal internally — you pass no goal id.
- **Do NOT just record a memory** with `remember`/`write_memory`. A memory is
  inert — it does NOT change the goal's status, so both the goal-think and PM
  domains keep nagging. Saving a preference instead of calling `stop_onboarding`
  is the wrong tool and leaves onboarding running.
- Confirm first if it's a passing/ambiguous mention, then call `stop_onboarding`.
  Afterwards, acknowledge warmly, say onboarding is set aside, and offer to bring
  it back later (reopening the goal re-enables it).

## Task Tree Structure

Tasks form a **tree** with arbitrary depth:
```
Goal (g-*)
  └── Project (p-*)
        ├── Task: M2.1 Milestone (top-level, parent=project)
        │     ├── Subtask: Quest manager (parent=M2.1, assigned: Bob)
        │     ├── Subtask: Dialogue UI sprites (parent=M2.1, assigned: Dave)
        │     └── Subtask: Persistence work (parent=M2.1, assigned: Eve)
        ├── Task: M2.2 Milestone
        │     └── Subtask: ...
        └── Task: M2.3 Milestone
```

- **Top-level tasks** live under a project (`project_id` set, `parent_task_id` null)
- **Subtasks** live under a parent task (`parent_task_id` set, `project_id` inherited)
- Subtasks can have their own subtasks — unlimited depth
- Every task (at any depth) still has `project_id` for project-level queries

### Creating subtasks
```
create_task(project_id="p-abc", name="Quest manager", parent_task_id="t-m21", assigned_to="bob")
```
When `parent_task_id` is provided, `project_id` is inherited from the parent task (you can
pass the parent task's project_id or it will be resolved automatically).

### Reparenting tasks
```
set_task_parent("t-xyz", "t-m22", "alice")   # move t-xyz under task t-m22
set_task_parent("t-xyz", "", "alice")         # make t-xyz top-level again
```

## Stack Ranking (G#, P#, T#)

Every entity level has a stack rank that determines priority order:
- **Goals**: G1, G2, G3... (global order)
- **Projects**: P1, P2, P3... (within a goal)
- **Tasks**: T1, T2, T3... (within a project)

Ranks auto-update on creation, status changes, and dependency changes.
Users reference entities by rank: "show me G3", "move P2 before P1", "what's T5?"

### Dependencies
```
set_goal_dependency("g-xxx", "g-yyy", "alice")       # G-xxx depends on G-yyy
set_project_dependency("p-xxx", "p-yyy", "alice")    # P-xxx depends on P-yyy
set_task_dependency("t-xxx", "t-yyy", "alice")       # T-xxx depends on T-yyy
```
Dependencies affect rank ordering (dependent comes after its dependency).

### Manual reorder
```
set_goal_order("g-bbb,g-aaa,g-ccc", "alice")              # Set G-rank order
set_project_order("g-xxx", "p-bbb,p-aaa,p-ccc", "alice")  # Set P-rank within goal
set_task_order("p-xxx", "t-bbb,t-aaa,t-ccc", "alice")     # Set T-rank within project
```

## Rank resolution — IMPORTANT

Rank references (G4, P2, T5) **auto-resolve** — you can pass them directly to any
tool. The system remembers the last-viewed goal and project across conversations, so:

- **"show me T3"** → call `get_entity_detail("T3")` directly. Do NOT call
  `get_project_detail` first to "look up" the mapping. T-ranks resolve automatically
  within the last-viewed project.
- **"show me P2"** → call `get_project_detail("P2")` directly.
- **"show me G1"** → call `get_goal_detail("G1")` directly.

**Never** call `search_goals`, `get_goals_summary`, or `get_project_detail` just to
resolve a rank. Pass the rank reference directly — the tool handles resolution.

## Display Views (drill-down hierarchy)

There are **four views** that form a drill-down hierarchy. Each level shows only its
own children — never skip levels or combine views:

```
Goals list → Goal + projects → Project + tasks → Full entity record
```

### 1. Goals list → `get_goals_summary(user_id)`
Shows **goals only** with G-ranks (G1, G2...), status, progress, project count. NO projects listed.
- ONLY use for: "show me my goals", "what are my goals", "goals overview"
- NEVER use this when the user asks about a specific goal.

### 2. Single goal → `get_goal_detail(goal_id)`
Shows **one goal + its projects with P-ranks** (P1, P2...). No tasks. Use whenever the
user references a **specific goal** — by G-rank, name, or description. Examples:
- "show me G3", "show me the TastyTrade goal", "what's the investing goal"
- "open the 2nd goal", "tell me about the house goal", "show me that goal"
- If the user gives a **G-rank** (G3), call `get_goal_detail("G3")` directly — it auto-resolves.
- If the user gives a **name** ("the investing goal"), call `search_goals("investing")` first
  to find the goal ID, then `get_goal_detail`. **ALWAYS search by name — do NOT guess IDs
  from conversation history. Names can be ambiguous and history may be stale.**

### 3. Project view → `get_project_detail(project_id)`
Shows **one project + full task tree with T-ranks** (T1, T2...). Use when user asks about a specific project:
- "show me P2", "show the Etsy project", "show the accounts project", "what are my tasks on X"
- If the user gives a **P-rank** (P2), call `get_project_detail("P2")` directly — it auto-resolves.
- If the user gives a **name** ("the Project-Alpha project", "the SkipperBot project"), call
  `search_goals("project-alpha")` first to find the project ID, then `get_project_detail`.
  **ALWAYS search by name — do NOT guess IDs from conversation history.**

### 4. Full record → `get_entity_detail(item_id)`
Shows **all fields, notes, history, artifacts, and links** for any entity:
- "details on T5", "all info on that task", "what are the details of this project"
Works for any `g-*`, `p-*`, or `t-*` entity.

### Direct-display (views 1, 2, & 3)
`get_goals_summary`, `get_goal_detail`, and `get_project_detail` use **direct display**:
the formatted output is sent straight to the user's chat — you do NOT need to repeat,
reformat, or summarize it. Your tool result contains the ID-rich version with `g-*`,
`p-*`, `t-*` IDs so you can reference them for follow-up actions.
**Never re-display** these views. Your reply comes AFTER the display is already shown,
so just answer any follow-up question or say nothing extra. Do NOT lead with
"Here's your goals:" — the user already sees it above your message.

## Safety Rules

### Cross-parent moves require confirmation
**NEVER** move a task to a different project, or a project to a different goal, without
first confirming with the user. These are destructive operations that change entity
ownership. Always ask:
- "Just to confirm — you want to move T3 from Project A to Project B?"
- "That would move this project from Goal X to Goal Y. Is that what you want?"

Only proceed after the user explicitly confirms. This applies to:
- `set_task_parent` when the target parent is in a different project
- `update_item` with a new `project_id`
- Any operation that changes a task's `project_id` or a project's `goal_id`

## Workflows

### Create a goal with milestone projects
- User describes a multi-phase effort → create goal → create project → create top-level tasks as milestones → create subtasks as work items under each milestone
- Each subtask can be assigned to a different person

### Track progress on a task
- User says "I finished the permit task" → `update_item(t-*, status=done)`
- If all sibling subtasks are done, the system hints to mark the parent done
- Check if all tasks in a project are done → optionally mark project done

### Add detailed notes
- User provides narrative → `update_entity_notes(g-*, content)` → stored in notes.md

### Search across all goals
- "What's the status of house stuff?" → `search_goals("house")`

### Get personal task list
- "What do I need to do?" → `get_my_tasks(user)` → shows tasks at all tree depths

### Reassign a task
- `update_item(t-*, fields_json with new assigned_to)`

### Defer or block a task
- `update_item(t-*, status=deferred/blocked, note="waiting on X")`

## Task Dependencies

Tasks can have explicit dependencies via `set_task_dependency`:
- `set_task_dependency("t-abc", "t-xyz", "alice")` → t-abc depends on t-xyz
- Dependencies can cross milestones, projects, even goals
- A task with unfinished dependencies is considered **blocked**
- When a dependency completes (status=done), blocked tasks are **auto-unblocked**
  (status changes from blocked → not_started automatically)

## Stack Ranking (Task Order)

Tasks are ranked **among siblings** (same parent level):
- Top-level tasks ranked within their project
- Subtasks ranked within their parent task
- `set_task_order("p-abc", "t-first,t-second,t-third", "alice")`
- New tasks auto-append at the end of their sibling list
- Stack rank determines traversal order for auto-nag

## Auto-Nag (Project Task Nagging)

Enable daily nagging on a project — the system walks the task tree depth-first
by stack rank and nags about the deepest actionable leaf task.

### How the tree walk works
1. Start with top-level tasks sorted by stack_rank
2. For each task, drill into its subtasks (also by stack_rank)
3. Return the first **leaf task** (or childless node) that is:
   - Not done or deferred
   - Not blocked by dependencies
4. If a parent task's subtasks are all done, the parent itself becomes actionable

### Enable auto-nag
`enable_project_nag("p-abc", "bob")` →
1. Walks the tree to find the first actionable leaf task
2. Creates a daily nag reminder with that task's name
3. Nag fires once per day at a random waking hour

### Automatic advancement
When a task is marked done (`update_item(t-*, status=done)`):
1. Tasks depending on it are auto-unblocked
2. If all sibling subtasks are done, hints to complete the parent
3. The nag advances to the next actionable leaf in the tree
4. If all tasks are done or blocked, the nag pauses

### Disable auto-nag
`disable_project_nag("p-abc", "alice")` → cancels the nag, preserves task ordering

### Setup workflow
1. Create project with milestone tasks
2. Add subtasks under each milestone for individual work items
3. Set order: `set_task_order("p-abc", "t-m1,t-m2,t-m3", "alice")`
4. Set dependencies if needed: `set_task_dependency("t-m3-sub", "t-m2-sub", "alice")`
5. Enable nag: `enable_project_nag("p-abc", "bob")`
6. User completes leaf tasks → nag drills into next subtask or next milestone

## Trello-Linked Projects (v2 — Live API)

Projects can be linked to a Trello board for **live integration**. Trello is the
source of truth — Skipper stores thin task skeletons and fetches card data live.

### Configuration
```
link_project_to_trello(project_id, board_name,
    backlog_list="Backlog", done_list="Done",
    user_lists_json='{"bob": "Bob TODO", "dave": "Dave TODO"}')
```
- **backlog_list**: Where new cards land (maps to `not_started`)
- **done_list**: Completed cards (maps to `done`)
- **user_lists**: Personal lists per user — determines assignment

### Creating Trello-linked tasks
Use `create_trello_task` (NOT `create_task`) to create a card + skeleton in one step:
```
create_trello_task(project_id, "Quest System", "bob",
    description="Build the quest engine", checklist_items='["Design", "Build", "Test"]')
```

### Adopting existing cards
Use `adopt_trello_card` to link an existing Trello card to a new skeleton:
```
adopt_trello_card(project_id, board_name, "bob", card_title="NPC Dialogue")
```

### Project view — grouped by Trello list
`get_project_detail` renders Trello-linked projects grouped by board list in
left-to-right order. This is **direct-display** output — do NOT reformat it.
```
--- Trello: Bob TODO [bob] ---
  T1 Quest System (checklist: 3/7)
  T2 Sub-Region System (checklist: 1/4)

--- Trello: Backlog ---
  T4 NPC Dialogue

--- Local tasks ---
  T7 Define Project-Alpha roadmap — NOT_STARTED
```

### Task detail — live card data
`get_entity_detail` on a Trello-linked task fetches live: description, numbered
checklists, labels, due date, completion %, card URL, and comments.

### Status changes move cards
| Action | Trello effect |
|--------|---------------|
| Mark done | Card → done_list |
| Mark in_progress | Card → user's personal list |
| Mark not_started | Card → backlog_list |

### Assignment changes move cards
"Assign T3 to Dave" → card moves to Dave's Trello list (from `user_lists`).

### Bidirectional delete
- Delete task in Skipper → archives the Trello card
- Card archived in Trello → skeleton auto-removed on next project view

### Checking off checklist items
Use `check_trello_item` to check/uncheck individual items on a Trello card's checklist.
Item numbers match the ☐/☑ display order from `get_entity_detail`.
```
check_trello_item("T1", 1)          # check first item
check_trello_item("T1", 3, "false") # uncheck third item
```
When the user says "check off item 1 on T1" or "mark the first criterion done",
call `check_trello_item` directly — do NOT call `get_entity_detail` first.

### Due date and name sync
Changing a task's due_date or name in Skipper also updates the Trello card.

## Combination Patterns

### Full project lifecycle
1. Create goal (g-*) with target date
2. Create projects (p-*) with milestone tasks (t-*)
3. Add subtasks under milestones for each person's work
4. Set task order and dependencies
5. Enable auto-nag on key projects
6. Attach reference docs as artifacts (a-*)
7. Set due date reminders on tasks (r-* linked to t-*)
8. Track progress via update_item → nag auto-advances through tree
9. Reminders fire → notifications (n-*) delivered

### Cross-goal dependency
- Task in Goal A depends on task in Goal B → `set_task_dependency(t-A, "t-B", "alice")`
- When t-B completes, t-A is automatically unblocked
- If t-A's project has auto-nag, the nag will pick it up next

### Seasonal/annual recurring workflows
- Create goal: "Annual tax prep" → tasks for each step → yearly recurring reminders
