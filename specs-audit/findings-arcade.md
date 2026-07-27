# Findings — arcade

Survey only; nothing fixed. Corpus 4 → 59 records. Items marked **VERIFIED** were confirmed by the PM.

**On raw-HTML rendering:** arcade is clean. No `dangerouslySetInnerHTML`, `innerHTML` or `document.write`
anywhere; the only externally-influenced strings rendered are `player` and `game` from the score board,
both JSX text nodes. Nothing in arcade renders model output.

## 1. VERIFIED — three games swallow keystrokes for the whole page, including the chat box

`web/src/components/AppPanel.jsx:196` keeps every open app **mounted** with `display: none`, and on
desktop the chat panel is visible beside the app panel at all times. All three action games register key
handlers on `window` with **no target check and no phase check** — confirmed by count: Aeldrift 2 window
listeners / 0 target checks / 2 `preventDefault`; Wardenfall 1 / 0 / 4; Spinhazard 2 / 0 / 4.

- `Wardenfall.jsx:621::onKey` + `:642` — `preventDefault()` on `"1"`, `"2"`, `" "` and `"enter"`. While
  Arcade is open on Wardenfall, **nobody on the page can type a space, type 1 or 2, or press Enter to
  send a chat message.** Enter also calls `startNextWaveNow()`.
- `Spinhazard.jsx:181,210` — `preventDefault()` on `Space` and the arrow keys, unconditionally.
- `Aeldrift.jsx:283–302` — `gameKeys` includes `w`, `a`, `s`, `d`, so **those four letters cannot be typed
  anywhere on the page** while Aeldrift is open.

Handlers are removed only on unmount, and switching app tabs does not unmount. Expected: bind to the
focused container only (Spinhazard and Aeldrift already do this *as well* — the `window` fallback is what
breaks it), or skip when `ev.target` is an input/textarea/contenteditable and when `phase !== "playing"`.

## 2. `save_score` never reaches memory — the call signature is wrong

