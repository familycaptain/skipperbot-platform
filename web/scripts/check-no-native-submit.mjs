#!/usr/bin/env node
/**
 * Guardrail for issue #36 (no native form submit in the web SPA).
 *
 * A <button type="submit"> inside a React <form> can perform a native HTML form
 * submission (default GET -> full-page reload) before React's onSubmit
 * preventDefault is in control under load, wiping SPA state. The fix is to make
 * every primary action button type="button" + onClick. This guardrail fails the
 * build if any `type="submit"` reappears anywhere under web/src.
 *
 * Grep-decidable invariant only (zero type="submit"). The finer structural
 * properties (button-inside-a-form, onSubmit retained, preventDefault guarded)
 * are asserted per-file by the spec's static tests, not here.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(fileURLToPath(new URL(".", import.meta.url)), "..", "src");
const NEEDLE = /type\s*=\s*["']submit["']/;
const offenders = [];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      walk(p);
    } else if (/\.(jsx?|tsx?)$/.test(entry)) {
      const lines = readFileSync(p, "utf8").split("\n");
      lines.forEach((line, i) => {
        if (NEEDLE.test(line)) offenders.push(`${relative(SRC, p)}:${i + 1}: ${line.trim()}`);
      });
    }
  }
}

walk(SRC);

if (offenders.length) {
  console.error(
    `\n[check-no-native-submit] FAIL — ${offenders.length} native-submit button(s) found under web/src (issue #36):`,
  );
  for (const o of offenders) console.error("  " + o);
  console.error(
    "\nUse <button type=\"button\" onClick={handler}> and keep <form onSubmit> for the Enter key.\n",
  );
  process.exit(1);
}

console.log("[check-no-native-submit] OK — zero type=\"submit\" buttons under web/src.");
