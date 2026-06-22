#!/usr/bin/env node
/**
 * Raw-token lint — the design-system completeness gate (issue #38).
 *
 * Apps must use the SEMANTIC token/class layer (surface, text, border, btn, pill, tab,
 * list-row, etc. defined once for both themes) instead of raw Tailwind scales, so light/dark
 * is correct by ONE definition and the same element looks identical across every app.
 *
 * This scans web/src AND every apps/<name>/ui for raw color usage and reports each offender
 * with a suggested semantic replacement. Deny-list is derived EMPIRICALLY from what the apps
 * actually use (slate/gray/zinc dominate; cyan/teal are the ad-hoc accents) and covers the
 * opacity-suffixed (bg-slate-900/30) and arbitrary-value (bg-[#…]) forms, plus the raw
 * text-white/bg-white "renders-black-on-accent" trap.
 *
 *   node scripts/check-no-raw-tokens.mjs            # scan everything
 *   node scripts/check-no-raw-tokens.mjs web/src    # scan one root
 *
 * Exit 0 = zero offenders in the scanned scope; 1 = offenders found (file:line + suggestion).
 * During migration the close-gate requires zero across web/src AND every app ui directory.
 */
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");

// Raw color patterns that are NOT allowed in app/shell UI.
const RAW = [
  // neutral scales (incl. opacity suffix): bg-slate-900, text-gray-400, border-zinc-700/50
  /\b(bg|text|border|ring|divide|from|to|via)-(slate|gray|zinc|neutral|stone)-\d{2,3}(\/\d{1,3})?\b/,
  // ad-hoc accents used instead of the one curated accent
  /\b(bg|text|border|ring|from|to|via)-(cyan|teal|sky)-\d{2,3}(\/\d{1,3})?\b/,
  // arbitrary hex color values: bg-[#1e293b], text-[#fff]
  /\b(bg|text|border|ring)-\[#[0-9a-fA-F]{3,8}\]/,
  // raw white/black on color (the text-white-renders-black trap) — use a btn-*/content token
  /\b(bg|text)-(white|black)\b/,
];
const SUGGEST = (cls) => {
  if (/^text-(slate|gray|zinc|neutral|stone)-(5|6|7)\d\d?/.test(cls)) return "text-muted / text-faint";
  if (/^text-(slate|gray|zinc|neutral|stone)-(2|3)\d\d?/.test(cls)) return "text-primary";
  if (/^bg-(slate|gray|zinc|neutral|stone)-(8|9)\d\d?/.test(cls)) return "surface-card / surface-panel / surface-page";
  if (/^bg-(slate|gray|zinc|neutral|stone)-(6|7)\d\d?/.test(cls)) return "surface-raised";
  if (/^border-/.test(cls)) return "border-subtle / border-strong";
  if (/(cyan|teal|sky)/.test(cls)) return "the curated accent token";
  if (/-(white|black)\b/.test(cls)) return "a content token / btn-* (foreground baked in)";
  if (/\[#/.test(cls)) return "a semantic token (add one if missing — never a raw hex)";
  return "a semantic class";
};

const TOKEN = /[\w-]+(\/\d{1,3})?|[\w-]+-\[#[0-9a-fA-F]{3,8}\]/g;

function uiRoots(argv) {
  if (argv.length) return argv.map((a) => join(ROOT, a));
  const roots = [join(ROOT, "web", "src")];
  const appsDir = join(ROOT, "apps");
  if (existsSync(appsDir)) {
    for (const a of readdirSync(appsDir)) {
      const ui = join(appsDir, a, "ui");
      if (existsSync(ui)) roots.push(ui);
    }
  }
  return roots;
}

const offenders = [];
function scan(dir) {
  if (!existsSync(dir)) return;
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    // EXEMPT: game canvases (e.g. apps/arcade/ui/games/*) use intentional, game-specific
    // palettes (card suits, boards, sprites) that are NOT part of the neutral light/dark
    // design system — migrating them to semantic neutrals would break the games (issue #38).
    if (st.isDirectory() && entry === "games") continue;
    if (st.isDirectory()) { scan(p); continue; }
    if (!/\.(jsx?|tsx?)$/.test(entry)) continue;
    readFileSync(p, "utf8").split("\n").forEach((line, i) => {
      for (const tok of (line.match(TOKEN) || [])) {
        if (RAW.some((re) => re.test(tok))) {
          offenders.push({ at: `${relative(ROOT, p)}:${i + 1}`, cls: tok, fix: SUGGEST(tok) });
          break; // one report per line is enough to locate it
        }
      }
    });
  }
}

uiRoots(process.argv.slice(2)).forEach(scan);

if (offenders.length) {
  console.error(`[check-no-raw-tokens] FAIL — ${offenders.length} raw color use(s) (issue #38):`);
  for (const o of offenders.slice(0, 200)) console.error(`  ${o.at}: ${o.cls}  ->  ${o.fix}`);
  if (offenders.length > 200) console.error(`  … and ${offenders.length - 200} more`);
  process.exit(1);
}
console.log("[check-no-raw-tokens] OK — zero raw color tokens in the scanned UI.");
