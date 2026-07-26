# Findings — Settings

Survey only. Nothing here was fixed. "Uncertain" is marked where I could not settle it
from the code alone.

---

## Security / permissions

### 1. Reading every setting is not admin-gated; only writing is
`apps/settings/routes.py::api_list_app_settings`, `::api_get_app_settings`,
`::api_list_panels`, `::api_get_panel`

`PATCH /apps/{id}`, `PATCH /panels/{id}` and both `/platform` handlers call
`enforce_admin(request)`. The four GET handlers call **nothing** — not even
`require_user`. The platform's auth middleware means the caller must be signed in, so this
is not anonymous, but **any** household member (including an account holding only `kid`)
can read:

- the household's home location label and timezone,
- the LAN and public URLs of the install,
- the Discord channel ids Skipper is allowed to reply in,
- the default printer address,
- every app's non-secret config values (backup destinations, Trello board names, nag
  windows, …),
- and, via `_panel_field_json(include_set=True)` / `_serialise_config_key`, a `set: true`
  flag per credential — i.e. an inventory of which integrations the household holds keys for.

Secret *values* are correctly blanked, so this is disclosure of configuration, not of keys.
Expected: the read side gated the same way as the write side (`enforce_admin`), or a
deliberate decision recorded that install configuration is readable by all members.
`GET /platform` **is** admin-gated, which makes the inconsistency look accidental.

### 2. `PATCH /platform` is a schema-free write that bypasses secret encryption
`apps/settings/routes.py::api_patch_platform_settings`

The handler writes arbitrary `{key: value}` pairs into `scope='platform'` via
`platform_config.set` — no schema, no key allow-list, and **no `secret=True` path**.
Because `app_platform/secrets.py::decrypt` treats a value without the `enc:1:` prefix as
plaintext and returns it unchanged, an admin (or anything holding an admin token) can
write `discord_token`, `brave_api_key`, `tier_smart_key`, … as **plaintext** through this
endpoint, and every reader (`settings.get(..., secret=True)`) will happily use it. The
credential then sits unencrypted in `public.app_config`, defeating the
credentials-encrypted-at-rest property entirely.

Compounding it: **nothing calls these two endpoints.** `grep -rn 'api/apps/settings'`
across the repo finds only `apps/settings/routes.py` and
`apps/settings/ui/SettingsApp.jsx`, and the UI only ever hits `/apps`, `/panels` and
`/account`. `GET /platform` and `PATCH /platform` are dead code carrying a live
encryption bypass. Expected: delete both, or route the write through
`platform_settings.set` with a secret-key allow-list.

### 3. `GET /api/users` exposes the whole roster to every member
`agent.py::list_users`

No admin gate. Returns, for every household member: login name, display name, full role
string, `has_password`, and `discord_id`. The Settings Members panel is the main consumer
(it also uses it to decide whether to render the admin controls). So any signed-in
member — a child's account included — can enumerate who the admins are, who has no
password set yet, and everyone's Discord id. Expected: admin-gate it, or reduce the
non-admin projection to name + display name. The route lives in `agent.py`, not in the
Settings app, but Settings is what surfaces it.

### 4. The Settings UI does not pre-gate the panels it knows are admin-only
`apps/settings/ui/SettingsApp.jsx::AppDetail`

`AppManagementPanel` does this correctly — it works out whether the viewer is an admin and
shows "Only admins can enable or disable apps" with the switches disabled. `AppDetail`
(which renders System, Integrations and every per-app page) does not: a non-admin gets
fully editable inputs and an enabled Save button, fills the form in, presses Save, and
only then receives `Admin access required`. Expected: the same up-front lock notice, since
the answer is already known.

---

## Dead settings presented as live

### 5. Five of the eleven System-panel fields are read by nothing
`apps/settings/routes.py::PLATFORM_PANELS["system"]`

