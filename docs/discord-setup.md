# Setting Up Your Discord Bot

This guide walks you through giving Skipperbot a Discord presence so you can
chat with it from Discord — by DM or in a server channel — and receive
notifications there.

It's a one-time setup. Budget about 10 minutes. Discord is free.

> **New here?** Discord is an *optional* integration. Skipperbot works fully
> from the web UI without it. If you just want to try Skipper, skip this and
> come back later. For the one-paragraph version, see the Discord entry in
> [docs/03-extended-functionality.md](03-extended-functionality.md#discord);
> this page is the full walkthrough.

## What you get

- **Chat from Discord** — DM the bot, or talk to it in an allowed server channel.
- **Notifications on Discord** — reminders, schedule nudges, and any app
  notification routed to the `discord`, `both`, or `all` channel land as a DM.

## The three things people get wrong

Read these first — they're the cause of ~every "my bot is online but ignores
me" report:

1. **The Message Content Intent must be ON** (Step 2). Without it Discord
   sends your bot *empty* message text, so it sees that a message arrived but
   can't read a word of it — and stays silent.
2. **Your Discord account must be linked to your Skipper user** (Step 6). The
   bot **only responds to known users**; a message from an unlinked Discord ID
   is silently ignored by design.
3. **The token goes in Settings → Integrations, not `.env`** (Step 5). Skipper
   reads the Discord token from its encrypted settings store; there is no
   `.env` fallback for it.

---

## Step 1 — Create the Discord application + bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, give it a name (e.g. "Skipper"), accept the terms,
   and **Create**.
3. In the left sidebar, open **Bot**.
4. (Optional) Set the bot's avatar and username here — this is what your family
   sees in Discord.

## Step 2 — Enable the Message Content Intent (do not skip)

Still on the **Bot** page, scroll to **Privileged Gateway Intents** and turn on:

- ✅ **Message Content Intent** — *required*. This is what lets the bot read the
  text of messages. Skipper does nothing useful without it.

You can leave **Presence** and **Server Members** intents off; Skipper doesn't
use them.

Click **Save Changes**.

## Step 3 — Copy the bot token

On the **Bot** page, under the bot's username, click **Reset Token** →
**Yes, do it!** → **Copy**. Paste it somewhere safe for a minute.

> Treat this token like a password — anyone who has it can control your bot.
> If it leaks, come back here and **Reset Token** again to invalidate the old one.

## Step 4 — Invite the bot to your server

1. In the left sidebar, open **OAuth2 → URL Generator**.
2. Under **Scopes**, check **`bot`**.
3. Under **Bot Permissions**, check at least:
   - **Send Messages**
   - **Read Message History**
   (These cover server channels. DMs work regardless of server permissions, as
   long as you and the bot share a server.)
4. Copy the **Generated URL** at the bottom, open it in your browser, pick your
   server, and **Authorize**.

The bot now appears in your server's member list (offline until Step 5).

## Step 5 — Give Skipper the token

The token lives in Skipper's encrypted settings, **not** in `.env`.

1. Open the Skipper web UI and launch the **Settings** app.
2. Go to the **Integrations** panel.
3. Paste your bot token into the **Discord token** field and save.
4. **Restart Skipper** so the bot connects on boot:
   ```bash
   skipper restart
   ```
   If `skipper` isn't on your `PATH` yet, use `./skipper.sh restart`
   (Linux/macOS) or `skipper.bat restart` (Windows). The launcher handles both
   Docker and native installs — you don't need to know which is running.

Saving a token **automatically enables** Discord — there's no separate on/off
switch to flip. (Internally, `discord_enabled()` returns true as soon as a
token is configured.) After the restart, the bot shows as **online** in your
server and the boot log prints `DISCORD: Connected to N guilds`.

## Step 6 — Link your Discord account to your Skipper user

This is the step that makes the bot actually answer *you* — Skipper only
responds to a Discord account that's linked to a Skipper user. **Everyone who
wants to use Discord does this once, for their own account.**

1. **Find your Discord user ID.** In Discord, open **User Settings → Advanced**
   and turn on **Developer Mode**. Then right-click your own name (in any chat or
   the member list) → **Copy User ID** — a number like `123456789012345678`.
2. **Add it in Skipper.** Open the **Settings** app, go to **Members**, find the
   **My Discord** card, paste your Discord user ID, and click **Link Discord**.

That's it — no restart needed; the bot picks up the link within a few seconds.
To unlink later, clear the field in the same card and save. Each family member
signs in and repeats these two steps for their own account.

> A given Discord ID links to exactly one Skipper user — if you paste one that
> someone else has already linked, the form tells you and won't save it.

## Step 7 — Verify

**DM the bot** (the simplest, most reliable surface): click the bot in your
server's member list → **Message**, and send "hi". You should see a typing
indicator and a reply within a few seconds.

If it works, you're done.

---

## Using Discord with Skipper

### DMs (recommended)

DM the bot directly. It responds to any linked user, with no extra
configuration. This is the primary supported way to use Skipper on Discord.

### Server channels (optional)

The bot can also respond in **allowed** server channels (in an allowed channel
it replies to every message from a linked user — no @-mention needed). Channels
are opt-in: a channel must be on the allow-list before the bot will speak there,
so it never spams a busy server. Configuring allowed channels is an advanced
step; if you only ever DM the bot you can ignore it entirely.

### Routing notifications to Discord

Once you're linked, any notification sent on the `discord`, `both`, or `all`
channel is delivered to you as a Discord DM (reminders, schedule nudges, app
alerts). See the channel matrix in
[specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) for which value does what.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot shows **offline** in the server | No token saved (Settings → Integrations), or you didn't restart the agent after saving. Check the boot log for `DISCORD: Connected to N guilds`. |
| Bot is **online but ignores every message** | The **Message Content Intent** is off (Step 2) — the most common cause. Turn it on in the Developer Portal and restart. |
| Bot ignores **your** messages but works for someone else | Your Discord ID isn't linked (Step 6), or you linked the wrong number. Re-copy your User ID (Developer Mode) and re-enter it in **Settings → Members → My Discord**. |
| Bot replies in DMs but not in a server channel | That channel isn't on the allow-list — DMs are the simplest path; use those, or configure the channel. |
| `DISCORD: Bot failed to start` in the log | The token is wrong or was reset in the portal. Reset the token again (Step 3) and re-paste it into Settings → Integrations. |
| Notifications don't reach Discord | The recipient must be linked (Step 6), and the notification must use a Discord-bearing channel (`discord`/`both`/`all`). |

## Disabling Discord

Clear the **Discord token** field in Settings → Integrations and run
`skipper restart`. With no token configured, the bot doesn't start and Skipper logs
`STARTUP: Discord disabled`. Your data and the web UI are unaffected. To go
further and revoke the bot entirely, delete the application in the Developer
Portal.
