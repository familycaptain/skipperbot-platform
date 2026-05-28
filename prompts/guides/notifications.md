# Notifications Guide

Notifications are automatically created when reminders fire or jobs complete.
Use `get_recent_notifications` to answer "what did you tell me?" or "show my alerts".
You do not need to create notifications manually — they are system-generated.

## Workflows

### View recent notifications
- "What did you tell me today?" → get_recent_notifications(recipient=user)

### Filter by source
- "Show me all reminder notifications" → get_recent_notifications(source_type="reminder")

### Trace back to source
- Notification has source_id (e.g. r-*) → look up the reminder, then follow links to find related task/goal

### Check delivery
- get_recent_notifications(source_id=r-*) → shows delivered=true/false

### End-of-day summary
1. Pull get_recent_notifications for today
2. Pull get_my_tasks for user (in_progress items)
3. Check any due reminders
4. Search auto-memories for today's entity changes
5. Compile into a summary delivered via Discord DM
