#!/usr/bin/env node
/**
 * Guardrail for the configurable contractor-trades sub-feature
 * (spec home.contractors.managed-trades, issue #83).
 *
 * Runs at web prebuild (and standalone). STATIC parse only — reads files with
 * readFileSync + regex; never imports app UI (react/lucide unresolvable here).
 *
 * Enforces that the hardcoded contractor trade list was replaced by a
 * household-configurable table + picker, so a regression back to the old
 * free-text datalist fails the build:
 *   (1) apps/home/migrations/008_contractor_trades.sql creates
 *       home_contractor_trades and seeds ALL 15 required trades, idempotently
 *       (ON CONFLICT DO NOTHING).
 *   (2) apps/home/ui/HomeApp.jsx renders the contractor trade control as a
 *       <select> (both the Add form and the ContractorCard edit form) and NO
 *       LONGER uses the old <input list="contractor-trades"> datalist.
 *   (3) a TradesManager component exists and talks to
 *       /api/apps/home/contractors/trades.
 * A self-test asserts the parser actually finds the required trades in the
 * migration text, so it can't pass vacuously.
 */

import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const MIGRATION = join(ROOT, "apps", "home", "migrations", "008_contractor_trades.sql");
const HOMEAPP = join(ROOT, "apps", "home", "ui", "HomeApp.jsx");

const REQUIRED_TRADES = [
  "General", "Plumber", "Electrician", "HVAC", "Lawn", "Landscaping", "Roofer",
  "Gutters", "Painter", "Handyman", "Pest Control", "Appliance Repair",
  "Cleaning", "Flooring", "Garage Door",
];

let failed = false;
function fail(msg) { console.error(`✗ check-contractor-trades: ${msg}`); failed = true; }
function ok(msg) { console.log(`✓ check-contractor-trades: ${msg}`); }

function read(path, label) {
  try { return readFileSync(path, "utf8"); }
  catch (e) { fail(`cannot read ${label} (${path}): ${e.message}`); return null; }
}

// ── (1) migration: table + idempotent seed of all 15 trades ──────────────────
const sql = read(MIGRATION, "migration 008_contractor_trades.sql");
if (sql) {
  if (!/create\s+table\s+if\s+not\s+exists\s+home_contractor_trades/i.test(sql)) {
    fail("migration does not CREATE TABLE IF NOT EXISTS home_contractor_trades");
  }
  if (!/on\s+conflict\s*\(\s*id\s*\)\s*do\s+nothing/i.test(sql)) {
    fail("migration seed is not idempotent (missing ON CONFLICT (id) DO NOTHING)");
  }
  const missing = REQUIRED_TRADES.filter(t => !new RegExp(`'${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}'`).test(sql));
  if (missing.length) fail(`migration is missing required seed trade(s): ${missing.join(", ")}`);
  else ok(`migration seeds all ${REQUIRED_TRADES.length} required trades idempotently`);
}

// ── (2) HomeApp.jsx: <select> picker, no legacy datalist ─────────────────────
const jsx = read(HOMEAPP, "apps/home/ui/HomeApp.jsx");
if (jsx) {
  // The old free-text trade datalists must be gone.
  if (/list="contractor-trades"/.test(jsx) || /list="contractor-trades-edit"/.test(jsx)) {
    fail("legacy free-text trade <input list=\"contractor-trades\"> datalist still present — must be a <select>");
  }
  if (/<datalist\s+id="contractor-trades(-edit)?"/.test(jsx)) {
    fail("legacy <datalist id=\"contractor-trades\"> still present — must be removed");
  }
  // The trade options helper (drives both add + edit <select>) must exist.
  if (!/function\s+tradeOptions\s*\(/.test(jsx)) {
    fail("tradeOptions() helper (managed-trade <select> options) not found");
  }
  // Both forms should render a <select> whose options come from tradeOpts.
  const selectFromOpts = (jsx.match(/tradeOpts\.map\(/g) || []).length;
  if (selectFromOpts < 2) {
    fail(`expected the Add and Edit trade <select> to both map tradeOpts (found ${selectFromOpts}/2)`);
  } else {
    ok("Add + Edit trade controls are <select> populated from the managed list");
  }
  // (3) TradesManager wired to the CRUD API.
  if (!/function\s+TradesManager\s*\(/.test(jsx)) {
    fail("TradesManager component not found");
  }
  if (!/\/api\/apps\/home\/contractors\/trades/.test(jsx)) {
    fail("no reference to the /api/apps/home/contractors/trades API");
  } else {
    ok("TradesManager present and wired to /api/apps/home/contractors/trades");
  }
}

// ── self-test: the parser must actually be able to find a known trade ────────
if (sql && !/'General'/.test(sql)) {
  fail("self-test: parser failed to locate a known seed ('General') — aborting fail-closed");
}

if (failed) {
  console.error("check-contractor-trades: FAILED");
  process.exit(1);
}
console.log("check-contractor-trades: OK");
