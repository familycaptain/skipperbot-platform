# Chores — LLM Guide

This is the **recurring weekly chore rotation** for the kids — replacing the
old Chore Manager spreadsheet. **NOT** for one-off paid tasks; those live in
the Bounties app. If a request involves dollar amounts, payments, balances,
or "earn money / I want to earn $X" → route to **Bounties** instead.

## Cast

- **Kids in rotation**: Kid One, Kid Two, Kid Three. Each is a row in `kids` (id
  prefix `kid-`) and is linked to a `public.users` row by `kids.user_id` —
  the values are usernames like `kid1`, `kid2`, `kid3`.
- **Parents** (alice, bob) — have full CRUD over kids, zones, chores.
- **Zones** (`cz-`) group rotating chores. Today there are three:
  - **Bathroom** — rotates Kid One → Kid Two → Kid Three, chores on Tuesdays
    (thorough) and Fridays (quick).
  - **Bedroom - Kid One** — Kid One solo, chores Mon / Wed / Thu.
  - **Bedroom - Shared** — Kid Two & Kid Three, chores Mon / Wed / Thu.

## Rotation rule

For a zone with `N` members and `K` chores on a given day, the kid for
chore `i` (0-indexed) on `target_date` is:

```
day_number   = NETWORKDAYS(zone.rotation_start, target_date)   # Mon-Fri only
chore_i_kid  = members[(day_number + i) mod N]
```

This is computed on the fly — there is no "today's schedule" table. Pull
the current view with `get_chores_today`.

## Caller identity

Every mutating tool takes `acted_by` — pass the calling username
(e.g. `"kid1"`, `"alice"`). Permissions:

| Tool family | Who can call |
|-------------|--------------|
| Read (`get_chores_today`, `get_chores_week`, `list_kids`, etc.) | anyone |
| `complete_chore` / `uncomplete_chore` | the kid themselves OR a parent |
| `add_kid`, `update_kid`, `remove_kid` | parent only |
| `add_zone`, `update_zone`, `remove_zone` | parent only |
| `add_chore`, `update_chore`, `remove_chore` | parent only |

## Replying to the 9 AM morning push

The morning DM is saved as a chatlog turn (a fake user message of
`[Skipper sent the scheduled 9:00 AM chore push]` followed by the
assistant DM that lists each chore with its `[ch-XXXXXXXX]` id). When the
kid later replies "did it" / "done" / "did the vacuum", that prior turn
is in the LLM session — use it to resolve the chore ID(s) the kid is
acknowledging.

- "did it" / "done" with **one** assignment → call `complete_chore` with
  that single `ch-` id.
- "did it" / "did them all" / "all done" with **multiple** → call
  `complete_chore` once per chore (loop).
- "did the vacuum" / "did the laundry" → match the chore name against
  the assigned chores in the prior turn, pass the matching `ch-` id.
- If you can't find a matching chore in today's assignments for the
  caller, say so — don't fabricate a check-off.

## Natural-language → tool mapping

| User said... | Tool | Args |
|--------------|------|------|
| "What are my chores today?" / "What does Kid Three have today?" | `get_chores_today` | `kid="kid3"` or `""` (all) |
| "Show me the whole week" | `get_chores_week` | optional `kid`, `start_date` |
| "Mark my bedroom vacuum done" (caller=kid1) | `complete_chore` | `kid="kid1"`, `chore="vacuum"`, `acted_by="kid1"` |
| "I did everything" (caller=kid2) | call `get_chores_today` first, then loop `complete_chore` for each |
| "Undo my laundry check-off" | `uncomplete_chore` | `kid="...", chore="laundry", acted_by="..."` |
| "What did Kid Three do last week?" | `get_chore_history` | `kid="kid3"`, `date_from`, `date_to` |
| "Add a new chore: empty trash on Thursday in the bathroom zone" | `add_chore` | `zone="Bathroom"`, `dow="Thursday"`, `name="Empty Trash"` |
| "Rename the toilet chore to scrub the toilet" | `update_chore` | `chore_id="ch-...", name="Scrub the Toilet"` |
| "Take Saturday vacuum off the list" | `remove_chore` | `chore_id="ch-..."` |
| "Reset rotation for Bathroom to start today" | `update_zone` | `zone="Bathroom"`, `rotation_start="2026-05-20"` |
| "Switch the bathroom rotation order to Kid Three, Kid One, Kid Two" | `update_zone` | `zone="Bathroom"`, `member_kids="Kid Three, Kid One, Kid Two"` |
| "Add a new kid named Sam" | `add_kid` | `name="Sam"` |

## Things to be careful about

1. **Bounties confusion.** If money is mentioned at all (`$`, "earn", "pay",
   "balance", "leaderboard"), it's almost certainly Bounties, not Chores.
2. **Fuzzy chore names.** `complete_chore` accepts `chore="vacuum"` and
   matches it against the kid's *assigned* chores for the date. If there's
   no match (the kid doesn't have that chore today), the tool will say so —
   don't fabricate a completion.
3. **Today vs target_date.** The rotation is deterministic; don't guess.
   Always pull `get_chores_today` to see who's actually assigned what.
4. **Permission failures.** If a kid tries to check off another kid's chore,
   the tool returns an error message — relay it; don't retry as that kid.
5. **Rotation-shuffle warning.** Changing `member_kids` on a zone shuffles
   *every future assignment* because of the modulo math. If the user is
   surprised, suggest also resetting `rotation_start` to today.
6. **Acked DOWs.** `add_chore` accepts both numeric (0=Sun..6=Sat) and
   names (`"Tue"`, `"Tuesday"`). Postgres' `extract(dow)` convention.
7. **Soft-deletes.** `remove_kid` and `remove_chore` are soft (active=FALSE)
   to preserve completion history. `remove_zone` is hard but blocked if
   completions exist on its chores.

## Daily flow

- **9:00 AM** — Skipper sends each kid (with `notify_morning = TRUE` and
  at least one assignment) a push listing their chores. Implemented in the
  `chores_morning` job — runs from `apps/chores/handlers.py`.
- Kids check off chores throughout the day, either in the Chores web app
  or by chatting with Skipper ("I did my vacuum").
- All siblings see all chores all the time — but each kid can only tick
  their own boxes.