| field | status |
|---|---|
| `lan_url` | **no reader anywhere** in `*.py`, `*.jsx`, `*.sql`, `*.yaml` |
| `public_url` | **no reader anywhere** |
| `max_session_turns` | seeded in `migrations/000_baseline.sql` (`'20'`) and read by nothing |
| `realtime_model` | **no reader**; the voice path uses `os.getenv("REALTIME_MODEL")` (`app_platform/voice/session.py:30`), not this setting |
| `embedding_model` | **no reader**; the live value is `tier_embedding_model` (`providers/tier_resolver.py`) |

A person can set the LAN URL, the public URL, the session-turn cap, the voice model and the
embedding model and nothing at all happens. `embedding_model` is the worst of these
because the field *also* carries `requires_restart: True` and a description promising a
re-embed, so it reads as the most consequential field on the page.

### 6. `smart_model` / `dumb_model` claim "takes effect immediately" but are superseded
`apps/settings/routes.py::PLATFORM_PANELS["system"]`, `config.py:124-125`

`config.SMART_MODEL` / `config.DUMB_MODEL` still resolve from these platform keys, but
`providers/tier_resolver.py`'s own docstring says it "replaces the import-time
`config.SMART_MODEL` / `config.DUMB_MODEL` bare strings", and the Models panel writes
`tier_smart_connector` / `tier_smart_model` instead. So the System panel's Smart/Fast text
boxes are at best a legacy path and at worst inert — and they are labelled "Takes effect
immediately — no restart needed", which is wrong twice over: `_platform_setting` resolves
**at import**, so even where the value is still read it would need a restart. Uncertain
whether `config.SMART_MODEL` has any remaining live consumer (the only hits are
`scripts/tool_policy_harness.py` and a docstring). Expected: remove the four model fields
from the System panel and leave Settings → Models as the single place models are chosen.

### 7. A live, `verified: true` spec and a passing bound test enshrine a dead field
`apps/settings/specs/model-config/no-restart-copy.yaml` (as found),
`apps/settings/tests/test_model_fields_no_restart.py`

`test_embedding_still_requires_restart` asserts
`embedding_model requires_restart == True` — "MUST keep … (vector-dim lock)". Per finding
5, `embedding_model` (the System-panel key) is read by nothing; the real lock is on
`tier_embedding_model` and is enforced in `agent.py::onboarding_save_models`. The test is
green, the spec was `verified: true`, and both describe a field with no effect. I rewrote
the spec around the observable behaviour (which model changes need a restart) and kept the
binding, but the test itself still asserts against the dead key.

### 8. The bound test names a spec id that is not in the corpus
`apps/settings/tests/test_model_fields_no_restart.py` docstring says
`platform.settings.model-config-no-restart-copy`. The record's actual id is
`settings.model-config.no-restart-copy`. Nothing enforces the docstring, but a reader
looking for that id finds nothing.

### 9. Debug switches default to on
`apps/settings/routes.py` (`show_entity_ids` default `True`, `debug_tokens` default `True`)
and `migrations/000_baseline.sql` (both seeded `true`). A fresh household install surfaces
internal entity ids in the interface and writes verbose token accounting to the logs by
default, though the panel describes both as debugging aids. Expected: `False` defaults,
with the operator opting in.

---

## Correctness

### 10. A multi-key save is not atomic — a failure leaves it half applied
`apps/settings/routes.py::api_patch_app_settings`, `::api_patch_panel`

Both iterate `req.values.items()` and write each key individually. If key three raises —
`SecretKeyMissing` (no encryption key), `LocationNotFound`, `GeocoderUnavailable`, a DB
error — keys one and two are already committed, the request returns 400/503, and the UI
shows "could not save" over a page that partly did. Re-pressing Save usually recovers
(the UI re-sends all still-differing keys), but the intermediate state is real and for
`default_location` it is guaranteed, since that is the branch that raises. Expected:
validate everything first, then write; or write inside one transaction.

