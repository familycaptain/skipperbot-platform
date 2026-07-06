#!/usr/bin/env node
/**
 * Guardrail for honest Backups "Run Now" status + the configure-first gate
 * (spec backups.runner.honest-unconfigured-run, issue #86).
 *
 * Runs at web prebuild (and standalone). STATIC parse only — readFileSync + regex.
 * Prevents a regression back to the old behavior where Run Now was always
 * enabled and a skipped run rendered the hardcoded "Backups were disabled":
 *   (1) BackupsApp.jsx gates on config.destination_configured (the Run Now button
 *       disable AND the empty state), and NO LONGER hardcodes "Backups were
 *       disabled" for a skipped run (it renders the real reason b.error).
 * A self-test asserts the parser finds the token it requires, so it can't pass
 * vacuously.
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const APP = join(ROOT, "apps", "backups", "ui", "BackupsApp.jsx");

let failed = false;
const fail = (m) => { console.error(`✗ check-backups-honest-status: ${m}`); failed = true; };

const src = readFileSync(APP, "utf8");

if (!/destination_configured/.test(src)) {
  fail("BackupsApp.jsx must gate on config.destination_configured (Run Now + empty state)");
}
if (/Backups were disabled/.test(src)) {
  fail('BackupsApp.jsx must NOT hardcode "Backups were disabled" for a skipped run — render the real reason (b.error)');
}
// The Run Now button must consider destination_configured in its disabled expr.
if (!/disabled=\{[^}]*destination_configured/.test(src)) {
  fail("the Run Now button's disabled expression must include destination_configured");
}

// Self-test: the parser is looking at the right file and the token exists.
if (!/onRunNow/.test(src)) {
  fail("self-test: BackupsApp.jsx did not contain the Run Now handler — wrong file?");
}

if (failed) process.exit(1);
console.log("✓ check-backups-honest-status: Run Now is gated on destination_configured; no hardcoded skip copy");
