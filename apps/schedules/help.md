# Schedules

The platform's recurring-event engine and calendar — one place where everything
that repeats (chores, maintenance, appointments, medical, bills) computes its
"next due."

## Overview

Schedules is the single source of recurring work. Instead of scattered cron jobs,
anything that repeats flows through here — by friendly cadence (daily, weekly,
monthly, yearly), by rule (RRULE/cron), by interval, or even usage-based ("every
5,000 miles"). It tracks each item's next-due date and keeps a completion log.
Other apps (Chores, Auto, Medical, Home) ride on top of it, and the calendar view
aggregates occurrences alongside reminders and due tasks.

## Screens

- **Calendar / schedule view.** Everything happening — recurring occurrences,
  reminders, and items with due dates — in one place.
- **Schedule detail.** A recurring item's recurrence rule, next-due, and
  completion history.

## Example workflows

**Create a recurring schedule**
- *In the app:* add a schedule with a cadence (weekly on Tue/Thu, monthly, etc.).
- *Through chat:* "schedule soccer practice every Tuesday and Thursday at 5",
  "add a monthly bill-pay reminder".

**See what's coming**
- *In the app:* the calendar/schedule view for the week or weekend.
- *Through chat:* "what's on the calendar this weekend?", "what's due this week?"
  (Skipper answers these through Goals/Reminders/Chores, which read Schedules
  underneath.)

## Tips

- Everything recurring lives here — there's no separate cron to manage.
- One-time nudges are better as **Reminders**; assignable work with due dates is
  better as **Goals** tasks. Schedules powers the *recurrence* behind apps like
  **Chores**, **Auto**, **Medical**, and **Home**.

## Your data

Your recurring schedules and their completion log are **saved in the database and
surfaced to Skipper's memory** (usually via the app that owns each item), so
"what's due this week?" works. Everything stays within your household.