### 11. A failed desktop-hide save is never reported and never reverted
`apps/settings/ui/SettingsApp.jsx::DesktopVisibilityPanel::toggle`

```js
setHidden(next);
setHiddenApps([...next]);   // launcher updated already
setSaving(true);
try { await fetch("/api/apps/hidden", {...}); } finally { setSaving(false); }
```

No `res.ok` check, no `catch`, no error state in the component. A rejected or failed POST
leaves the local state and the live launcher showing the new arrangement while the server
still holds the old one — so the change silently reverts on the next reload.
`AppManagementPanel::toggle` next door does check `j.ok` and surfaces `err`. Expected: the
same treatment.

### 12. A person can hide their own Settings tile and has no in-UI way back
`web/src/apps/registry.js::getTileApps` includes `settings` (it is `subview: false` and
never disabled, being in `REQUIRED_APPS`). So Settings → Desktop apps → "Settings: Hidden"
removes the only tile that leads to the screen that could un-hide it; the tile-level
right-click "hide" does the same. Recovery exists — `getOpenableApps()` deliberately
includes hidden tiles, so asking Skipper to open Settings still works — but it is not
discoverable. Expected: exclude `settings` from the hide list, or refuse to hide the last
route to it.

### 13. The Apps and Desktop panels can only see apps that ship a UI
`web/src/apps/registry.js` builds `APP_MANIFESTS` from
`import.meta.glob("../../../apps/*/ui/index.js")`, so `getManageableApps()` and
`getTileApps()` list only apps with a `ui/index.js`. A backend-only app (tools, handlers,
jobs, no UI) can be installed and loaded but **cannot be turned off from Settings** — it is
simply not on the Apps screen. Conversely `/api/apps/required` returns the full
`REQUIRED_APPS` tuple, so any id in it without a UI never renders. Expected: drive the Apps
screen from the backend's loaded-app list, which `GET /api/apps/settings/apps` already
returns.

### 14. The location field can go blank while a location is configured
`apps/settings/routes.py::_default_location_label` returns `""` on any exception and when
`configured` is false. Combined with "blank means keep" in `api_patch_panel`, an install
whose stored record fails `_validate_record` (or whose legacy `default_zip` has not
migrated) shows an empty Location box, gives the person no signal that a location *is* set,
and cannot be corrected by leaving the box empty. Uncertain how reachable this is — it
needs a malformed or legacy record.

### 15. There is no way to unset the home location
Same handler: `if not q: continue`. Once a location is stored the only operation is
"replace it", never "clear it". I specced the keep-on-blank behaviour (it is deliberate and
protects against accidental wipes), but the absence of any clear path deserves a decision.

### 16. `GET /apps/{app_id}` will happily describe the Settings app itself
`_loaded_apps_sorted()` filters `m.id != "settings"` so the list endpoint excludes it, but
`api_get_app_settings` does not and returns Settings with `schema: []`,
`has_settings: false`. Harmless, but the two endpoints disagree about whether Settings is a
configurable app.

---

## Skipper's side of the hand-off

### 17. Skipper can open Settings but cannot land anyone on the panel it just named
`apps/settings/ui/index.js`, `apps/settings/ui/SettingsApp.jsx`

`apps/goals/onboarding.py::ONBOARDING_AGENDA` requires Skipper to give exact paths —
"Settings → System → Location", "Settings → Integrations", "Settings → Members → My
Discord" — precisely because it has no tool that can apply them. But:

- `ui/index.js` declares **no `tabs: [...]` array**, so `build_open_app_tool()` renders
  Settings with no tab list and `open_app(app_type="settings", tab=…)` has nothing valid to
  pass;
- `SettingsApp` accepts only `{ userId }` — it ignores `context` and `tab` entirely and
  hard-codes `useState("__desktop__")`.

