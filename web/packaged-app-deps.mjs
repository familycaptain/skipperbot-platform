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
import { execSync } from "node:child_process";

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

/**
 * Return the ids of every app under apps/<id> that ships a ui/ directory,
 * sorted. Used to emit explicit Tailwind @source lines (see emitSources).
 */
export function collectPackagedAppUiDirs() {
  const ids = [];
  let appNames = [];
  try {
    appNames = fs
      .readdirSync(APPS_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
      .sort();
  } catch {
    return ids;
  }
  for (const app of appNames) {
    try {
      if (fs.statSync(path.join(APPS_DIR, app, "ui")).isDirectory()) ids.push(app);
    } catch {
      /* no ui/ dir — skip */
    }
  }
  return ids;
}

// ---------------------------------------------------------------------------
// Tailwind source emission
// ---------------------------------------------------------------------------
// Tailwind v4 skips gitignored paths when a glob @source matches them, so
// optional apps cloned into apps/ (gitignored) don't get scanned and their
// exclusive classes are dropped from the CSS. Tailwind DOES honor a glob-free,
// explicitly-named directory even if gitignored — so we generate one
// `@source "../../apps/<id>/ui"` line per installed app into a CSS file that
// src/index.css imports. Relative paths are resolved from the generated file's
// location (web/src/), so "../../apps/<id>/ui" === repo-root/apps/<id>/ui.

const SOURCES_CSS = path.join(WEB_DIR, "src", "packaged-app-sources.css");

function emitSources() {
  const ids = collectPackagedAppUiDirs();
  const lines = [
    "/* AUTO-GENERATED by packaged-app-deps.mjs --emit-sources. DO NOT EDIT.",
    " * One explicit Tailwind @source per app with a ui/ dir, so apps cloned",
    " * into apps/ (gitignored) still get their classes scanned. Regenerated by",
    " * the npm prebuild/predev hooks and at container start. */",
    ...ids.map((id) => `@source "../../apps/${id}/ui";`),
    "",
  ];
  fs.writeFileSync(SOURCES_CSS, lines.join("\n"));
  console.log(`[app-deps] wrote ${path.relative(WEB_DIR, SOURCES_CSS)} (${ids.length} app ui dir(s): ${ids.join(", ") || "none"})`);
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
  // Run npm through the shell (execSync), NOT execFileSync('npm'/'npm.cmd'):
  //   - bare `npm` on Windows -> ENOENT (npm is npm.cmd, not npm)
  //   - `npm.cmd` via execFileSync -> EINVAL on modern Node, which refuses to
  //     spawn .cmd/.bat files directly (the CVE-2024-27980 mitigation)
  // execSync uses a shell on every platform, so npm resolves normally. Quote
  // each spec so a version range like ^1.9.4 survives cmd.exe (where `^` is an
  // escape char) and the Unix shell alike.
  const quoted = specs.map((s) => `"${s}"`).join(" ");
  execSync(`npm install --no-save --no-audit --no-fund ${quoted}`, {
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
    runInstall();      // deps (entrypoint path)
    emitSources();     // and refresh the Tailwind @source list
  } else if (mode === "--emit-sources") {
    emitSources();     // Tailwind sources only (npm prebuild/predev path)
  } else {
    // Default: print what would be collected (handy for debugging).
    console.log(JSON.stringify(
      { ...collectPackagedAppDeps(), uiDirs: collectPackagedAppUiDirs() }, null, 2));
  }
}
