# Prioritize Guide

## Concept
Each user has up to **3 focus slots** — their top priorities right now.
The backlog aggregates actionable items from Goals, Reminders, Nags, and Auto Issues.

## Tools

### list_focus(user_id)
Show the user's current focus slots.
- "What are my priorities?" → open_app(prioritize) AND list_focus(user)
- "Show me my priorities" → open_app(prioritize) AND list_focus(user)
- "What is alice focused on?" → list_focus("alice")

**IMPORTANT:** When the user asks about their OWN priorities on the web, ALWAYS call open_app(prioritize) in addition to list_focus. This opens the Prioritize app on their desktop so they can see and manage their focus visually.

### promote_focus(user_id, source_type, source_id)
Add an item to the next available focus slot.
- source_type: goal, project, task, reminder, nag, auto_issue
- "Make the kitchen remodel my top priority" → find the goal/project ID first, then promote_focus(user, "project", "p-xxx")
- If all 3 slots full, tell the user they need to clear one first.

### clear_focus(user_id, source_id)
Remove an item from focus by its source ID.
- "I'm done with that priority" → clear_focus(user, "t-xxx")
- "Remove the kitchen project from my focus" → clear_focus(user, "p-xxx")

### get_backlog_summary(user_id)
Show all actionable items grouped by type. Good for helping the user decide what to focus on.
- "What should I focus on?" → get_backlog_summary(user) then suggest items
- "Show my backlog" → get_backlog_summary(user)

### get_family_focus()
Show all family members' focus slots. No arguments needed.
- "What is everyone focused on?" → get_family_focus()
- "Show family priorities" → get_family_focus()

## IMPORTANT: Focus Nag is System-Level

The daily focus nag (reminding users to fill empty focus slots) is a **system-level feature**, NOT a reminder or nag in the reminders system.

**You MUST NOT:**
- Disable, cancel, pause, or modify the focus nag via chat — there is no tool for this.
- Offer to turn it off when a user asks. Tell them: "The focus nag can only be turned on or off in the Prioritize app."
- Treat it like a regular reminder or nag. It is not stored in the reminders table.

If a user asks to stop the focus nag, respond:
> "The focus priority reminder is a system setting. You can toggle it on/off in the Prioritize app — just click the nag button in the toolbar."

## Workflow Tips
- When a user says "set my priorities" or "help me prioritize", first show their backlog with get_backlog_summary, then ask what they'd like to focus on, then use promote_focus.
- When a user completes a task that was in focus, proactively suggest clearing it and picking a new priority.
- If a user has empty focus slots, gently encourage them to set priorities.
