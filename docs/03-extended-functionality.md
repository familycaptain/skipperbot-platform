# Extended Functionality

This guide covers **optional integrations** — capabilities you can enable
by editing `.env` and restarting. Skipperbot runs fine without any of them;
each adds a specific capability.

Each section follows the same shape: **what it enables**, **cost**, **setup**,
**verify**.

---

## Capabilities at a glance

| Integration | Adds | Cost |
|---|---|---|
| [Discord](#discord) | Chat with Skipperbot from a Discord server | Free |
| [Brave Web Search](#brave-web-search) | Web search, research jobs, knowledge crawls | Free tier sufficient |
| [Trello](#trello) | Sync goals / tasks / lists with Trello boards | Free |
| [Resend](#resend-outbound-email) | Outbound transactional email | Free tier |
| [Gmail](#gmail-inbound) | Inbound email rules and the Email app | Free (requires Tier 3 deployment) |
| [FCM](#fcm-mobile-push) | Push notifications to mobile devices | Free |
| [Pushover](#pushover) | Alternative push channel | Modest one-time fee |
| [Home Assistant](#home-assistant) | Smart-home tools | Free if you already run HA |
| [Voice](#voice) | Wake-word voice via `skipperbot-voice` | Picovoice free tier |
| [Google Drive Backups](#google-drive-backups) | Off-machine backups to Drive | Free tier |
| [Weather](#weather) | Weather lookups via `skipperbot-app-weather` | Free tier from provider |
| [Going External](#going-external) | Access Skipperbot from outside your LAN | Varies |

After every change to `.env`, restart the agent. The startup banner will
show the integration switching `OFF → ON`.

---

## Discord

**What it enables:** Chat with Skipperbot from your Discord server.
Notifications can be routed to Discord as well. Without it, the web UI
is the only chat surface.

**Cost:** Free.

**Setup (short version):**

1. Create an application + bot at <https://discord.com/developers/applications>.
2. On the **Bot** page, enable the **Message Content Intent** (required — the
   bot can't read messages without it).
3. Copy the bot token and invite the bot to your server (OAuth2 URL Generator,
   `bot` scope, Send Messages + Read Message History).
4. Paste the token into **Settings → Integrations → Discord token** in the
   Skipper web UI, then restart the agent. (The token lives in Skipper's
   encrypted settings — **not** in `.env`.)
5. Link your Discord account to your Skipper user (so the bot knows it's you).

**Verify:** DM the bot — it should reply within a few seconds.

👉 **Full step-by-step walkthrough, including how to find your Discord user ID
and the most common "bot ignores me" fixes: [docs/discord-setup.md](discord-setup.md).**

---

## Brave Web Search

**What it enables:** Skipperbot can search the web. Used by the agent's
"look this up online" requests, by **research jobs**, and by **knowledge
crawls**. Without it, those features return a clear "no web search
configured" message.

**Cost:** Brave Search has a free tier sufficient for personal use.

**Setup:**

1. Sign up at <https://brave.com/search/api/>.
2. Create a free API key.
3. Add to `.env`:
   ```
   BRAVE_API_KEY=<your key>
   ```
4. Restart.

**Verify:** Ask Skipperbot "what's the weather in Paris?" — it should
respond with current info rather than "I can't search the web."

---

## Trello

**What it enables:** Sync Skipperbot's goals, projects, tasks, and lists to
a Trello board. Useful if your family already lives in Trello.

**Cost:** Free.

**Setup:**

1. Get a Trello API key + token at <https://trello.com/app-key>.
2. Add to `.env`:
   ```
   TRELLO_KEY=<your key>
   TRELLO_TOKEN=<your token>
   ```
3. Through the Settings app, link your Trello board IDs to Skipperbot lists/goals/tasks.
4. Restart.

**Verify:** Create a task in Skipperbot and confirm it appears as a card
on your Trello board.

---

## Resend (outbound email)

**What it enables:** Skipperbot can send transactional email. The Newsletter
app uses this for generated newsletters; the Email app uses it for outbound
replies.

**Cost:** Free tier (3,000 emails/month).

**Setup:**

1. Sign up at <https://resend.com>.
2. Verify a sending domain (or use the sandbox `onboarding@resend.dev` for testing).
3. Generate an API key.
4. Add to `.env`:
   ```
   RESEND_API_KEY=<your key>
   ```
5. Restart.

**Verify:** From Skipperbot, ask it to email you a test note. Confirm receipt.

---

## Gmail (inbound)

**What it enables:** Skipperbot can read your Gmail inbox, run rules
against it, and surface email in the Email app.

**Important:** Inbound Gmail OAuth requires a publicly-resolvable redirect
URI. **You need a Tier 3 deployment** (own domain + public TLS) for this
to work — see [Going External](#going-external) below.

**Cost:** Free (uses the standard Gmail API quotas).

**Setup:**

1. Complete a Tier 3 deployment so you have a public HTTPS URL.
2. In Google Cloud Console, create an OAuth 2.0 Client ID for a "Web application".
3. Add `https://your-domain/api/apps/email/oauth/callback` as an authorized redirect URI.
4. Add to `.env`:
   ```
   GMAIL_CLIENT_ID=<client id>
   GMAIL_CLIENT_SECRET=<client secret>
   GMAIL_REDIRECT_URI=https://your-domain/api/apps/email/oauth/callback
   ```
5. Install the Email app (`skipperbot-app-email`).
6. From the Email app, complete the OAuth flow.

**Verify:** Recent emails appear in the Email app.

---

## FCM (mobile push)

**What it enables:** Push notifications delivered to the `skipperbot-mobile`
app on phones. Without it, notifications still go to Discord and the web
UI; mobile push is silently disabled.

**Cost:** Free (Firebase free tier).

**Setup:**

1. Create a Firebase project at <https://console.firebase.google.com>.
2. Enable Cloud Messaging.
3. Generate a service-account JSON file and download it.
4. Place the file outside the repo (e.g. `~/firebase-skipper.json`) and reference it in `.env`:
   ```
   FCM_SERVICE_ACCOUNT_FILE=/home/you/firebase-skipper.json
   ```
5. Restart.

**Verify:** From Skipperbot, fire a test notification — your mobile app
should receive it.

---

## Pushover

**What it enables:** An alternative push channel — useful if you don't want
to run a mobile app but want phone notifications.

**Cost:** One-time ~$5 per platform.

**Setup:**

1. Sign up at <https://pushover.net>, create an app, get a key.
2. Add to `.env`:
   ```
   PUSHOVER_APP_TOKEN=<app token>
   PUSHOVER_USER_KEY=<your user key>
   ```
3. Restart.

**Verify:** Fire a test notification.

---

## Home Assistant

**What it enables:** Skipperbot can control your smart home through tools
that talk to Home Assistant — lights, switches, sensors, scenes, etc.

**Cost:** Free if you already run Home Assistant.

**Setup:**

1. In Home Assistant, create a long-lived access token (Profile → Long-lived access tokens).
2. Add to `.env`:
   ```
   HOME_ASSISTANT_URL=http://homeassistant.local:8123
   HOME_ASSISTANT_TOKEN=<your token>
   ```
3. Restart.

**Verify:** Ask Skipperbot "what lights are on?" — it should query Home
Assistant and respond.

---

## Voice

**What it enables:** Wake-word voice ("Hey Skipper") via the separate
`skipperbot-voice` companion service.

Voice runs as its own process (often on a different machine — a
Raspberry Pi or a desktop with a USB mic + speaker). It connects to the
platform's REST API.

**Cost:** Picovoice has a free tier sufficient for personal use.

**Setup:** Follow the `skipperbot-voice` repo's README — it walks through
per-OS audio device setup, Picovoice signup, wake-word model installation,
and obtaining a service token from the platform.

**Verify:** Say "Hey Skipper, what time is it?" — should respond.

---

## Google Drive Backups

**What it enables:** Off-machine backups to Google Drive in addition to
local DB backups. Without it, backups stay local.

**Cost:** Free tier (15 GB).

**Setup:**

1. Create a Google service account; share a Drive folder with it.
2. Download the JSON key.
3. Add to `.env`:
   ```
   BACKUP_GOOGLE_KEY_FILE=/path/to/key.json
   GDRIVE_IMPERSONATE_EMAIL=your-google-account@example.com
   ```
4. Restart.

**Verify:** From the Backups app, trigger a backup and confirm it appears in Drive.

---

## Weather

**What it enables:** Weather lookups via the `skipperbot-app-weather`
headless app (no UI — just MCP tools the agent calls).

**Cost:** Free tier from your chosen provider (OpenWeatherMap, etc.).

**Setup:**

1. Install the optional app: `cd apps && git clone https://github.com/familycaptain/skipperbot-app-weather.git weather && cd ..`
2. Sign up at your weather provider and get an API key.
3. Add to `.env`:
   ```
   WEATHER_API_KEY=<your key>
   ```
4. Restart the platform.

**Verify:** Ask Skipperbot "what's the weather?" — it should respond.

---

## Going External

By default Skipperbot listens on `localhost:8000` (or on your LAN IP if you
set `SKIPPER_LAN_URL`). To make it reachable from outside your home network
— for mobile use anywhere, Chromecast from off-LAN, Gmail inbound OAuth, or
just to share access with someone else — you have three sub-paths:

### Cloudflare Tunnel (easiest)

No port forwarding needed. No static IP needed.

1. Install `cloudflared` from <https://github.com/cloudflare/cloudflared>.
2. Authenticate: `cloudflared tunnel login`.
3. Create a tunnel: `cloudflared tunnel create skipper`.
4. Point a hostname at the tunnel (a free `*.trycloudflare.com` or your own DNS).
5. Set `SKIPPER_PUBLIC_URL=https://skipper.example.com` in `.env`.
6. Run the tunnel: `cloudflared tunnel run --url http://localhost:8000 skipper`.

### Tailscale Funnel

Similar — no port forwarding, no static IP.

1. Install Tailscale on the host.
2. `sudo tailscale up`.
3. `sudo tailscale funnel 8000`.
4. Set `SKIPPER_PUBLIC_URL=https://<host>.<tailnet>.ts.net` in `.env`.

### Domain + DDNS + port forward + Caddy (full control)

1. Register a domain.
2. Set an A record pointing at your home's public IP.
3. Install a DDNS client (`ddclient`, or your provider's DNS API).
4. Forward router port 443 → host port 8000.
5. Install Caddy: <https://caddyserver.com/docs/install>.
6. `deploy/Caddyfile.example` is a starting point; customize and copy to `/etc/caddy/Caddyfile`.
7. `sudo systemctl reload caddy`.
8. Set `SKIPPER_PUBLIC_URL=https://your-domain.com` in `.env`.

For all three paths, also:

- Update the Gmail OAuth redirect URI (Google Cloud Console) if you use Gmail.
- Update CORS configuration (handled automatically when `SKIPPER_PUBLIC_URL` is set).
- Verify access from a phone on cellular (not WiFi) to confirm external reachability.

---

## Disabling an integration

Delete or comment out the relevant `.env` line and restart. The startup
banner will show the integration as `OFF`. Any tools that depend on it
will return a "not configured" message when called.
