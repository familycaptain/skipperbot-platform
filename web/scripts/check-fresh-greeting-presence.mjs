#!/usr/bin/env node
/**
 * Bound test for platform.onboarding.prompt-fresh-install-greeting (issue #79) — client side.
 *
 * On a genuinely fresh keyless install the desktop WS connects before models are
 * configured, so the arrival greeting is server-driven and can take longer than the
 * one-shot optimistic-typing window armed at load (OPTIMISTIC_GREETING_TIMEOUT_MS).
 * The fix makes presence SERVER-DRIVEN: the arrival-produce path emits a 'typing' frame
 * at produce-start, and the client keeps the dots lit for the whole produce by cancelling
 * the bounded optimistic fail-open when that server 'typing:true' frame arrives — no silent
 * dead-air gap. A dropped socket clears presence as a crash backstop.
 *
 * No JS unit runner exists in this repo (vite + custom node check-*.mjs gates), so this is a
 * plain-node source presence-guard; the LIVE fresh-install acceptance is the authoritative
 * behavior oracle. Assertions are deliberately LOOSE so innocuous refactors don't break build.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(fileURLToPath(new URL(".", import.meta.url)), "..", "src", "hooks", "useSkipperSocket.js");
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

// (a) The bounded optimistic fail-open BACKSTOP still exists (no infinite spinner).
check(
  "bounded optimistic fail-open constant still present (OPTIMISTIC_GREETING_TIMEOUT_MS)",
  /OPTIMISTIC_GREETING_TIMEOUT_MS/.test(src),
);

// (b) The optimistic timer is held in a ref so the ws effect can cancel it cross-effect.
check(
  "optimistic greet timer held in a ref (optimisticGreetTimer = useRef)",
  /optimisticGreetTimer\s*=\s*useRef/.test(src),
);

// (c) A server 'typing:true' frame cancels the optimistic fail-open so presence stays lit
//     through a produce longer than the load window.
check(
  "'typing' case cancels the optimistic timer on data.status (server-driven presence)",
  /data\.status\s*&&\s*optimisticGreetTimer\.current/.test(src) &&
    /clearTimeout\(\s*optimisticGreetTimer\.current\s*\)/.test(src),
);

// (d) A dropped socket clears presence (crash backstop after a typing:true frame).
const onclose = (src.match(/ws\.onclose\s*=\s*\(event\)\s*=>\s*\{[\s\S]{0,300}/) || [""])[0];
check(
  "ws.onclose clears presence (setIsTyping(false))",
  /setIsTyping\(\s*false\s*\)/.test(onclose),
);

if (failures) {
  console.error(`\ncheck-fresh-greeting-presence: ${failures} failure(s)`);
  process.exit(1);
}
console.log("\ncheck-fresh-greeting-presence: all checks passed");
