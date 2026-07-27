# Findings — system

Survey only; nothing fixed. Corpus 3 → 48 records — was the thinnest in the repo.

## Security / access

**1. `routes.py::api_system_metrics` has no authorization at all.** The route takes no `Request` and calls
no `scope_user`/`resolve_target`/`has_role`; only `agent.py::auth_gate` applies, which requires *any*
principal. Exposed to a `kid` login:
- `platform.platform()` (255) — host OS, kernel version and libc, e.g.
  `Linux-6.1.0-rpi7-rpi-v8-aarch64-with-glibc2.36`. Version-fingerprinting detail with no household use.
- `python` version and `pid` (256-257).
- `latest_investment.status` and `.posture` (UI 357-368) — **the household's financial posture** from the
  external trading service, on a screen with no role gate.
- DB size, every record count, the last job's *name*, backup outcomes.

No paths, credentials or environment variables are exposed — checked; the only env read is server-side.
Expected: the runtime/OS/PID card and the investment line gated on `admin`/`parent`, as `apps/chores` does
with `_require_parent`. This is the residual `kid` gap (`CROSS-CUTTING.md` §1), not an adult-trust case.

**2. VERIFIED — `agent.py::api_admin_status` (4425) is not admin-gated despite living under `/api/admin/`.**
Its two siblings are: `api_admin_restart` (4490) and `api_admin_deploy` (4522) both call
`_is_admin_req` and return 403. `api_admin_status` does not, so any signed-in member gets `build_id`,
`uptime_seconds`, `shutting_down`, `active_dispatches`, `active_jobs` and `env`. Low severity, but the path
prefix implies a gate that is not there, and `env` reveals whether this is a dev instance. The System UI
calls it for every viewer.

**3. The System app renders the Restart button to everyone; the console header renders the identical
button only to admins.** `web/src/components/Shell.jsx:38,256` computes
`isAdmin = hasRole(userRole, "admin")` and wraps its power button in it.
`apps/system/ui/SystemApp.jsx:157-163` has no equivalent — it is not even passed a role (props are
`{ appId, userId, isActive }`), and `web/src/apps/registry.js` does not filter launcher tiles by role. So a
child's desktop shows the System tile and a live-looking Restart button. **The server refuses the request
(§2 confirms restart *is* gated), so the agent is safe — the UI is not honest.**

**4. `SystemApp.jsx::handleRestart` (102-108) ignores the response, so a refused restart displays as a
successful one.** It does `await fetch(...)` with no `res.ok` check and `catch {}`, having already set
`restarting = true`. A non-admin who presses Yes sees "Restarting..." with a spinner **forever**; the agent
never restarts and no error is ever shown. This is the closest analogue to the `apps/settings` dead-`PATCH`
problem — not a dead route, but a control whose failure is indistinguishable from success.

**5. `restarting` is never cleared and the System app never re-checks whether the agent came back.**
`Shell.jsx::handleRestart` (55-75) waits 3s then polls `/api/admin/status` every 2s and reloads on the
first success. `SystemApp.jsx` does neither. Two controls for one action with materially different
behaviour; the one inside the app is the worse of the two.

## Documentation that contradicts the code

**6. `help.md` advertises two chat workflows that cannot exist.** It states "*Through chat:* 'how's the
system doing?', 'how many records do we have?', 'when was the last backup?'" and "*Through chat:* 'restart
Skipper' (Skipper confirms, then restarts)". `manifest.yaml` sets `tool_category: ~`, the app ships no
`tools.py`, and a repo-wide grep finds **no restart tool anywhere**. The model has no way to read this
dashboard or restart the agent.

**7. `help.md` and `manifest.yaml` disagree about whether restart belongs to this app.** help.md documents
the restart control as a System screen; `manifest.yaml`'s description says the app owns "a single
read-only REST route"; `specs/SPEC.md` says "the admin endpoints … are platform-wide and stay in
`agent.py`" and does not mention the restart control at all. The old `_capability.yaml` went further and
said System is "NOT an admin control panel" — flatly contradicted by the UI. The capability is rewritten;
`SPEC.md` and the manifest description remain stale.

## Dead code and unread fields

