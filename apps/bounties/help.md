# Bounties

A chore-and-reward system: parents post paid tasks, kids complete them to earn
credit, and the app tracks balances and payouts.

## Overview

Bounties is the **money** side of chores (recurring unpaid chores live in the
**Chores** app). A parent posts a task worth a dollar amount; a kid does it and
submits it; the parent approves, which credits the kid's balance. When the parent
actually pays out (cash, Venmo), they record the payment, which debits the
balance. There's a leaderboard for a little friendly competition.

## Screens

- **Bounties list.** Open/claimed/completed tasks with their dollar values; filter
  by status or category. Recurring **templates** auto-regenerate new bounties.
- **Balances.** Each kid's current earned-but-unpaid balance.
- **Leaderboard.** Family rankings — all-time, this month, or this week.

## Example workflows

**Post a bounty (parent)**
- *In the app:* create a bounty (title + dollar value), or set up a recurring template.
- *Through chat:* "post a $5 bounty to clean the garage".

**Complete one (kid)**
- *Through chat:* "I mowed the lawn" → Skipper finds the matching open bounty and
  submits it for approval.

**Approve + pay (parent)**
- *Through chat:* "approve the lawn bounty" (credits the kid), then later
  "I paid Alice $20 in cash" (debits the balance).

**Check standings**
- *Through chat:* "what's my balance?", "who's leading the bounty board this month?"

## Tips

- Only **parents/admins** can create bounties, approve/reject, and record payments.
- Values are dollars in chat ("$15") — the app stores them precisely.
- Use **Bounties** for paid one-offs; use **Chores** for the recurring unpaid rotation.

## Your data

Bounties, submissions, approvals, balances, and payments are **saved in the
database and pulled into Skipper's memory**, so you can ask "how much has Alice
earned this month?" and Skipper knows. It stays within your household.
