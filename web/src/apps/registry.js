// =============================================================================
// App registry — central manifest for all desktop apps.
// =============================================================================
// Required apps ship inside the platform repo at apps/<id>/ui/index.js.
// Optional apps are cloned into apps/<id>/ by the operator. Both are
// discovered by the same import.meta.glob block below — there are no
// hardcoded registry entries anymore.
//
// Each apps/<id>/ui/index.js exports a default array of:
//   { id, name, icon, component, singleton, page? }
// where `component` is `lazy(() => import("./<App>"))`. The build picks
// up the glob match at compile time so code-splitting works per-app.

const APP_MANIFESTS = {};

/**
 * App registry — central manifest for all desktop apps.
 *
 * Each entry defines:
 *   id         – unique string key
 *   name       – display name for tabs/UI
 *   icon       – Lucide icon component
 *   component  – lazy-loaded React component
 *   singleton  – if true, only one instance can be open at a time
 *
 * Apps receive these standard props:
 *   appId      – the runtime instance ID (may differ from registry id for multi-instance)
 *   userId     – current user's canonical name
 *   context    – optional context object passed when opening (e.g. { docId, goalId })
 *   onTitle    – callback(newTitle) to update the tab label
 */


// ---------------------------------------------------------------------------
// Packaged-app discovery
// ---------------------------------------------------------------------------
// Each packaged app under /apps/<id>/ui/index.js exports a default array of
// registry entries. Vite resolves this glob at build time (static analysis),
// so every match is bundled with code-splitting intact.
//
// Adding a new packaged app's UI = drop apps/<id>/ui/{index.js, *.jsx} in.
// Removing one = delete the folder. No edits to this file required.
//
// Discovered entries are auto-tagged with `appPackage: true` so the launcher
// styles them as packaged apps without each manifest having to remember.
const _packagedAppModules = import.meta.glob("../../../apps/*/ui/index.js", { eager: true });
for (const mod of Object.values(_packagedAppModules)) {
  const entries = mod.default || [];
  for (const entry of entries) {
    if (APP_MANIFESTS[entry.id]) {
      console.warn(`[registry] Packaged app entry '${entry.id}' collides with a core entry — packaged wins.`);
    }
    APP_MANIFESTS[entry.id] = { ...entry, appPackage: true };
  }
}

/** Get a manifest by app type ID. */
export function getAppManifest(appType) {
  return APP_MANIFESTS[appType] || null;
}

// A "sub-view" (registration flag `subview: true`) is a detail/viewer app-type
// that opens contextually — a chart, a document, a recipe detail, the anime
// player, a folder view — and never gets a launcher tile. It's not a togglable
// app, so it's excluded from every launcher + management list below.

// Runtime set of app ids the operator has DISABLED (platform level). Populated
// from GET /api/apps/disabled at startup via setDisabledApps(). A disabled app
// is fully off: its backend doesn't load (see app_platform/loader.py) and it's
// removed from the launcher here. (Distinct from a user HIDING a tile.)
let _disabledApps = new Set();
export function setDisabledApps(ids) { _disabledApps = new Set(ids || []); }
export function getDisabledApps() { return [..._disabledApps]; }
export function isAppDisabled(id) { return _disabledApps.has(id); }

// Per-user HIDDEN tiles (each user curates their own desktop). This is an
// OPT-OUT list: an app NOT in the set is shown — so a newly installed app is
// visible by default (it's in nobody's hidden list). Loaded from
// GET /api/apps/hidden. Hiding affects only this user's launcher and never
// unloads the app (that's "disabled", which is platform-wide).
let _hiddenApps = new Set();
const _visibilityListeners = new Set();
export function setHiddenApps(ids) {
  _hiddenApps = new Set(ids || []);
  _visibilityListeners.forEach((fn) => fn());   // re-render the launcher live
}
export function getHiddenApps() { return [..._hiddenApps]; }
export function isAppHidden(id) { return _hiddenApps.has(id); }
/** Subscribe to launcher-visibility changes (hide/show). Returns an unsubscribe fn. */
export function subscribeAppVisibility(fn) {
  _visibilityListeners.add(fn);
  return () => _visibilityListeners.delete(fn);
}

function _launcherVisible(a) {
  return !a.subview && !_disabledApps.has(a.id) && !_hiddenApps.has(a.id);
}

/** Get all registered app manifests for the launcher UI. Excludes sub-views. */
export function getAllApps() {
  return Object.values(APP_MANIFESTS).filter(_launcherVisible).sort((a, b) => a.name.localeCompare(b.name));
}

/** Apps for the management UI — every real (non-sub-view) app, including disabled
 *  ones so they can be re-enabled. */
export function getManageableApps() {
  return Object.values(APP_MANIFESTS)
    .filter(a => !a.subview)
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Real tile apps that are currently loaded (non-sub-view, not disabled) — the
 *  source for the per-user "My desktop" show/hide picker. Includes apps the
 *  user has hidden, so they can un-hide them. */
export function getTileApps() {
  return Object.values(APP_MANIFESTS)
    .filter(a => !a.subview && !_disabledApps.has(a.id))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** App-types the LLM may open via `open_app`. Built dynamically from every
 *  installed + ENABLED app — and intentionally INCLUDES sub-views and
 *  per-user-hidden tiles (visible only means "shows on the desktop"; open_app can
 *  still open them). Reported to the backend so the open_app tool's app list is
 *  never hardcoded. Each app may declare a `tabs: [...]` array in its ui/index.js. */
export function getOpenableApps() {
  return Object.values(APP_MANIFESTS)
    .filter(a => !_disabledApps.has(a.id))
    .map(a => ({ id: a.id, name: a.name, subview: !!a.subview, tabs: a.tabs || [] }));
}

/** Get launcher apps for a specific page (1, 2, or 3). Page 1 = everyday, page 2 = tools, page 3 = system. */
export function getAppsForPage(page) {
  return Object.values(APP_MANIFESTS)
    .filter(a => _launcherVisible(a) && (a.page === page || (page === 1 && !a.page)))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Generate a unique instance ID for an app. */
let _instanceCounter = 0;
export function newInstanceId(appType) {
  return `${appType}-${++_instanceCounter}-${Date.now()}`;
}
