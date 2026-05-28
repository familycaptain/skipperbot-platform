# Timers Guide

Timers are short, in-memory countdowns that fire a notification to the
requesting user when they expire. They are the right tool when the user says
"set a timer", "start a timer", "X second timer", "X minute timer", or
"countdown".

## Always act, never ask

When the user says "set a 30 second timer", "start a 5 minute timer",
"timer for 90 seconds for the eggs":
- Call `start_timer` IMMEDIATELY with the right duration.
- Do NOT ask "would you like me to set a timer?" — just do it.
- Do NOT ask for a name if one wasn't given — the label is optional.

## Sizing — timer vs reminder

- Sub-minute or short countdowns (seconds, single-digit minutes) → `start_timer`
- Wall-clock times ("at 3pm", "tomorrow morning", "when I get home") → `set_reminder`
- Anything 30+ minutes away → prefer `set_reminder`. Timers live in memory and
  do not survive an agent restart.

## Duration argument

`start_timer` accepts two integer args: `seconds` and `minutes`. Combine them
freely.

- "30 second timer" → `start_timer(user_id, seconds=30)`
- "5 minute timer" → `start_timer(user_id, minutes=5)`
- "timer for 1 minute 30 seconds" → `start_timer(user_id, minutes=1, seconds=30)`
- "90 second timer" → either `seconds=90` or `minutes=1, seconds=30` — both work.

## Naming

If the user names what the timer is for, pass it as `name`:
- "5 minute timer for the pasta" → `start_timer(user_id, minutes=5, name="pasta")`
- "30 seconds for the eggs" → `start_timer(user_id, seconds=30, name="eggs")`
- "set a 2 minute timer" (no purpose) → `start_timer(user_id, minutes=2)` — leave name empty.

## Listing and cancelling

- "What timers do I have running?" → `list_timers(user_id)`
- "Cancel the pasta timer" → first `list_timers(user_id)` to find the id,
  then `cancel_timer(timer_id)`.
- "Cancel that timer" (just after setting one) → `cancel_timer` with the id
  returned by the most recent `start_timer` call.

## Who is the recipient?

The user who asked for the timer receives the notification. Always pass the
current user's canonical id (lowercase) as `user_id`. The notification is
delivered through the standard system — web UI, mobile push, Discord — so you
don't need to do anything else to make it audible.

## What firing looks like

When a timer expires, a notification with message `"⏱️ Timer done: <name>
(<duration>)"` is sent to the user. There is no follow-up reminder loop —
timers are one-shot.
