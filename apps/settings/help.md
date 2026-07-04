# Settings

One place to configure Skipper — platform-wide options, integration keys, family
members, and each app's own settings.

## Overview

Settings is the control panel. It gathers the platform-level options plus every
installed app's own settings into one screen, so there's a single place to tune
how Skipper behaves and to plug in optional services. Secrets you enter (API keys,
tokens) are stored encrypted. Some options need a restart to take effect — those
are marked.

## Screens (panels)

- **System.** Timezone, default location (city / region / country), AI model names, LAN/public URLs, and
  display/debug flags. Items marked **↻ restart** apply after a server restart.
- **Integrations.** Cross-cutting service credentials — Discord, Brave Search,
  Weather, OpenAI admin, etc.
- **Members.** Add/remove family members, set roles, and reset passwords (admins);
  anyone can change their own password. (The single owner shows a read-only
  ★ "primary" badge.)
- **Per-app settings.** Every app that has options shows its own panel (e.g.
  Backups destinations, Reminders lead time). Apps with no options aren't listed.
- **Desktop.** Show/hide app launcher icons.

## Example workflows

**Set up the basics**
- *In the app:* System → set your timezone and default location — your city /
  region / country (the Weather app and chat use it). Restart if a setting is flagged ↻.

**Add an integration**
- *In the app:* Integrations → paste the key (e.g. a Weather or Discord token);
  it's saved encrypted.

**Manage the family**
- *In the app:* Members → add a person, set their role, or reset a password.

**Tune an app**
- *In the app:* open that app's panel here (or its cog) and adjust its options.

## Tips

- Restart-required settings are labeled — change them, then restart Skipper.
- Secrets are encrypted at rest; they never appear in chat.
- Most things now live here rather than in `.env`; an app with no options simply won't show a panel.

## Your data

Settings values are **saved in the database** (secrets encrypted). This is
configuration rather than day-to-day records, so it isn't surfaced as recallable
"memory"; it shapes how Skipper and the apps behave. Everything stays within your
household.
