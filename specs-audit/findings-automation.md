# Findings — automation

Survey only; nothing here is fixed. Everything below was read out of
`apps/automation/` (plus `docs/03-extended-functionality.md` and
`app_platform/capabilities.py`) at the time of the spec rewrite. Where I could not settle a
question without a live Home Assistant, I say so.

**Framing note for whoever assigned this audit:** the brief described this app as *user-defined
automations — triggers, conditions, actions, enable/disable state*. There is no such thing in the
code. `apps/automation/` is a **remote control for Home Assistant**: read an entity, change an
entity, and remember what the household calls its things. It holds no rules, has no trigger
evaluation, and nothing in it fires on its own except an hourly read-only refresh of the device
list (`hooks.py::_refresh_loop`). Standing rules live in the Behaviors app, scheduled work in the
Schedules app, and real trigger/condition/action automations in the household's own Home Assistant.
The specs are written against the code, not the brief.

---

## What bounds an action — very little

**1. The generic service call builds its request path by string interpolation, unescaped.**
`tools.py:733`:

```python
path = f"/api/services/{domain.strip().lower()}/{service.strip()}"
```

`domain` and `service` come from the model. Neither is quoted or validated against the service list
(`/api/services` is fetched by a *different* tool and never consulted here), so a `service` value
containing `../` or `?` addresses a **different Home Assistant endpoint** with the operator's
long-lived token attached — e.g. `service="../../config/core/update"` or
`service="turn_on?return_response"`. By contrast every entity id on the read path *is* escaped
(`urllib.parse.quote(value, safe='.')`, e.g. `tools.py:302`), so the omission looks accidental
rather than deliberate. Expected: reject a `domain`/`service` that is not a bare identifier, or
percent-encode both.

**2. Nothing in the app bounds *what* may be called.** `call_home_assistant_service` accepts any
domain and service with any JSON payload, and a Home Assistant long-lived access token is an
**admin** credential. That reaches `lock.unlock`, `alarm_control_panel.disarm`, `cover.open_cover`,
`script.*`, `shell_command.*`, `notify.*` (Skipper speaking or messaging through a path the platform
does not log), and Home Assistant's own host/OS services. This may well be intended — it is the
escape hatch that makes the app useful — but it should be a decision on the record, not an
accident of there being no check.

