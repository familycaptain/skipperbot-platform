# Bounties — Tool Guide

## Overview
Family chore-and-reward system. Parents define tasks with dollar values, kids complete them for balance credits.

## Workflow

### Creating bounties (parent/admin only)
- Use `create_bounty` for one-off tasks
- Templates (recurring) are managed in the UI — they auto-regenerate on approval

### Completing bounties (kids)
- Use `submit_bounty` when a kid says they did a chore
- Match what they said to an open bounty: "I mowed the lawn" → find the matching open bounty and submit it

### Approving/Rejecting (parent/admin only)
- Use `approve_bounty` to confirm completion — this credits the kid's balance
- Rejected bounties return to open status for someone else to try

### Checking balances
- Use `get_bounty_balance` with a username to check one person's balance
- Use `get_bounty_balance` with no args to see all balances

### Recording payments (parent/admin only)
- Use `record_bounty_payment` when a parent pays a kid externally (cash, Venmo, etc.)
- This debits the kid's balance

### Leaderboard
- Use `get_bounty_leaderboard` with period 'all', 'month', or 'week'

## Tools

- `list_bounties(status?, category?)` — list bounties with optional filters
- `get_bounty(bounty_id)` — full bounty detail
- `create_bounty(title, value_cents, created_by, category?, description?)` — create a one-off bounty
- `submit_bounty(bounty_id, submitted_by, note?)` — kid submits completion
- `approve_bounty(bounty_id, reviewed_by, note?)` — parent approves
- `get_bounty_balance(user_id?)` — check balance(s)
- `record_bounty_payment(user_id, amount_cents, recorded_by, payment_method?, note?)` — log external payment
- `get_bounty_leaderboard(period?)` — family rankings

## Key rules

1. **All values in cents** — 1500 = $15.00. Convert from dollars if the user says "$15".
2. **Only parent/admin can**: create bounties, approve/reject, record payments.
3. **Anyone can submit**: kids submit completion, parents approve.
4. **Recurring bounties**: managed via templates in the UI. On approval, the next instance auto-generates.
5. **Payment debits balance**: recording a payment reduces the kid's available balance.
