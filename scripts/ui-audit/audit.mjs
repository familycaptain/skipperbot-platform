#!/usr/bin/env node
/**
 * Skipper UI audit — log in, open every launcher app, screenshot it, and flag
 * pages that render empty / broken when they should show data.
 *
 *   node audit.mjs --base http://evolve-test.local:8000 --user admin --pass admin1234
 *
 * Output (under --out, default ./_audit):
 *   - report.json / report.md   findings (status per app)
 *   - <app>.png                 full-page screenshot per app (so a human/Claude can SEE it)
 *
 * The Skipper web UI is a React SPA: apps open via React state (NOT url routes), so
 * there's no #/<app> deep-link and curl sees only an empty shell. This drives a real
 * headless browser — it logs in, then clicks each launcher tile across all 3 pages.
 * Doubles as the Evolve box-2 `validate` harness (EVOLVE.md §5): proof a feature
 * actually RENDERS, not just that its unit tests pass.
 */
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { argv } from "node:process";

const arg = (n, d) => { const i = argv.indexOf("--" + n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const BASE = arg("base", "http://evolve-test.local:8000").replace(/\/$/, "");
const USER = arg("user", "admin");
const PASS = arg("pass", "admin1234");
const OUT = arg("out", "./_audit");
const ONLY = (arg("only", "") || "").split(",").map((s) => s.trim()).filter(Boolean);
const SETTLE_MS = Number(arg("settle", "1800"));
const TOKEN_KEY = "skipperbot_token"; // web/src/utils/api.js
const TILE = 'button[title="Right-click to hide from your desktop"]'; // launcher app tiles
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// Empty-state markers Skipper's React components render when there's no data.
const EMPTY_RE =
  /\bno [a-z0-9 .'’-]*?(yet|found|assigned|scheduled)\b|nothing (here|to|yet)|no (results|items|data|records|entries)|get started|add your first|create your first|is empty|haven['’]t (added|created)/i;

async function login() {
  const post = (body) =>
    fetch(`${BASE}/auth/login`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => r.json());
  await post({ username: USER }).catch(() => {});
  const res = await post({ username: USER, password: PASS });
  if (!res?.ok || !res?.token) throw new Error("login failed: " + JSON.stringify(res));
  return { token: res.token, user: res.user }; // SPA needs BOTH in localStorage to boot to desktop
}

const goHome = async (page) => {
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(TILE, { timeout: 20000 });
};
const gotoPage = async (page, idx) => {
  if (idx === 0) return;
  await page.evaluate((i) => {
    const dot = [...document.querySelectorAll("button[title]")].find((b) => b.title.startsWith(`Page ${i + 1}`));
    dot?.click();
  }, idx);
  await page.waitForTimeout(400);
};
const tileNames = (page) =>
  page.$$eval(TILE, (els) => els.map((b) => b.querySelector("span")?.textContent?.trim()).filter(Boolean));

async function main() {
  await mkdir(OUT, { recursive: true });
  console.log(`[audit] base=${BASE} user=${USER}`);
  const { token, user } = await login();
  console.log(`[audit] logged in as ${user?.name} (${user?.role})`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 1700 } });
  await ctx.addInitScript(([t, u]) => {
    try { localStorage.setItem("skipperbot_token", t); localStorage.setItem("skipperbot_user", u); } catch {}
  }, [token, JSON.stringify(user || {})]);
  const page = await ctx.newPage();

  // Discover tiles across all 3 launcher pages.
  await goHome(page);
  const tiles = [];
  for (let p = 0; p < 3; p++) {
    await gotoPage(page, p);
    for (const name of await tileNames(page)) tiles.push({ name, page: p });
  }
  const seen = new Set();
  let work = tiles.filter((t) => (seen.has(t.name) ? false : seen.add(t.name)));
  if (ONLY.length) work = work.filter((t) => ONLY.includes(slug(t.name)) || ONLY.includes(t.name));
  console.log(`[audit] ${work.length} app pages discovered across 3 launcher pages`);

  const findings = [];
  for (const { name, page: p } of work) {
    const errors = [], badApi = [];
    const onConsole = (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); };
    const onPageErr = (e) => errors.push("pageerror: " + String(e).slice(0, 200));
    const onResp = (r) => { const u = r.url(); if (u.includes("/api/") && r.status() >= 400) badApi.push(`${r.status()} ${u.replace(BASE, "")}`); };
    page.on("console", onConsole); page.on("pageerror", onPageErr); page.on("response", onResp);

    let text = "", id = slug(name);
    try {
      await goHome(page);
      await gotoPage(page, p);
      const opened = await page.evaluate(({ tileSel, n }) => {
        const b = [...document.querySelectorAll(tileSel)].find((x) => x.querySelector("span")?.textContent?.trim() === n);
        if (b) { b.click(); return true; }
        return false;
      }, { tileSel: TILE, n: name });
      if (!opened) throw new Error("tile not found");
      await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(SETTLE_MS);
      id = (await page.evaluate(() => document.querySelector("[data-appid]")?.getAttribute("data-appid"))) || id;
      text = (await page.evaluate(() => document.body?.innerText || "")).trim();
    } catch (e) {
      errors.push("open: " + String(e).slice(0, 200));
    }
    await page.screenshot({ path: `${OUT}/${id}.png`, fullPage: true }).catch(() => {});

    const empty = EMPTY_RE.test(text);
    const blank = text.replace(/\s+/g, " ").length < 40;
    const status = errors.length || badApi.length ? "ERROR" : empty || blank ? "EMPTY" : "OK";
    findings.push({
      id, name, status, chars: text.length, empty, blank,
      empty_match: empty ? (text.match(EMPTY_RE) || [])[0] : null,
      bad_api: badApi.slice(0, 6), errors: errors.slice(0, 6),
      sample: text.replace(/\s+/g, " ").slice(0, 200),
    });
    console.log(`  ${status.padEnd(5)} ${id}  (${name})`);
    page.off("console", onConsole); page.off("pageerror", onPageErr); page.off("response", onResp);
  }
  await browser.close();

  const order = { ERROR: 0, EMPTY: 1, OK: 2 };
  findings.sort((a, b) => order[a.status] - order[b.status] || a.id.localeCompare(b.id));
  await writeFile(`${OUT}/report.json`, JSON.stringify({ base: BASE, generated_for: USER, findings }, null, 2));
  await writeFile(
    `${OUT}/report.md`,
    [`# UI audit — ${BASE}`, "", `| status | app | id | chars | detail |`, `|---|---|---|---|---|`,
      ...findings.map((f) => `| ${f.status} | ${f.name} | ${f.id} | ${f.chars} | ${(f.bad_api[0] || f.errors[0] || f.empty_match || (f.status === "OK" ? "" : f.sample)).slice(0, 80)} |`),
    ].join("\n")
  );
  const n = (s) => findings.filter((f) => f.status === s).length;
  console.log(`\n[audit] ERROR=${n("ERROR")} EMPTY=${n("EMPTY")} OK=${n("OK")}  ->  ${OUT}/report.md`);
}

main().catch((e) => { console.error(e); process.exit(1); });
