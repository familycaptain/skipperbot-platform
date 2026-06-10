# Medical

A private family health tracker — medications and refills, recurring treatments,
a medical-event journal, lab results over time, and medical-equipment upkeep.

## Overview

Medical keeps each family member's health records in one place. It tracks
**medications** (with refill reminders that nag until ordered, then until filled),
**treatments** (recurring procedures like injections/infusions), **events** (a
journal of visits, surgeries, labs, notes), **labs** (specific result values with
trend history), and **equipment** (devices with recurring maintenance). Everything
is tied to a family member and stays in your self-hosted database.

## Screens

- **Members.** The family members records are filed under (add a member first).
- **Medications.** Each med with dosage, days-left, and refill status
  (active → needs ordering → ordered → filled).
- **Treatments.** Recurring procedures with their next-due date and a per-instance log.
- **Events.** The medical journal — visits, procedures, labs, notes — with optional follow-up dates.
- **Labs.** Result values (e.g. Hemoglobin, Calcium) with history/trends.
- **Equipment.** Devices and their recurring maintenance tasks.

## Example workflows

**Track a medication + refills**
- *Through chat:* "Alice started amoxicillin today, 10-day course" → tracks it;
  Skipper nags when it's running low. Then "I ordered Alice's refill" / "picked it
  up" advances the cycle.

**Log a visit or lab**
- *Through chat:* "log Dave's annual physical on March 3", "record Bob's labs from
  yesterday: phosphorus 4.2, calcium 9.1" → stored with trend history.

**Recurring treatment**
- *Through chat:* "Eve gets her injection every 2 weeks" then "did Eve's injection
  today" → logs it and advances the next-due date.

**Look things up**
- *Through chat:* "when was Dave's last physical?", "show Alice's medication
  history", "what labs were taken on 3/3?", "what refills are coming up?"

## Tips

- Add the **member** before adding their records.
- Medications = scheduled doses with refill nags; **treatments** = recurring
  procedures. Follow-up dates on events create reminders.
- For homeopathic remedies specifically, use the **Homeopathy** app.

## Your data

This is sensitive health data — it's **saved in your self-hosted database and
pulled into Skipper's memory** so you can ask about it in chat, but it never
leaves your household. (Refill/treatment reminders are created automatically from
what you log.)
