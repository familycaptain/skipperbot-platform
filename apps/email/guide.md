# Email — App Guide

## Overview
Gmail integration for the family. Connect Gmail accounts via OAuth, define
inbox rules to automatically label, archive, or mark messages as read, and
view a log of processed emails.

## Features
- **OAuth Connect** — Link Gmail accounts via Google OAuth 2.0
- **Inbox Rules** — From/subject/body matching with label, archive, mark-read actions
- **Activity Log** — History of processed emails and which rules matched
- **Manual Sync** — Trigger sync on demand; scheduled sync via job queue

## Entity Types
| Prefix | Entity         | Description                  |
|--------|----------------|------------------------------|
| `ea`   | Email Account  | Connected Gmail account      |
| `er`   | Email Rule     | Processing rule for account  |
| `el`   | Email Log      | Record of processed message  |

## API Endpoints
All mounted at `/api/apps/email/`:

- `GET /accounts?user=<id>` — List connected accounts
- `GET /oauth/start?user=<id>&display_name=<name>` — Start OAuth flow
- `GET /oauth/callback` — OAuth callback (Google redirects here)
- `DELETE /accounts/<id>` — Disconnect account
- `PATCH /accounts/<id>` — Update account settings
- `GET /rules?account_id=<id>` — List rules
- `POST /rules` — Create rule
- `PATCH /rules/<id>` — Update rule
- `DELETE /rules/<id>` — Delete rule
- `POST /rules/reorder` — Reorder rules
- `GET /log` — View processed email log
- `POST /sync?account_id=<id>` — Trigger manual sync
