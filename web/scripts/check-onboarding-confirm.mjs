#!/usr/bin/env node
/**
 * Bound test for platform.onboarding.admin-password-confirm (issue #56).
 *
 * The onboarding admin-creation step (web/src/pages/Onboarding.jsx
 * CreatePrimaryUser) must require a matching, double-entered password before it
 * will create the sole-admin account — a typo'd password would otherwise lock
 * everyone out (no self-service reset exists). This is a source presence-guard;
 * the e2e is the authoritative behavior oracle. No JS unit runner exists in this
 * repo (vite + custom node check-*.mjs gates), so this is a plain-node assert
 * script: it prints PASS/FAIL and exits non-zero on any failure.
 *
 * Assertions are deliberately LOOSE (presence-based) so innocuous re-styling of
 * the field doesn't break the build:
 *   (a) a `confirm` state exists;
 *   (b) a second type="password" input with name="confirm_password" exists;
 *   (c) the Create-account button's disabled= expression includes a
 *       confirm/match term (e.g. confirmOk);
 *   (d) the create-user fetch body still lists exactly username / display_name /
 *       password / timezone and does NOT include confirm (the "confirm never
 *       sent" invariant).
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

// (a) A `confirm` state var (useState) exists.
check(
  "confirm state exists (const [confirm, setConfirm] = useState)",
  /\[\s*confirm\s*,\s*setConfirm\s*\]\s*=\s*useState/.test(src),
);

// (b) A second type="password" input, named confirm_password.
{
  const pwInputs = src.match(/type\s*=\s*["']password["']/g) || [];
  check("at least two type=\"password\" inputs (Password + Confirm)", pwInputs.length >= 2);
  check(
    "a name=\"confirm_password\" input exists",
    /name\s*=\s*["']confirm_password["']/.test(src),
  );
}

// (c) The Create-account button's disabled= expression carries a confirm/match term.
{
  // Grab the disabled={...} expression on the Create-account button and confirm
  // it references the confirm/match gate (confirmOk, or a raw password===confirm
  // style term). Loose: any `confirm`/`match` token inside a disabled= expr.
  const disabledExprs = src.match(/disabled\s*=\s*\{[^}]*\}/g) || [];
  const gated = disabledExprs.some((e) => /confirm|match/i.test(e));
  check("Create-account button disabled= expr includes a confirm/match term", gated);
}

// (d) The create-user fetch body still lists exactly the four fields and no confirm.
{
  // Locate the create-user POST body object literal.
  const bodyMatch = src.match(/create-user[\s\S]*?body:\s*JSON\.stringify\(\s*\{([\s\S]*?)\}\s*\)/);
  check("create-user fetch body found", !!bodyMatch);
  if (bodyMatch) {
    const body = bodyMatch[1];
    check("create-user body includes username", /\busername\b/.test(body));
    check("create-user body includes display_name", /\bdisplay_name\b/.test(body));
    check("create-user body includes password", /\bpassword\b/.test(body));
    check("create-user body includes timezone", /\btimezone\b/.test(body));
    check(
      "create-user body does NOT include confirm (confirm never sent)",
      !/\bconfirm\b/.test(body),
    );
  }
}

if (failures) {
  console.error(`\n[check-onboarding-confirm] FAIL — ${failures} assertion(s) failed.`);
  process.exit(1);
}
console.log("\n[check-onboarding-confirm] OK — confirm-password guard present; confirm never sent.");
