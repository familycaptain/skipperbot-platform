# Email

Connect a Gmail account so Skipper can automatically triage your inbox with rules
you define, and keep a log of what it did.

## Overview

Email links one or more Gmail accounts (via Google sign-in) and applies your
**inbox rules** — match on sender/subject/body, then label, archive, or mark as
read. It syncs on a schedule (and on demand) and keeps an activity log of which
messages were processed and which rule matched. It stays idle until you connect
an account.

## Setup

In **Settings → Email**, start the Google sign-in (OAuth) to connect a Gmail
account (see `docs/03-extended-functionality.md` for the one-time Google setup).
You can connect more than one account and disconnect any of them later.

## Screens

- **Accounts.** Connected Gmail accounts; connect, disconnect, or adjust settings.
- **Rules.** Your inbox rules in priority order — each has match conditions
  (from/subject/body) and actions (label / archive / mark read). Add, edit,
  reorder, or delete them.
- **Activity log.** A history of processed messages and which rule matched, so you
  can see what the automation has been doing.

## Example workflows

**Connect an account**
- *In the app:* Settings → Email → connect with Google.

**Make a triage rule**
- *In the app:* Rules → add a rule, e.g. *from contains "school.edu" → apply label
  "School", mark read*.

**Run it now / review**
- *In the app:* trigger a manual sync, then check the activity log.
- *Through chat:* "any important emails today?", "summarize my unread mail".

## Tips

- Rules apply in order — put more specific rules above broader ones.
- Use it to keep noisy senders out of the way automatically (label + archive).

## Your data

Connected accounts, your rules, and the processed-email log are **saved in the
database and pulled into Skipper's memory**, so you can ask "what did the email
rules do today?" Your Google credentials are stored encrypted and never appear in
chat; everything stays within your household.
