#!/usr/bin/env node
/**
 * Bound test for platform.onboarding.theme-picker (issue #57).
 *
 * The onboarding admin-creation step (web/src/pages/Onboarding.jsx
 * CreatePrimaryUser) must offer a live Dark/Light theme picker that consumes the
 * shared theme API (useTheme/applyTheme from web/src/utils/theme.js) — a pure
 * consumer, no second persistence path — and must NOT add a `theme` field to the
 * create-user payload (persistence is client-only, per-browser localStorage).
 * This is a source presence-guard; the e2e is the authoritative behavior oracle.
 * No JS unit runner exists in this repo (vite + custom node check-*.mjs gates),
 * so this is a plain-node assert script: it prints PASS/FAIL and exits non-zero
 * on any failure.
 *
 * Assertions are deliberately LOOSE (presence-based) so innocuous re-styling of
 * the control doesn't break the build:
 *   (a) Onboarding.jsx imports/uses the shared theme API (useTheme or applyTheme);
 *   (b) it renders a Dark/Light theme control (a role="radiogroup"/role="radio"
 *       group, or the Dark/Light labels wired to setTheme);
 *   (c) the create-user fetch body still lists exactly username / display_name /
 *       password / timezone and does NOT include `theme`.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(fileURLToPath(new URL(".", import.meta.url)), "..", "src", "pages", "Onboarding.jsx");
const src = readFileSync(SRC, "utf8");

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log(`  PASS  ${name}`);
  } else {
    failures++;
    console.error(`  FAIL  ${name}`);
  }
}

// (a) Consumes the shared theme API (useTheme hook, or applyTheme directly).
check(
  "uses the shared theme API (useTheme or applyTheme)",
  /\buseTheme\s*\(/.test(src) || /\bapplyTheme\s*\(/.test(src),
);

// (b) Renders a Dark/Light theme control: either a radiogroup/radio group, or
//     Dark + Light options wired to setTheme.
{
  const hasRadiogroup = /role\s*=\s*["']radiogroup["']/.test(src) && /role\s*=\s*["']radio["']/.test(src);
  const hasDarkLight =
    /setTheme\s*\(\s*["']dark["']\s*\)/.test(src) &&
    /setTheme\s*\(\s*["']light["']\s*\)/.test(src);
  check("renders a Dark/Light theme control (radiogroup or Dark/Light setTheme calls)", hasRadiogroup || hasDarkLight);
}

// (c) The create-user fetch body still lists exactly the four fields and no theme.
{
  const bodyMatch = src.match(/create-user[\s\S]*?body:\s*JSON\.stringify\(\s*\{([\s\S]*?)\}\s*\)/);
  check("create-user fetch body found", !!bodyMatch);
  if (bodyMatch) {
    const body = bodyMatch[1];
    check("create-user body includes username", /\busername\b/.test(body));
    check("create-user body includes display_name", /\bdisplay_name\b/.test(body));
    check("create-user body includes password", /\bpassword\b/.test(body));
    check("create-user body includes timezone", /\btimezone\b/.test(body));
    check(
      "create-user body does NOT include theme (theme never sent)",
      !/\btheme\b/.test(body),
    );
  }
}

if (failures) {
  console.error(`\n[check-onboarding-theme] FAIL — ${failures} assertion(s) failed.`);
  process.exit(1);
}
console.log("\n[check-onboarding-theme] OK — Dark/Light theme picker present; theme never sent in create-user body.");
