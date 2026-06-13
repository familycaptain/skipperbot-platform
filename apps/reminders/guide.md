# Reminders & Nags Guide

## One-Shot Reminders
- "Remind me at 3pm to call the vet" → set_reminder(user, message, remind_at)
- Auto-memory logged: [created] reminder r-*

## Recurring Reminders
- "Remind me every Monday at 9am to check email" → set_reminder with rrule="FREQ=WEEKLY;BYDAY=MO"
- Supports RRULE strings: FREQ=DAILY, FREQ=WEEKLY;BYDAY=MO,WE,FR, FREQ=MONTHLY;BYDAY=3TU, etc.

## Cancel / Modify
- "Cancel that reminder" → cancel_reminder_by_id(r-*)
- "Change that to 10am" → modify_reminder_by_id(r-*, remind_at=new_time)

## Smart Timing — Events vs Actions

**TWO MANDATORY RULES for events/appointments:**
1. **Set the reminder REMINDER_LEAD_MINUTES before the event time** (check your system prompt for the value — currently 120 minutes / 2 hours). NEVER set it at the event time.
2. **ALWAYS include the actual event time in the reminder message text.** The person needs to know when the event is.

**Event examples** (REMINDER_LEAD_MINUTES = 120 → remind 2 HOURS before):
- "Remind me I have a doctor's appointment Monday at 3:30pm" → set_reminder at **1:30 PM**, message: "Doctor's appointment at 3:30 PM"
- "Bob has soccer practice at 5pm tomorrow" → set_reminder at **3:00 PM**, message: "Bob has soccer practice at 5:00 PM"
- "Remind john at 2:30pm he has to meet his teacher" → set_reminder at **12:30 PM**, message: "Meet your teacher at 2:30 PM"
- "We have dinner reservations at 7" → set_reminder at **5:00 PM**, message: "Dinner reservations at 7:00 PM"

**Action examples** (remind AT the stated time — no lead time):
- "Remind me to call the vet at 3pm" → set_reminder at 3:00pm exactly
- "Remind me at 9am to check email" → set_reminder at 9:00am exactly

**Vague time of day** — when a reminder gives only "morning / afternoon / evening
/ night" with no clock time, resolve it using REMINDER_TIME_SLOTS from your system
prompt (defaults: morning 08:00, afternoon 13:00, evening/night 19:00).
- "Remind me tomorrow morning to take out the trash" → set_reminder at tomorrow 08:00
- "Remind me this evening to water the plants" → set_reminder at today 19:00

The key distinction: if the time describes **when something happens** (an event/appointment/meeting), subtract REMINDER_LEAD_MINUTES and include the event time in the message.
If the time describes **when to do something** (an action), remind at that time.
When in doubt, add lead time — it's better to be early than late.

## Nag Reminders

**DECISION RULE — set_nag vs set_reminder:**
If the request has **no specific date or time**, use `set_nag`. Key trigger phrases:
- "don't let me forget", "don't forget to", "don't let X forget"
- "nag me", "keep reminding me", "bug me about"
- "I need to remember to..." (no time given)
- Any open-ended "remind me to X" with **no when** → `set_nag`

Only use `set_reminder` when there is a **specific date, time, or recurrence pattern**.

Nags are **low-ceremony persistent nudges** — unlike reminders (which fire at a specific time
for a specific reason), nags are gentle daily pokes that say "hey, don't forget about this."
They're ideal for things that don't have a deadline but shouldn't be forgotten.

- "Nag me to clean the garage" → set_nag(user, message) — fires once daily at a random waking hour until cancelled
- "Don't let Bob forget to return his library books" → set_nag(bob, message)
- "Don't let me forget to do my taxes" → set_nag(user, "Do your taxes")
- No time needed — the system picks random times during waking hours
- Multiple nags for the same user are spread throughout the day
- Cancel with cancel_reminder_by_id when the task is done
- Auto-nag on projects (`enable_project_nag`) uses the same mechanism but automatically
  advances to the next task in the tree when one is completed

### Time-of-day scoping

Nags can optionally be scoped to a part of the day using `time_slot`:
- **morning** → 7 AM – 12 PM
- **afternoon** → 12 PM – 5 PM
- **evening** / **night** → 5 PM – 9 PM
- *(empty)* → any time during full waking hours (default)

Natural language patterns → `time_slot` mapping:
- "nag me every morning to check on X" → set_nag(user, message, time_slot="morning")
- "nag me in the evening to review Y" → set_nag(user, message, time_slot="evening")
- "don't let me forget in the afternoon to call Z" → set_nag(user, message, time_slot="afternoon")
- "bug me every night to take meds" → set_nag(user, message, time_slot="night")
- "nag me to clean the garage" → set_nag(user, message) — no time_slot, any waking hour

## Snoozing / Follow-up

When a reminder or nag fires and the user says they're busy, use `snooze_reminder` to
create a one-time follow-up. The original reminder is untouched — a brand new one-shot
reminder is created with the same message, firing at `now + duration`.

```
snooze_reminder(
    reminder_id="r-a1b2c3d4",   # the reminder that just fired
    duration="1h",                # human-readable: "30m", "2 hours", "1h30m", "90"
)
```

### How it works:
1. Reminder/nag fires → notification appears in chat log as `⏰ Reminder [r-abc]: ...`
2. User says "I'm busy, come back in an hour"
3. You call `snooze_reminder(r-abc, "1h")`
4. New one-shot reminder created (e.g. `r-xyz`) firing in 1 hour with same message
5. When the follow-up fires, the user can snooze it again — no limit

### Key details:
- The original reminder is **never modified** (nags still advance to tomorrow, recurring advances normally)
- Follow-up messages get a 🔁 prefix to distinguish from the original
- Duration supports: `30m`, `1h`, `1h30m`, `2 hours`, `90 minutes`, `45`, `1.5h`
- A bare number is treated as minutes
- The `snoozed_from` field on the follow-up links back to the original

### Natural language patterns:
| User says | Action |
|-----------|--------|
| "come back in an hour" | `snooze_reminder(r-*, "1h")` |
| "remind me again in 30 minutes" | `snooze_reminder(r-*, "30m")` |
| "snooze that for 2 hours" | `snooze_reminder(r-*, "2h")` |
| "I'm busy, follow up later" | `snooze_reminder(r-*, "1h")` (default ~1h) |
| "yeah yeah, try again in 45 minutes" | `snooze_reminder(r-*, "45m")` |
| "bounce it back 90 minutes" | `snooze_reminder(r-*, "90m")` |
| "put it off for an hour" | `snooze_reminder(r-*, "1h")` |

## Due Date Reminders on Entities
- "Remind me 3 days before the septic deadline" → set_due_reminder(p-*, user, days_before=3)
- Creates r-* linked to p-* via lnk-* with relation "reminds_about"

## Delivery
- Scheduler checks every 30s → delivers via Discord DM (all users) + Pushover (Alice only)
- Notification (n-*) auto-created on delivery

## Combination Patterns

### Reminder linked to a task
- Create reminder about a task → link_entities(r-*, t-*, relation="reminds_about")
- When reminder fires, look up linked task for context

### Recurring check-in on a project
- set_reminder with rrule for weekly check-in → link to p-*
- Each time it fires, pull project status and include in message

### Family coordination
- Bob asks "Tell dad to pick up milk" → send DM to Alice + set reminder at 5pm
- Set reminder linked to shopping list for context

### Recurring review cadence
- Set weekly recurring reminder linked to goal → each week pull get_goals_summary