So `open_app("settings")` always lands on **Desktop apps**, and a person told to go to
"Settings → System → Location" arrives at the app-tile visibility screen and has to find
the panel themselves. Expected:
`tabs: ["desktop","members","apps","models","system","integrations"]` in `ui/index.js`, and
`SettingsApp` seeding `selected` from `context.tab`. This is the single change that would
most improve the onboarding hand-off.

### 18. `help.md` is stale in three places
`apps/settings/help.md`

- Claims Integrations holds a **Weather** credential ("e.g. a Weather or Discord token").
  There is no weather key in `PLATFORM_PANELS["integrations"]`, and the weather app uses a
  keyless service (`apps/weather/data.py`).
- Does not mention the **Models** panel or the **Apps** (enable/disable) panel, both of
  which are in the sidebar.
- Does not mention "Where will you chat with Skipper?" (the per-person primary surface),
  which is one of the few genuinely per-person things on the page.

`/api/apps/{app_id}/help` serves this file to Skipper as well as to the person, so the
stale Weather line is a hallucination source.

---

## Documentation that describes code that does not exist

### 19. `app_platform/config.py` and `apps/settings/specs/SPEC.md` both claim the loader seeds defaults
> "Manifest-declared defaults populate `app_config` on first load; the loader inserts
> default rows for every key in an app's `config:` array that doesn't already have a stored
> value."

`app_platform/loader.py` does no such thing — the only config reference in it is the
`disabled_apps` read. The behaviour is real but achieved differently, at read time, by
`apps/settings/routes.py::_current_values` falling back to `ck.default`. Harmless, but it
documents a mechanism that was never built.

### 20. `ConfigKeyDef`'s docstring contradicts the actual secret handling
`app_platform/manifest.py:90-93`:

> "Apps may declare `secret: true` … The value is still stored / returned in plaintext by
> the config layer — masking is presentation only."

Not true for anything routed through Settings: `api_patch_app_settings` calls
`platform_settings.set(..., secret=True)` (AES-GCM encrypt) and `_current_values` blanks
the value on read. The docstring reads as a licence to treat these as cosmetic, which would
be a security regression if believed.

### 21. `apps/settings/specs/SPEC.md` predates most of the app
It documents only `/apps` and `/platform` — no mention of `/panels`, `/account`, the System
or Integrations panels, Members, Models, or the Apps/Desktop screens, i.e. most of what the
app now is. It also presents `PATCH /platform` as the supported way to change platform
settings, which is the dead endpoint from finding 2.

---

## Corpus problems in the specs I inherited

### 22. `specs/model-config/` had no `_feature.yaml` — the corpus did not load
`settings.model-config.no-restart-copy` existed with no `settings.model-config` feature
record, which is a hard **error** under the §4 loader rules (`engine/schema.py::validate` →
"parent not found"). Anything validating this corpus was failing. Fixed by adding the
feature file.

### 23. Five of the six inherited specs were tautologies and were deleted
- `config.list-app-settings` — "Listing discovers every installed app's config schema…"
- `config.edit-app-settings` — "Editing reads and writes an app's config values…"
- `config.platform-settings` — "Platform settings read and write the platform-scope configuration."
- `panels.manage-panels` — "Panel settings read and update the configuration of app panels."
- `account.manage-account` — "Account settings read and update the signed-in user's own account details."

None names a trigger except in the sense that "the feature exists"; none survives test 0.
The `panels` feature was also mis-named — it was about the desktop-tile and app-enable
screens, not about the System and Integrations panels the code calls "panels".

### 24. The inherited `no-restart-copy` spec was a build log
Its `behavior` named `requires_restart:False`, `POST /api/onboarding/save-models`,
`restart_required` and "post-#73"; its `implements` entries were prose ("`ModelsPanel:`
remove the post-save restart banner; plain 'Saved'") rather than `path::symbol`; its `notes`
were 400+ characters of work journal including a `.gitignore` warning. Rewritten; the test
binding and `verified: true` were kept.
