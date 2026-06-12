# App visibility — the three layers

Whether an app's tile shows up on your desktop is decided by **three independent
layers**, plus one structural rule. They're easy to mix up, so here's exactly what
each one does, who controls it, and when it takes effect.

Quick mental model — an app tile appears on **your** desktop only if **all** of
these are true:

```
   is a real tile (not a sub-view)      ← structural
   AND the app is enabled (loaded)      ← platform / admin
   AND you haven't hidden it            ← per-user
```

| Layer | Question | Who controls it | Scope | Set where | Takes effect |
|---|---|---|---|---|---|
| **0. Sub-view** | Is this even a launcher tile? | the app author | global | manifest `subview: true` | n/a (structural) |
| **1. Required vs optional** | Can it be turned off at all? | the platform | global | `REQUIRED_APPS` / `core: true` | n/a |
| **2. Enabled vs disabled** | Is the app loaded? | an **admin** | whole household | Settings → **Apps** | next **restart** |
| **3. Hidden vs shown** | Do *I* see the tile? | **each user** | just you | Settings → **My desktop** (or right-click a tile) | **immediately** |

---

## Layer 0 — Sub-views (structural)

Some app entries aren't standalone apps at all — they're **detail / viewer
windows** that open from somewhere else: a chart, a document, a recipe detail, a
folder view, the anime player. These carry `subview: true` in their registration
and **never get a launcher tile**. You can't toggle them; they appear only when you
open the thing they display.

Everything below applies only to **real tile apps** — never to sub-views.

## Layer 1 — Required vs optional

- **Required (core) apps** are part of the platform's contract (goals, reminders,
  settings, jobs, notifications, …). They're always loaded, can't be disabled, and
  the platform refuses to boot without them. Enforced by the `REQUIRED_APPS` list
  in `app_platform/loader.py` (and marked `core: true` in their manifest).
- **Optional apps** are everything else. They can be disabled (Layer 2).

This layer just decides *whether Layer 2 is even available* for an app.

## Layer 2 — Enabled vs disabled (platform, admin)

A platform-wide on/off switch, controlled by an **admin** in **Settings → Apps**.

- **Disabled = fully off for everyone.** A disabled app doesn't load at all — no
  chat tools, no REST routes, no background jobs, no thinking domains. It's not
  "hidden," it's *gone* until re-enabled.
- Required apps can't be disabled (the toggle is locked, and the API rejects it).
- Because apps are wired up at startup, **a disable/enable change takes effect on
  the next restart.**
- Stored in `disabled_apps` (platform config); the loader skips disabled apps.

Use this to remove a capability from the whole household (e.g. you don't want the
Bounties app at all).

## Layer 3 — Hidden vs shown (per-user)

A personal preference — **each user curates their own launcher**, with no effect on
anyone else and no effect on whether the app runs.

- **Hidden = the tile is gone from *your* desktop only.** The app is still loaded;
  its chat tools and routes still work; other users still see it.
- Set it two ways: **Settings → My desktop** (a show/hide list), or **right-click a
  tile on the desktop → "Hide from my desktop."**
- Takes effect **immediately** — no restart.
- It's an **opt-out** list (we store the ids you've hidden), which means **newly
  installed apps show up automatically** — you'd have to hide them on purpose.
- Stored per user at config scope `user:<name>`; the launcher filters your set.

Use this to declutter your own desktop (e.g. you never open Scriptures, so you hide
its tile — but your partner still sees theirs).

---

## How they combine — worked examples

- **Goals** — required, so always loaded; you *can* hide its tile from your own
  desktop (Layer 3), but no one can disable it (Layer 1/2).
- **Bounties** — optional. An admin disables it (Layer 2) → it's gone for everyone,
  tools and all, after a restart.
- **Anime** (installed) — optional and enabled. You hide it from your desktop
  (Layer 3) → your tile disappears instantly; your kid still has theirs; the app
  keeps running.
- **A recipe detail view** — a sub-view (Layer 0). It never shows as a tile and
  isn't in any of the lists; it opens when you click a recipe.

## "Why don't I see an app?" — quick diagnosis

1. **Is it a sub-view?** Then it's never a tile — open it from its parent app.
2. **Is it disabled?** Ask an admin to check Settings → Apps (a disabled app is off
   for everyone, and needs a restart to come back).
3. **Did you hide it?** Check Settings → My desktop and toggle it back to *Shown*.

See also [docs/02-adding-apps.md](02-adding-apps.md) for the app *kinds* (required /
bundled-optional / separate-repo) and how to install or remove one.