**3. The "confirm before doing anything risky" rule is prompt-only.** `guide.md` rule 12 and
`app_platform/voice/prompting.py::build_base_voice_instructions` ("For dangerous, expensive,
security-related, or irreversible actions, require explicit confirmation or refuse") are
*instructions to the model*. No code path anywhere in the app treats a lock, alarm, garage door or
camera differently from a lamp. The one real enforcement in the app is the dashboard's domain
allow-list (`routes.py:21 TOGGLEABLE`), which the chat/voice tools bypass entirely. I wrote
`automation.control.risky-actions-are-confirmed-first` as intent and flagged it in its notes;
whether it should be enforced in code is an operator call.

**4. No per-person restriction on control.** App routes are mounted under the platform's global
auth gate (`agent.py::auth_gate`) and use no `require_admin` and no role check, so any principal
with a valid bearer token — including a long-lived **service token** minted for the voice satellite
or a phone — can toggle every light and switch, edit every learned name, and (via chat tools) call
any Home Assistant service. Probably intended for a single-household install; worth stating
explicitly somewhere.

**5. No transport floor on the credential.** The stored URL may be `http://`, in which case the
admin token is sent in an `Authorization` header in cleartext on the LAN every request
(`tools.py::_ha_request`), and over `ws://` for the registry fetch (`devices.py::_ws_url`). Not
wrong for a home LAN; worth a warning next to the setting.

## Data loss

**6. A single odd registry response can wipe every hand-curated device name.**
`devices.py::_save_devices` ends with:

```python
if keep:
    cur.execute("DELETE FROM ha_devices WHERE device_id <> ALL(%s)", (keep,))
else:
    cur.execute("DELETE FROM ha_devices")
```

`keep` is built by `_build_device_aliases`, which drops any device that owns no *enabled, non-hidden*
entity (`_build_entities_by_device`). So a Home Assistant that answers `device_registry/list`
successfully but returns an entity registry in which nothing maps to a device (an integration
mid-reload, a permissions change, a schema change in a future HA release) yields `keep == []` and
**deletes the whole table** — every alias a person typed into the Names tab, and with it the voice
alias block (`build_voice_alias_block` returns "" for an empty table, silently). There is no
backup: the legacy `devices.json` import only runs while the table is empty *and* only once per
process (see 9). Even in normal operation, hiding a device's last entity in Home Assistant silently
deletes the names the household gave that device. Expected: never delete on an empty/degraded
fetch, and keep alias rows for devices that have gone away rather than dropping them.

**7. Entity-alias writes are whole-table rewrites, so concurrent writers lose each other's work.**
`tools.py::_save_aliases` does `DELETE FROM ha_aliases` then re-inserts the caller's entire dict;
every caller does load-modify-save (`add_home_assistant_alias`, `delete_home_assistant_alias`,
`_maybe_learn_alias`, `routes.py::api_edit_alias`). Two writes that overlap — and *alias learning
fires on ordinary voice traffic* (`_maybe_learn_alias`), so overlap is not exotic — end with
last-commit-wins over the whole table, silently reverting the other. Expected: single-row
INSERT/UPDATE/DELETE, which the table's primary key already supports.

**8. A transient DB read error can be laundered into a full alias wipe.** `_load_aliases`
(`tools.py:146-156`) catches *any* exception and returns `{}`. Its callers do not distinguish
"no aliases" from "could not read aliases", and then call `_save_aliases`, which deletes every row
before inserting. So one failed read followed by a successful write (`add_home_assistant_alias`, or
an automatic learn) leaves exactly one alias in a table that had fifty. Expected: a read failure
should abort the write, not be treated as an empty set.

**9. The legacy import gives up permanently on its first hiccup.**
`_import_legacy_aliases_once` / `_import_legacy_devices_once` set `_..._imported = True` *before*
doing any work (`tools.py:118`, `devices.py:244`). If the DB is not ready on the first call — very
plausible at boot — the import is skipped and never retried for the life of the process, so an
upgraded install can come up with an empty alias table while `aliases.json`/`devices.json` sit
right there. Flag on success, not on entry.

## Answers that are wrong rather than absent

**10. Controlling a name whose entity no longer exists reports success.** `_resolve_entity`
(`tools.py:307-321`) resolves a taught alias by fetching the entity; on *any* failure, including a
404 for a deleted entity, it returns `{"entity_id": entity_id}` — a fabricated stub — and never
falls through to the fuzzy search. Consequences:

- `turn_off_home_assistant_entity("garage heater")` for a removed entity POSTs the service and
  answers `Called Home Assistant service switch.turn_off.` with no changed states. A person reads
  that as done. (I could not confirm on a live HA whether `POST /api/services/...` with an unknown
  `entity_id` is a 200 with `[]` or an error in current HA versions — **unverified**, and it decides
  how bad this is.)
- `resolve_home_assistant_entity` prints `Resolved Home Assistant entity: … = unknown` for the
  missing thing, because the stub has no `state` key and `_entity_display` defaults it to
  "unknown" — presented as a resolution, not a failure.

Expected: a 404 on a taught name should be reported as "that name points at something that no
longer exists", and should not be dressed up as a resolved entity. I specced the *non*-self-healing
part as intent (`automation.names.a-name-whose-thing-is-gone`) because silently re-pointing a stale
name at a similar device is worse; the silent success is the finding.

**11. An unresolvable name produces a malformed service call.**
`turn_on_home_assistant_entity` (`tools.py:771-773`) does
`resolved = _resolve_entity_id(entity_id)` → `domain = _entity_domain(resolved)`. When nothing
matches, `_resolve_entity_id` returns the raw spoken text (`tools.py:333`), which has no `.`, so
`domain` is `""` and the request goes to `/api/services//turn_on`. The user-visible result is a raw
`Home Assistant API error 404` rather than "I don't know what you mean by that". Expected: detect
the unresolved case and say so.

**12. The battery scan reports non-batteries and voltage sensors as flat.**
`find_home_assistant_low_batteries` treats an entity as a battery if `device_class == "battery"`
**or** the string `battery` appears anywhere in its id or friendly name (`tools.py:854-858`), then
compares its numeric state against a percentage threshold *without ever looking at
`unit_of_measurement`*. So `sensor.battery_charger_power` at 12 W, or any battery **voltage** sensor
(3.0 V, 12.6 V), is reported as a battery at or below 25% — permanently, on every scan. Expected:
require `device_class == "battery"` or a `%` unit before comparing against a percentage.

**13. A failed device warm-up looks like a device with nothing in it.**
`warm_entities_cache_if_empty` swallows its exception (`devices.py:411-414`). `find_home_device`
then finds the device row in the DB (which persists) but `get_entities_for_device` returns `[]`, so
the answer is a device header, `entities (0):`, and the instruction "pick the entity_id that matches
the user's question" — with nothing to pick from and no hint that Home Assistant was unreachable.
Expected: distinguish "this device has no parts" from "I could not reach Home Assistant".

**14. `set_home_assistant_light` cannot turn a light off, and 0% is silently ignored.** It always
calls `light.turn_on`; `brightness_pct=0` means "leave brightness alone" (`tools.py:826`), so "set
the kitchen light to 0" turns the light **on** at its previous brightness. Meanwhile the dashboard
route clamps to `max(0, ...)` (`routes.py:115`) and *does* forward a 0, which Home Assistant reads
as off — two different meanings for the same number across the two surfaces. The UI slider starts
at 1, so only an API caller can hit it.

## Retry and re-fire behaviour

**15. Every failing device lookup re-attempts a full WebSocket registry fetch.** The in-memory map
stays empty when a warm-up fails, so `warm_entities_cache_if_empty` refires `fetch_and_save()` on
*every subsequent* `find_home_device` call — a fresh WS connect with a 10 s open timeout, plus a
full table rewrite when it succeeds. A person repeating a question at a voice speaker while Home
Assistant is down produces a connect attempt per utterance, each blocking that tool call for up to
ten seconds. No negative caching, no backoff. (The hourly loop, by contrast, is correctly patient.)

**16. A read-path tool call rewrites the device table.** `find_home_device`, a read, can trigger
`fetch_and_save()`, which upserts and DELETEs rows in `ha_devices` (see 6). The refresh thread can
be doing the same thing concurrently — two whole-table rewrites with no coordination beyond the
in-memory `_entities_lock`, which does not cover the DB write.

**17. The refresh thread runs on installs that have no Home Assistant.** `_refresh_loop` starts
unconditionally in `register_hooks` and never checks whether the app is configured, so an install
that never connected Home Assistant logs a warning every hour forever. The message it logs is also
stale: `_fetch_registries` raises `"HOME_ASSISTANT_URL is not set"` / `"HOME_ASSISTANT_TOKEN is not
set"` (`devices.py:88-90`), naming env vars that are no longer how this is configured (see 18).

## Documentation that contradicts the code

**18. The official setup instructions do not work.** `docs/03-extended-functionality.md:214-221`
tells the operator to put `HOME_ASSISTANT_URL` / `HOME_ASSISTANT_TOKEN` in `.env` and restart.
`tools.py::_ha_base_url` / `_ha_token` and `devices.py` read **only** the `app:automation` settings
scope — there is no env fallback — and `capabilities.py::is_enabled` ignores `env_vars` whenever
`settings_keys` is present, which it is for `home_assistant`. An operator who follows the docs gets
"Home Assistant is not configured" from every tool and OFF in the boot banner, with nothing pointing
at why. `apps/automation/guide.md` (lines 3-6) and the docstring of
`test_home_assistant_connection` ("Requires HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in .env")
repeat the same stale instruction — and that docstring is *shown to the model*, so Skipper will tell
a user to go and edit `.env`.

**19. `capabilities.py` still declares `env_vars=("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN")`**
for the `home_assistant` capability. Dead in practice (settings_keys wins), and misleading next to
18. Separately: **nothing in the codebase calls `is_enabled("home_assistant")`** — the capability
exists only for the boot banner and the tool-router hint; the app does its own
`_ha_setup_error()` check. Not a bug, but two sources of truth for "is this configured".

**20. Spec drift in the corpus I replaced.** The old `automation.diagnostics.test-connection` and
`automation.diagnostics.low-batteries` both listed `apps/automation/ui/AutomationApp.jsx` under
`implements`; the UI has no connection-test control and no battery surface at all. All 13 previous
specifications were tautologies of the tool docstrings ("Adding saves a human-friendly alias for a
Home Assistant entity"), and none of them described anything that has since been deleted, so
nothing was dropped as stale — they were rewritten.

## Small things

**21. `routes.py::api_delete_alias` always answers `{"ok": true}`**, including for an alias that
never existed; the message says otherwise but the UI only reads `ok` and removes the row regardless.

**22. Renaming an alias can silently overwrite a different one.** `api_edit_alias` pops the old key
and assigns the new one; if the new name is already taken by another alias, that other mapping is
replaced with no warning.

**23. Device aliases are shown un-normalized until reload.** `NamesManager.addDeviceAlias` puts the
raw typed text into local state while `set_device_aliases` stores the normalized form, so a person
who types "Kitchen Lamp!" sees that until the next refresh, then sees "kitchen lamp".

**24. The connection pill never updates without a page reload.** `DashboardView.load` re-fetches
`/entities` but not `/status`, so a household that fixes Home Assistant and presses Refresh still
reads "offline" beside the title.

**25. The Names tab is unreachable until Home Assistant is configured**, even though it reads only
Skipper's own DB (`AutomationApp` returns `SetupCard` on `!configured`). The code comment says this
is deliberate; noting it because it also means an operator cannot pre-load names before connecting.

**26. `/entities`, `/all-entities` and `/control` each fetch the *entire* `/api/states` document**,
and `/control` fetches it a second time to read back one entity. Opening the Names tab pulls the
whole state document just to populate an id picker. No caching, no rate limiting on the app's
routes. Fine for one household on a LAN; it is the app's hottest path.

**27. Dead imports.** `import os` is unused in both `tools.py` and `devices.py`.

**28. `include_unavailable` on `resolve_home_assistant_entity` is only honoured on the search
path.** A dotted id or a taught-name hit returns whatever Home Assistant says, unavailable or not
(the post-check saves it, but via the "state key missing → treated as available" path described in
10).

**29. The two legacy JSON files are present in the working tree** (`apps/automation/devices.json`,
`aliases.json`, both correctly `.gitignore`d, both untracked) and contain the operator's household
inventory. They are only read by the one-shot import. Nothing to fix; noted so a future reader does
not mistake them for fixtures, and so nobody encodes their contents as intent.
