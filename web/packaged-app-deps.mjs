// =============================================================================
// Packaged-app frontend dependency collector
// =============================================================================
// Packaged apps live at apps/<id>/ and may ship a UI under apps/<id>/ui/ that
// imports npm packages the base platform doesn't bundle. We do NOT want to
// hardcode every community app's dependency into web/package.json or the Vite
// alias list. Instead, each app declares its frontend deps in
//
//     apps/<id>/ui/package.json
//       { "dependencies": { ... },        // app-specific — installed + aliased
//         "peerDependencies": { ... } }   // platform-provided — never touched
//
// This module is the single source of truth read by BOTH:
//   - web/vite.config.js  — to generate resolver aliases dynamically, and
//   - deploy/entrypoint.sh — via `node packaged-app-deps.mjs --install`, to
//     install the union into web/node_modules at container start.
//
// So: `git clone <app> apps/<id>` + restart the container → the app's deps are
// picked up automatically. The platform never names a specific package.
// =============================================================================

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_DIR = __dirname;
const APPS_DIR = path.resolve(__dirname, "..", "apps");

// Parse the leading "x.y.z" out of a version range ("^3.7.0" -> [3,7,0]) for a
// best-effort "newest wins" comparison. Avoids pulling in a semver dependency.
function versionTuple(range) {
  const m = String(range).match(/(\d+)\.(\d+)\.(\d+)/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [0, 0, 0];
}

// Returns +1 if a is newer than b, -1 if older, 0 if equal.
function compareRanges(a, b) {
  const ta = versionTuple(a), tb = versionTuple(b);
  for (let i = 0; i < 3; i++) {
    if (ta[i] !== tb[i]) return ta[i] > tb[i] ? 1 : -1;
  }
  return 0;
}

/**
 * Scan apps/<id>/ui/package.json and union their `dependencies`.
 * On a version-range conflict the newer range wins (a warning is recorded).
 *
 * @returns {{ deps: Record<string,string>, conflicts: Array, sources: Record<string,string[]> }}
 */
export function collectPackagedAppDeps() {
  const deps = {};            // pkg -> chosen version range
  const sources = {};         // pkg -> [app ids that declared it]
  const conflicts = [];

  let appNames = [];
  try {
    appNames = fs
      .readdirSync(APPS_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
      .sort(); // deterministic order
  } catch {
    return { deps, conflicts, sources }; // no apps/ dir — nothing to do
  }

  for (const app of appNames) {
    const pkgPath = path.join(APPS_DIR, app, "ui", "package.json");
    let pkg;
    try {
      pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
    } catch {
      continue; // app has no ui/package.json (or it's unreadable) — skip
    }
    const appDeps = pkg.dependencies || {};
    for (const [name, range] of Object.entries(appDeps)) {
      (sources[name] ||= []).push(app);
      if (!(name in deps)) {
        deps[name] = range;
        continue;
      }
      if (deps[name] !== range) {
        const keepIncoming = compareRanges(range, deps[name]) > 0;
        conflicts.push({
          name,
          kept: keepIncoming ? range : deps[name],
          dropped: keepIncoming ? deps[name] : range,
          app,
        });
        if (keepIncoming) deps[name] = range;
      }
    }
  }

  return { deps, conflicts, sources };
}

// ---------------------------------------------------------------------------
// CLI: `node packaged-app-deps.mjs --install`
// Installs the collected union into web/node_modules with --no-save (so the
// platform's package.json / package-lock.json are never mutated by an app).
// A stamp skips the reinstall when the collected set is unchanged.
// ---------------------------------------------------------------------------

function runInstall() {
  const { deps, conflicts, sources } = collectPackagedAppDeps();

  for (const c of conflicts) {
    console.warn(
      `[app-deps] version conflict for ${c.name}: using ${c.kept}, ignoring ${c.dropped} (from app '${c.app}')`
    );
  }

  const specs = Object.entries(deps)
    .map(([name, range]) => `${name}@${range}`)
    .sort();

  if (specs.length === 0) {
    console.log("[app-deps] no packaged-app frontend dependencies declared");
    return;
  }

  console.log(
    `[app-deps] ${specs.length} packaged-app dep(s) from ${
      new Set(Object.values(sources).flat()).size
    } app(s):`
  );
  for (const [name, apps] of Object.entries(sources)) {
    console.log(`[app-deps]   ${name}@${deps[name]}  <- ${[...new Set(apps)].join(", ")}`);
  }

  // Skip the install when nothing changed since last run.
  const stampPath = path.join(WEB_DIR, "node_modules", ".skipper-app-deps-stamp");
  const sig = specs.join("\n");
  try {
    if (fs.readFileSync(stampPath, "utf8") === sig) {
      console.log("[app-deps] unchanged since last install — skipping");
      return;
    }
  } catch {
    /* no stamp yet — install */
  }

  console.log(`[app-deps] installing: ${specs.join(" ")}`);
  execFileSync("npm", ["install", "--no-save", "--no-audit", "--no-fund", ...specs], {
    cwd: WEB_DIR,
    stdio: "inherit",
  });

  try {
    fs.writeFileSync(stampPath, sig);
  } catch {
    /* node_modules not writable yet — non-fatal; we just reinstall next time */
  }
  console.log("[app-deps] install complete");
}

if (path.resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  const mode = process.argv[2];
  if (mode === "--install") {
    runInstall();
  } else {
    // Default: print the collected deps as JSON (handy for debugging).
    console.log(JSON.stringify(collectPackagedAppDeps(), null, 2));
  }
}
