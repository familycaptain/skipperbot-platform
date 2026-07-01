#!/usr/bin/env node
/**
 * Guardrail for the empty-state hero (spec platform.app-ui.empty-state-hero).
 *
 * Runs at web prebuild (and standalone). STATIC parse only — it reads files with
 * readFileSync + regex and NEVER import()s an app ui/index.js (those import
 * react/lucide, unresolvable from a bare Node script). The pure registry module
 * web/src/apps/emptyStateHero.js has no react/lucide imports, so it IS imported
 * directly to test the REAL predicate + registry.
 *
 * What it enforces:
 *  (1) isPristineEmpty truth table.
 *  (2) Enumerate PRIMARY (non-subview) entry ids across apps/*.ui/index.js.
 *      FAIL-CLOSED: error on any app index.js it cannot parse. A self-test
 *      asserts it recovers the KNOWN primary set (35 entries) and that the 7
 *      primary+subview files classify their subview correctly — so the id/subview
 *      regex can't silently mis-classify.
 *  (3) OPT_IN xor EXCLUDE over primary ids:
 *        - HARD FAIL if an entry is in BOTH (not disjoint).
 *        - Option B: an UNCLASSIFIED primary entry prints a loud WARNING telling
 *          the dev to classify it, is treated as default-exclude (no hero), and
 *          DOES NOT fail the build.
 *  (4) Per-hero blurb presence (DECLARE-UP-FRONT — every OPT_IN entry's data is
 *      authored in batch 1): each default/page OPT_IN entry has a non-empty
 *      `blurb`; each per-view OPT_IN entry has a `heroes` map with a non-empty
 *      blurb for EACH view it declares.
 *  (5) Every EXCLUDE entry has a non-empty reason.
 *
 * Per-app <PristineEmpty> integration (branch placement, per-view slice,
 * filterActive completeness, +New preserved, todo's no-todo-AND-no-backlog
 * condition) is proven by the VALIDATE screenshots, not by this static check.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const APPS_DIR = join(HERE, "..", "..", "apps");
const REGISTRY_MODULE = join(HERE, "..", "src", "apps", "emptyStateHero.js");

const errors = [];
const warnings = [];
const fail = (m) => errors.push(m);
const warn = (m) => warnings.push(m);

// ── The KNOWN ground truth (self-test) ──────────────────────────────────────
// 35 primary (non-subview) entry ids across every apps/*/ui/index.js.
const KNOWN_PRIMARY = [
  "arcade", "auto", "automation", "backups", "behaviors", "bounties",
  "brainstorming", "calculators", "chores", "documents", "email", "finder",
  "folders", "goals", "home", "images", "issues", "jobs", "lists", "locator",
  "meals", "medical", "notifications", "prioritize", "recipes", "reminders",
  "schedules", "settings", "system", "tasks", "thinking", "timeline", "todo",
  "tools", "weather",
].sort();
// The 7 files that ship BOTH a primary and a subview entry: file dir -> subview id.
const KNOWN_SUBVIEW = {
  auto: "auto-vehicle",
  brainstorming: "brainstorm",
  documents: "document",
  folders: "folder",
  images: "image",
  recipes: "recipe",
  locator: "locator-item",
};