`data.py:67::save_score` calls `digest_record(app_id=…, entity_type=…, entity_id=…, summary=…, by=…)`.
`app_platform/memory.py:130::digest_record` takes `(app_id, entity_type, action, entity_id, record, by='',
context_hint='', blocking=False)` — there is **no `summary` parameter**, and `action` and `record` are
required. Every call raises `TypeError`, swallowed by the bare `except Exception: pass` at `data.py:70`.
So no arcade score has ever been digested, and `help.md` ("Your high scores … are pulled into Skipper's
memory, so you can ask 'what's the top score on Spinhazard?'") is false. The in-progress Solitaire game it
also claims is in memory is never digested at all.

## 3. `BACKFILL_ENTITIES` has no consumer anywhere in the repo

`data.py:31` declares it; across the whole tree the only other occurrence outside `apps/*/data.py` is the
scaffold template `scripts/new_app.py:229`. Nothing reads it at runtime. With §2 this means arcade records
reach memory by **no** path. **Cross-cutting — 20 apps declare it**, and other audit files (e.g.
`findings-schedules.md` §16) refer to "the periodic `BACKFILL_ENTITIES` sweep" as though it existed. Its
`list_fn` also asks for `limit=1000` while `top_scores` clamps to 100, so it would be wrong even if it ran.

## 4. The shared board makes two of the four games unrankable

Score ranges are incommensurable and the board is one list sorted on raw score (`data.py:87`,
`ArcadeApp.jsx:87`, `limit=10`):

| game | realistic range |
|---|---|
| Spinhazard | thousands |
| Wardenfall | hundreds–thousands (`wave*100 + kills*5`, endless) |
| Solitaire | 100–1197 (`max(100, 1200 - moves*3)`) |
| **Aeldrift** | **0–16** (shard count) |

An Aeldrift run can never appear on a top-10 any Spinhazard run has touched. The API and chat tool both
support `?game=`, but the **UI offers no per-game filter**, so an Aeldrift score is visible nowhere.
`help.md` compounds it by claiming the board covers "the action games" only and that Solitaire merely
"saves your game" — Solitaire *does* post on a win.

## 5. Aeldrift's seven islands are buried below the ground plane — never visible

`Aeldrift.jsx:144–159`: mound sphere radius `r`, then `position.y = -r * 0.55` and `scale.y = 0.5`.
World-space top = `-0.55r + 0.5r = -0.05r`, i.e. **always below `y = 0`**, and the ground
`CircleGeometry` at `y = 0` is opaque. All 7 mounds are invisible, while the blurb promises "a low-poly
archipelago" and the start screen says "drift across the isles".

## 6. No authorization on any arcade route, and `player` comes from the client

`routes.py` — 5 endpoints, **zero** calls to `scope_user` / `resolve_target` / `current_principal`.
- `api_save_score:41` takes `player` from the request body verbatim, so any caller can post any score
  under any member's name (`CROSS-CUTTING.md` §2).
- `api_get_solitaire_save:51`, `api_put_solitaire_save:57`, `api_delete_solitaire_save:65` take `player`
  as a query/body field keyed on the member's **canonical name** — trivially guessable — so any member,
  including a `kid` account, can read, overwrite or **silently destroy** another member's in-progress
  game. This is destructive rather than merely readable, so it is not obviously covered by the
  adults-trust-each-other decision. `DELETE` returns `{"ok": true}` regardless.

## 7. A poisoned score is permanent — no delete path anywhere

`save_score` applies `max(0, int(score))` with **no upper bound**, and there is no `DELETE /scores`, no
reset tool and no admin path. One crafted POST of `2147483647` permanently occupies the top of the
household's board with no remedy short of SQL. `player` is likewise unbounded in length.

## 8. "New game" in Solitaire can silently fail to take effect

`Solitaire.jsx:130::newGame` deals a fresh hand but does **not** call `clearSave`; the replacement relies
on the 600 ms debounced PUT at `:115`. The effect's cleanup (`:122`) cancels the pending timer on unmount,
so leaving Solitaire within ~600 ms of a new deal leaves the **old** hand stored — the person returns to
the hand they thought they had abandoned. The same window loses the last move or two of any session.

## 9. Aeldrift rebuilds its entire three.js world after every completed run

`ArcadeApp.jsx:149` passes a fresh inline arrow as `onGameOver`. Submitting a score bumps `refreshKey`,
re-rendering `ArcadeApp` → new `onGameOver` → new `fireGameOver` → the scene-setup effect's dep
`[fireGameOver]` (`Aeldrift.jsx:453`) changes → the whole scene, geometry, materials and WebGL context are
torn down and rebuilt with a newly randomised world, behind the still-showing "cleared" overlay.
Wardenfall avoids this with `onGameOverRef`; only Aeldrift is affected.

## 10. Games keep running at full speed while hidden, and can end unattended

Because unfocused app tabs stay mounted (§1), the `requestAnimationFrame` loops keep firing (the tab is
visible, so no browser throttling). Wardenfall keeps spawning waves, loses lives, and will **fire
`onGameOver` and record a score while the person is in another app.** Aeldrift keeps rendering a hidden
WebGL canvas via `setAnimationLoop`. Whether an unattended loss should be recorded is a product decision.

## 11–12. Already-recorded cross-cutting instances

`manifest.yaml:16` declares `id_format: "hs-{hex8}"`, so `hs-` entity links never validate
(`CROSS-CUTTING.md` §4c). And `routes.py:43` and `:59` return `{"ok": false, "error": …}` with a **200**
(§4d) — both callers ignore the body, so a rejected score is indistinguishable from an accepted one.

## 13. Smaller

- `tools.py:12–14` — the tool docstring lists only wardenfall/aeldrift/spinhazard; **Solitaire is
  missing**, so the model will not offer a Solitaire board. No validation of `game` against
  `VALID_GAMES` either: an unknown game returns "No arcade scores recorded yet — go play a game!", which
  is wrong rather than merely unhelpful.
- `ArcadeApp.jsx:4` header comment says "three original games"; there are four. `:166` uses
  `md:grid-cols-3` for four cards, giving a 3+1 layout.
- `migrations/001_initial.sql:7` — the `game` column comment omits Solitaire.
- `Solitaire.jsx:18` imports `Undo2` and never uses it; there is no undo, so the import implies a feature
  that does not exist.
- `Solitaire.jsx:246::clickWaste` — with a tableau card selected, clicking the waste calls
  `tryMove({zone:"waste"})`, which `tryMove` does not handle, so it falls through to `return prev` and
  silently clears the selection. The pick-up is lost with no feedback.
- `Wardenfall.jsx:165::computeScore` — comment says "waves **fully survived** × 100", but `spawnWave`
  increments `s.wave` at the *start* of a wave, so giving up on wave 1 with zero kills scores 100.
- `Wardenfall.jsx:402–416::applyDamage` — a single-target projectile damages the **nearest enemy to the
  impact point** within 22px, not the enemy it was fired at. With bunched enemies an Archer regularly
  hits the wrong one.
- `Wardenfall.jsx:697` — `const hudAccumRef = useRef(0)` is declared *after* the effect that closes over
  it. Works only because the closure runs post-render; fragile.
- `Aeldrift.jsx` — `keysRef.current` is never cleared on a phase change, so a key held when "Finish run"
  is clicked stays latched into the next run. `handleFinish` with nothing gathered records a permanent
  **0** on the household board (see §7).
- `ArcadeApp.jsx:130` — `refreshKey` is bumped even when the POST threw, so a failed submission is
  invisible: the board silently refetches without the run.
- `high_scores.player` and `solitaire_saves.player` are soft references to `public.users.name` with no FK,
  so renaming a member orphans their scores and saved hand; `solitaire_saves` has no cleanup for departed
  members.
- `ui/sfx.js:19` — the mute preference lives in `localStorage`, so it is per-browser rather than
  per-member: it does not follow a person to their phone, and two people sharing a browser share it.
- `apps/tools/tests/test_tool_guide.py:73,141` uses `apps/arcade/guide.md` as a deliberate
  *non-existent* fixture and asserts it stays absent — so creating an arcade `guide.md` would break an
  unrelated app's test.
- `manifest.yaml:23–24` — `emits: []` / `subscribes: []`, so arcade is clean on `CROSS-CUTTING.md` §6.
