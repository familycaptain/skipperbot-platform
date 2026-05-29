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

/** Get all registered app manifests (for launcher UI). Excludes utility apps. */
const LAUNCHER_HIDDEN = new Set(["chart", "document", "recipe", "image", "locator-item", "auto-vehicle", "brainstorm", "calendar-day", "folder", "anime-player"]);
export function getAllApps() {
  return Object.values(APP_MANIFESTS).filter(a => !LAUNCHER_HIDDEN.has(a.id)).sort((a, b) => a.name.localeCompare(b.name));
}

/** Get launcher apps for a specific page (1, 2, or 3). Page 1 = everyday, page 2 = tools, page 3 = system. */
export function getAppsForPage(page) {
  return Object.values(APP_MANIFESTS)
    .filter(a => !LAUNCHER_HIDDEN.has(a.id) && (a.page === page || (page === 1 && !a.page)))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Generate a unique instance ID for an app. */
let _instanceCounter = 0;
export function newInstanceId(appType) {
  return `${appType}-${++_instanceCounter}-${Date.now()}`;
}
