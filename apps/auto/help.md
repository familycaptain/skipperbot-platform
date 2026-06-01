# Auto Maintenance

A logbook for every household vehicle — service history, what's due, open issues,
condition checks, and value over time.

## Overview

Add each vehicle once, then log what you do to it. Auto keeps a searchable
service timeline, tracks recurring maintenance and oil changes (so it can tell
you what's coming up), records issues until they're fixed, and stores periodic
condition snapshots and blue-book valuations. Most people drive it from chat
("I got an oil change today…") and check the app for the full picture.

## Screens

- **Vehicle list.** All your vehicles with a quick summary (name, odometer,
  anything due).
- **Vehicle detail.** Opens one vehicle and shows its:
  - **Service history** — the timeline of oil changes, tire rotations, repairs,
    inspections, etc., with dates, mileage, cost, and notes.
  - **Upcoming maintenance** — recurring items and oil-change tracking that are
    due or coming up.
  - **Issues** — open problems (check-engine light, windshield chip) and their
    resolution.
  - **Condition reports** — periodic snapshots of brakes/tires/battery/etc.
  - **Valuations** — recorded private-party / trade-in values over time.

## Example workflows

**Add a vehicle**
- *In the app:* add a vehicle (make/model/year, optional VIN/plate, current odometer).
- *Through chat:* "add my 2016 F-150, about 62,000 miles".

**Log a service**
- *In the app:* open the vehicle → add a service record (type, date, mileage, cost, shop/notes).
- *Through chat:* "log an oil change for the truck at 62,000 miles, $45 at Jiffy
  Lube". (Logging an oil change with mileage auto-starts oil tracking — roughly
  every 5,000 miles — so Skipper can nag you when the next one's due.)

**See what's due**
- *In the app:* the vehicle's "upcoming maintenance" section.
- *Through chat:* "what's overdue on the truck?" or "what maintenance is coming up?"

**Recurring maintenance**
- *Through chat:* "remind me to rotate the tires every 6 months" creates a
  recurring schedule; later "I rotated the tires" marks it done and logs the
  service, advancing the next due date.

**Track issues / value / condition**
- *Through chat:* "the windshield has a chip" (logs an issue), "the truck's KBB
  value is $18k" (valuation), "brakes and tires are good, battery is weak"
  (condition report).

## Tips

- Recurring maintenance and due-date reminders pair with the **Reminders/Schedules** apps.
- Mention current mileage any time ("the truck's at 64,000 now") and Skipper updates the odometer and checks if the oil change is due.

## Your data

Every vehicle, service record, issue, condition report, and valuation is **saved
in the database and pulled into Skipper's memory** — so you can ask "when did we
last rotate the tires?" or "what did the last oil change cost?" and Skipper
recalls it. It stays within your household.
