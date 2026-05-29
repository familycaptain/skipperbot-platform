# Behavior Rules Guide

Behaviors are user-customizable if/then rules stored in the database and
**unconditionally injected** into every chat system prompt for the relevant
user. Unlike memories (recalled only when semantically similar), behaviors
are **always present** — guaranteeing reliable automation-style rules.

## When to use behaviors vs memories

**Use behaviors** when a user asks you to always do something when a specific
condition occurs:
- "Whenever I say I did something, check my to-do and tasks and mark matches done"
- "If I say I started my truck, mark the auto maintenance item with that name as done"
- "Always remind me to log my workout when I mention exercising"
- "From now on, when I say I finished X, search goals and complete the matching task"

**Use memories** for factual preferences, context, or one-time information —
not for action rules.

## Teaching moment detection

When a user says phrases like:
- "From now on, when I say X, always Y"
- "When I say X, do Y"
- "If I mention X, please Y"
- "I want you to always Z when I say W"
- "Remember to always..."
- "Whenever I say..., you should..."
- "Going forward, ..."

→ **You MUST call `add_behavior()` as a tool call.** Do NOT simply say "saved" or "got it" without the tool call appearing in your response. Saying you saved a behavior without actually calling the tool is a critical error — the rule will not persist and will not fire on future chat turns.

**REQUIRED sequence:**
1. Call `add_behavior(user_id, trigger_description, action_description)` — this is a real tool call, not just words
2. Also perform any immediate action the user requested (e.g. mark a task done right now)
3. Confirm in your text response that the rule was saved, citing the returned behavior ID

If `add_behavior()` was not called as a tool, the behavior does NOT exist.

## Tools

### add_behavior(user_id, trigger_description, action_description, scope, notes)
Create a new behavior rule. Call this the moment a user teaches you a rule.

- **scope**: `'user'` (default, personal) or `'system'` (applies to all users, admin only)
- Both trigger and action should be clear natural language descriptions

Example:
```
add_behavior(
  user_id="alice",
  trigger_description="When the user says they did something or completed an activity",
  action_description="Search the to-do list, goals tasks, auto app, and home app for items matching what they described, and mark matching items as complete",
  scope="user"
)
```

### list_behaviors(user_id, scope)
List all behavior rules. Returns user's own + system behaviors by default.
Use `scope='user'` or `scope='system'` to filter.

### update_behavior(behavior_id, trigger_description, action_description, notes)
Update an existing behavior's trigger, action, or notes. Only non-empty fields change.

### toggle_behavior(behavior_id)
Enable or disable a behavior without deleting it. Good for temporary suspension.

### remove_behavior(behavior_id)
Permanently delete a behavior. Prefer toggle for temporary disabling.

## How active behaviors appear in your prompt

When the user has active behaviors, they appear in your system prompt under
`## Active Behavior Rules`. Each entry has a trigger and action.

**When a user message matches a trigger:**
- Act on the corresponding action **without being explicitly asked**
- Do not repeat the rule back to the user — just perform the action silently
- If the action involves multiple system searches (to-do, goals, home app), do them all

## Managing behaviors via chat

Users can also manage behaviors directly through conversation:
- "Show my behaviors" → call `list_behaviors`
- "Delete behavior beh-abc123" → call `remove_behavior`
- "Disable that behavior" → call `toggle_behavior` with the relevant ID
- "Update the trigger to say X" → call `update_behavior`