**8. Five of the eighteen packaged counts are queried on every dashboard load and rendered nowhere.**
`_PACKAGED_COUNTS` (routes.py:56-75) includes `schedules`, `folders`, `behaviors`, `priority_focus` and
`timeline_posts`; none appear in `SystemApp.jsx`. Five `COUNT(*)` over full tables per page load, for
nothing. `counts["investment_snapshots"]` (186) and `doc_curation["cursor_id"]` (209) are likewise returned
and never rendered — the latter is an internal memory id, so dropping it is a small privacy win too.

**9. `from zoneinfo import ZoneInfo` (routes.py:19) is unused** — the timezone comes from
`app_platform.time.get_timezone`. And `SystemApp` destructures `{ appId, userId, isActive }` and uses none
of them.

## Correctness

**10. The "resilient — every section is wrapped in a try/except" claim in `api_system_metrics`'s docstring
(99-102) is false for the process snapshot.** Lines 235-244 catch `ImportError` only.
`psutil.Process(os.getpid())` can raise `NoSuchProcess`, and `memory_info()` can raise `AccessDenied` on a
hardened host or restricted container; either propagates out of `_fetch` and **500s the entire
dashboard** — the one failure mode the rest of the function is written to prevent. Expected:
`except Exception`.

**11. Two different uptimes are on screen simultaneously and can disagree.** The header shows
`agentStatus.uptime_seconds` = `int(time.time()) - int(BUILD_ID)` (agent.py:4432) — time since the *build
id* was minted. The Server Health card shows `sys.uptime_seconds` = now minus `psutil` process create time
(routes.py:239-242). After a plain restart on unchanged code the process clock resets while `BUILD_ID` may
not, so "up 3d 4h" can sit two inches above "Uptime 12m". Both are labelled identically.

**12. `_PACKAGED_COUNTS` is a hardcoded roster of 12 apps, but the manifest, help.md and capability all say
"every installed app".** The repo has 36. Twenty-one apps contribute nothing and cannot — adding an app
requires editing this file. **The dashboard silently under-reports the install with no indication that it
is doing so.** Expected: derive the roster from the app registry / `entity_types`, or state the limit on
screen.

**13. `_PACKAGED_COUNTS` and `_PLATFORM_COUNTS` are annotated `list[tuple[str, str]]` and the comment above
them says "(table_name, label, query) triples".** They are pairs of `(label, sql)`; the loop at 111 unpacks
two. The comment describes a shape that never existed.

## Integration / plumbing

**14. `VITE_TRADING_URL`/`VITE_TRADING_KEY` are read server-side here, which is correct** — while
`apps/backups/ui/BackupsApp.jsx:7-8` inlines the same credential into the public browser bundle (see
`findings-backups.md`). Worth noting from this side: because System proxies it properly, **the
browser-side copy in Backups is removable — the pattern to keep already exists in this file.**

**15. The remote `/api/metrics` payload is trusted wholesale.** `latest_investment` is handed to the UI,
which renders `.status` through `StatusBadge` and `.posture` as text (JSX-escaped, so no injection), and
`inv["snapshot_count"]` goes straight into the counts dict with no type check — a string would render
as-is in a numeric card. The `urlopen` carries `# noqa: S310`, i.e. a static analyser was silenced —
unlike `apps/timeline`'s SSRF the URL here is operator-supplied via env rather than caller-supplied, so
this suppression is defensible.

**16. `manifest.yaml` declares `platform_deps: [db]` but the route also imports
`app_platform.time::get_timezone`** — an undeclared platform dependency.

**17. No caching and no concurrency: one dashboard load issues ~28 sequential queries** (26 counts +
consciousness + DB size + latest job + latest backup + two curation queries), plus a synchronous 5s-capped
HTTP call to an external host, all inside one `asyncio.to_thread`. `pg_database_size` and the
`memories`-position subquery are the expensive ones. On a Pi-class host with a large log this is the
slowest read-only screen in the platform, and Refresh re-runs all of it — for an app whose whole purpose is
to load quickly.

**18. Nothing overlaps `specs/platform/deploy/agent-memory-containment.yaml`** — this app only *reports*
the process's RSS; it enforces no limit and takes no action.