// ── Static parse of an app ui/index.js ──────────────────────────────────────
// Returns { entries: [{ id, subview, blurb, heroes }] } or throws if unparseable.
const ID_RE = /\bid\s*:\s*(["'`])([\w-]+)\1/g;
const STR_RE = /^(["'`])((?:\\.|(?!\1).)*)\1/;

function extractString(text, afterKeyRe) {
  const m = text.match(afterKeyRe);
  if (!m) return undefined;
  const rest = text.slice(m.index + m[0].length).replace(/^\s*/, "");
  const s = rest.match(STR_RE);
  return s ? s[2] : undefined;
}

function extractHeroes(spanText) {
  // Find `heroes: {` then the block up to its closing `}`. Blurb strings never
  // contain braces, so the first `}` after the opening `{` closes the map.
  const open = spanText.search(/\bheroes\s*:\s*\{/);
  if (open === -1) return null;
  const braceStart = spanText.indexOf("{", open);
  const braceEnd = spanText.indexOf("}", braceStart);
  if (braceStart === -1 || braceEnd === -1) return null;
  const block = spanText.slice(braceStart + 1, braceEnd);
  const map = {};
  const pairRe = /([\w-]+)\s*:\s*(["'`])((?:\\.|(?!\2).)*)\2/g;
  let m;
  while ((m = pairRe.exec(block)) !== null) map[m[1]] = m[3];
  return map;
}

function parseIndexFile(text, appDir) {
  if (!/export\s+default\s*\[/.test(text)) return { entries: [] }; // not a manifest (e.g. empty timers)

  const ids = [];
  let m;
  ID_RE.lastIndex = 0;
  while ((m = ID_RE.exec(text)) !== null) ids.push({ id: m[2], index: m.index });
  if (ids.length === 0) {
    throw new Error(`${appDir}: has 'export default [' but no parseable entry id`);
  }

  const entries = [];
  for (let i = 0; i < ids.length; i++) {
    const start = ids[i].index;
    const end = i + 1 < ids.length ? ids[i + 1].index : text.length;
    const span = text.slice(start, end);
    entries.push({
      id: ids[i].id,
      subview: /\bsubview\s*:\s*true\b/.test(span),
      blurb: extractString(span, /\bblurb\s*:/),
      heroes: extractHeroes(span),
    });
  }
  return { entries };
}

// ── Walk apps/*/ui/index.js ─────────────────────────────────────────────────
const primaryById = new Map();  // id -> { appDir, blurb, heroes }
const subviewIds = new Set();

let appDirs = [];
try {
  appDirs = readdirSync(APPS_DIR).filter((d) => {
    try { return statSync(join(APPS_DIR, d)).isDirectory(); } catch { return false; }
  });
} catch (e) {
  fail(`Cannot read apps directory ${APPS_DIR}: ${e.message}`);
}

for (const appDir of appDirs) {
  const idxPath = join(APPS_DIR, appDir, "ui", "index.js");
  let text;
  try {
    text = readFileSync(idxPath, "utf8");
  } catch {
    continue; // no ui/index.js — not a UI app
  }
  let parsed;
  try {
    parsed = parseIndexFile(text, appDir);
  } catch (e) {
    fail(`UNPARSEABLE app manifest (fail-closed): ${e.message}`);
    continue;
  }
  for (const entry of parsed.entries) {
    if (entry.subview) {
      subviewIds.add(entry.id);
    } else {
      if (primaryById.has(entry.id)) {
        warn(`Duplicate primary entry id '${entry.id}' (in ${primaryById.get(entry.id).appDir} and ${appDir})`);
      }
      primaryById.set(entry.id, { appDir, blurb: entry.blurb, heroes: entry.heroes });
    }
  }
}

const primaryIds = [...primaryById.keys()].sort();

// ── (2) Self-test: recovered primary set must match the known ground truth ──
{
  const got = new Set(primaryIds);
  const want = new Set(KNOWN_PRIMARY);
  const missing = KNOWN_PRIMARY.filter((id) => !got.has(id));
  const extra = primaryIds.filter((id) => !want.has(id));
  if (missing.length) {
    fail(`Self-test: parser MISSED known primary entr${missing.length === 1 ? "y" : "ies"}: ${missing.join(", ")} (regex mis-classification — fail-closed)`);
  }
  if (extra.length) {
    // A genuinely new app is legitimate — but the self-test's job is to catch
    // silent regex drift, so surface it loudly. It is not, by itself, fatal:
    // the classification pass (3) handles new apps via Option B.
    warn(`Self-test: parser found primary entries not in the known set (new app? update KNOWN_PRIMARY): ${extra.join(", ")}`);
  }
  for (const [file, subId] of Object.entries(KNOWN_SUBVIEW)) {
    if (!subviewIds.has(subId)) {
      fail(`Self-test: expected subview '${subId}' (from apps/${file}) to be classified as a subview — not found (regex mis-classification)`);
    }
    if (got.has(subId)) {
      fail(`Self-test: subview '${subId}' was mis-classified as a PRIMARY entry`);
    }
  }
}

// ── Load the pure registry module (safe to import — no react/lucide) ─────────
let OPT_IN, EXCLUDE, isPristineEmpty;
try {
  ({ OPT_IN, EXCLUDE, isPristineEmpty } = await import(pathToFileURL(REGISTRY_MODULE).href));
} catch (e) {
  fail(`Cannot import registry module ${REGISTRY_MODULE}: ${e.message}`);
}

// ── (1) isPristineEmpty truth table ─────────────────────────────────────────
if (isPristineEmpty) {
  const cases = [
    { args: { records: [], loading: false, filterActive: false }, want: true, desc: "empty + not loading + no filter" },
    { args: { records: [{}], loading: false, filterActive: false }, want: false, desc: "has a record" },
    { args: { records: [], loading: true, filterActive: false }, want: false, desc: "still loading" },
    { args: { records: [], loading: false, filterActive: true }, want: false, desc: "filter active" },
    { args: { records: null, loading: false, filterActive: false }, want: true, desc: "records:null treated empty" },
  ];
  for (const c of cases) {
    const got = isPristineEmpty(c.args);
    if (got !== c.want) fail(`isPristineEmpty truth table: "${c.desc}" -> got ${got}, want ${c.want}`);
  }
}

// ── (3)+(4)+(5) Registry: disjoint, exhaustive (Option B), blurb + reason ────
if (OPT_IN && EXCLUDE) {
  // Disjointness + classification over every primary id.
  for (const id of primaryIds) {
    const inOpt = Object.prototype.hasOwnProperty.call(OPT_IN, id);
    const inExc = Object.prototype.hasOwnProperty.call(EXCLUDE, id);
    if (inOpt && inExc) {
      fail(`Primary entry '${id}' is in BOTH OPT_IN and EXCLUDE (not disjoint)`);
    } else if (!inOpt && !inExc) {
      // Option B — warn loudly, treat as default-exclude, DO NOT fail.
      warn(`UNCLASSIFIED primary entry '${id}' (app: ${primaryById.get(id)?.appDir}). ` +
        `Classify it in web/src/apps/emptyStateHero.js (OPT_IN with a placement + blurb, or EXCLUDE with a reason). ` +
        `Treating it as default-EXCLUDE (no hero) for now — build stays green.`);
    }
  }

  // Stale keys: registry entries that don't correspond to a real primary id.
  const primarySet = new Set(primaryIds);
  for (const id of Object.keys(OPT_IN)) {
    if (!primarySet.has(id)) warn(`OPT_IN key '${id}' is not a known primary entry id (stale?)`);
  }
  for (const id of Object.keys(EXCLUDE)) {
    if (!primarySet.has(id)) warn(`EXCLUDE key '${id}' is not a known primary entry id (stale?)`);
  }

  // (4) Per-hero blurb presence for every OPT_IN entry.
  for (const [id, placement] of Object.entries(OPT_IN)) {
    const rec = primaryById.get(id);
    if (!rec) continue; // stale key already warned above
    const mode = placement?.mode;
    if (mode === "per-view") {
      const views = Array.isArray(placement.views) ? placement.views : [];
      if (views.length === 0) {
        fail(`OPT_IN '${id}' is per-view but declares no views`);
      }
      const heroes = rec.heroes || {};
      for (const view of views) {
        const copy = heroes[view];
        if (!copy || !String(copy).trim()) {
          fail(`OPT_IN '${id}' (per-view) is missing a non-empty heroes["${view}"] blurb in apps/${rec.appDir}/ui/index.js`);
        }
      }
    } else if (mode === "default" || mode === "page") {
      if (!rec.blurb || !String(rec.blurb).trim()) {
        fail(`OPT_IN '${id}' (${mode}) is missing a non-empty \`blurb\` in apps/${rec.appDir}/ui/index.js`);
      }
    } else {
      fail(`OPT_IN '${id}' has an unknown placement mode: ${JSON.stringify(mode)}`);
    }
  }

  // (5) Every EXCLUDE has a non-empty reason.
  for (const [id, reason] of Object.entries(EXCLUDE)) {
    if (!reason || !String(reason).trim()) {
      fail(`EXCLUDE '${id}' has no reason`);
    }
  }
}

// ── Report ───────────────────────────────────────────────────────────────────
for (const w of warnings) console.warn(`[check-empty-state-hero] WARN — ${w}`);

if (errors.length) {
  console.error(`\n[check-empty-state-hero] FAIL — ${errors.length} error(s):`);
  for (const e of errors) console.error("  " + e);
  console.error("");
  process.exit(1);
}

console.log(
  `[check-empty-state-hero] OK — ${primaryIds.length} primary entries; ` +
  `${Object.keys(OPT_IN || {}).length} opt-in / ${Object.keys(EXCLUDE || {}).length} excluded; ` +
  `truth table + blurb/heroes coverage verified` +
  (warnings.length ? ` (${warnings.length} warning(s))` : "") + ".",
);
