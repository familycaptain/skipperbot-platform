# Reminders

"Tell me X at time Y" — one-shot or recurring reminders that notify you (or
whoever you choose) at the right moment, with optional nagging and snooze.

## Overview

Reminders is for time-based nudges. Set a one-time reminder ("3pm, call the vet")
or a recurring one ("every Monday 9am"), aim it at yourself or another family
member, and it's delivered through your configured channels (in-app, Discord,
mobile). Turn on **nag** mode for things that must not be forgotten (it re-fires
until you acknowledge), and **snooze** when you need a little longer.

## Screens

- **Reminders list.** Your upcoming and recurring reminders, with their times and
  recipients; edit, snooze, or cancel here.
- **Edit reminder.** Time/date or recurrence rule, the message, recipient, and
  nag on/off.

## Example workflows

**Set a reminder**
- *In the app:* add a reminder — message, time, optional repeat, recipient.
- *Through chat:* "remind me to take the trash out at 7pm", "remind Jess about the
  dentist next Tuesday at 2", "remind me every Monday at 9 to check email".

**Events vs. actions (Skipper handles this for you)**
- For an *event* ("doctor's appointment Monday at 3:30"), Skipper sets the
  reminder ahead of time (a configurable lead, default 2 hours) and puts the
  event time in the message.
- For an *action* ("remind me at 3 to call"), it fires at exactly that time.

**Manage them**
- *Through chat:* "what reminders do I have today?", "change that to 10am",
  "snooze it an hour", "cancel that reminder".

## Tips

- The default lead time for events is set in **Settings → Reminders**.
- Use **nag** for must-not-miss items; it keeps reminding until you acknowledge.
- For recurring household work, **Chores**/**Schedules** may fit better than a plain repeat.

## Your data

Your reminders (one-shot and recurring) are **saved in the database and pulled
into Skipper's memory**, so "what's coming up?" works. They stay within your
household; delivery channels are configured in Settings.
