#!/usr/bin/env node
/**
 * Skipper UI audit — log in, open every launcher app AND every tab within it,
 * screenshot each, and flag pages that render empty / broken when they should
 * show data.
 *
 *   node audit.mjs --base http://evolve-test.local:8000 --user david --pass david1234
 *
 * Output (under --out, default ./_audit):
 *   - report.json / report.md   findings (status per app/tab)
 *   - <app>.png                 default view
 *   - <app>__<tab>.png          one screenshot per tab (so a human/Claude can SEE it)
 *
 * The Skipper web UI is a React SPA: apps open via React state (NOT url routes) and
 * tabs are per-app state toggles, so curl sees only an empty shell. This drives a
 * real headless browser — login, click each launcher tile across all 3 pages, then
 * click each known tab. Doubles as the Evolve box-2 `validate` harness (EVOLVE.md §5).
 */
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { argv } from "node:process";

const arg = (n, d) => { const i = argv.indexOf("--" + n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const BASE = arg("base", "http://evolve-test.local:8000").replace(/\/$/, "");
const USER = arg("user", "david");
const PASS = arg("pass", "david1234");
const OUT = arg("out", "./_audit");
const ONLY = (arg("only", "") || "").split(",").map((s) => s.trim()).filter(Boolean);
const SETTLE_MS = Number(arg("settle", "1700"));
const TILE = 'button[title="Right-click to hide from your desktop"]'; // launcher app tiles
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// Per-app tab labels (extracted from apps/*/ui/*.jsx tab arrays). Keyed by app slug.
// Apps not listed are single-view (default screenshot only).
const TABS = {
  auto: ["Service History", "Maintenance", "Issues", "Condition", "Value"],
  bounties: ["Board", "Leaderboard", "My Balance", "Templates", "Settings"],
  chores: ["Today", "Week", "Manage"],
  home: ["Maintenance", "Appliances", "Contractors", "Insurance", "Issues"],
  meals: ["Browse", "Meal Log", "Discover", "Components", "Manage"],
  medical: ["Medications", "Appointments", "Events", "Treatments", "Labs", "Equipment"],
  reminders: ["Reminders", "Nags"],
  weather: ["Current", "Forecast", "Radar"],
  thinking: ["Mind", "Domains", "Log"],
  automation: ["Dashboard", "Names"],
  jobs: ["Config", "Logs"],
};

const EMPTY_RE =
  /\bno [a-z0-9 .'’-]*?(yet|found|assigned|scheduled)\b|nothing (here|to|yet)|no (results|items|data|records|entries)|get started|add your first|create your first|is empty|haven['’]t (added|created)/i;

async function login() {
  const post = (body) =>
    fetch(`${BASE}/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
  await post({ username: USER }).catch(() => {});
  const res = await post({ username: USER, password: PASS });
  if (!res?.ok || !res?.token) throw new Error("login failed: " + JSON.stringify(res));
  return { token: res.token, user: res.user }; // SPA needs BOTH token + user in localStorage
}

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

  const goHome = async () => { await page.goto(BASE, { waitUntil: "domcontentloaded" }); await page.waitForSelector(TILE, { timeout: 20000 }); };
  const gotoPage = async (idx) => {
    if (idx === 0) return;
    await page.evaluate((i) => { [...document.querySelectorAll("button[title]")].find((b) => b.title.startsWith(`Page ${i + 1}`))?.click(); }, idx);
    await page.waitForTimeout(400);
  };
  const clickByText = (txt) => page.evaluate((t) => {
    const b = [...document.querySelectorAll("button")].find((x) => x.innerText.trim() === t);
    if (b) { b.click(); return true; } return false;
  }, txt);

  // Discover tiles across all 3 launcher pages.
  await goHome();
  const tiles = [];
  for (let p = 0; p < 3; p++) {
    await gotoPage(p);
    for (const n of await page.$$eval(TILE, (els) => els.map((b) => b.querySelector("span")?.textContent?.trim()).filter(Boolean))) tiles.push({ name: n, page: p });
  }
  const seen = new Set();
  let work = tiles.filter((t) => (seen.has(t.name) ? false : seen.add(t.name)));
  if (ONLY.length) work = work.filter((t) => ONLY.includes(slug(t.name)));
  console.log(`[audit] ${work.length} apps discovered`);

  const findings = [];
  const capture = async (id, tab, errors, badApi) => {
    await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
    await page.waitForTimeout(SETTLE_MS);
    const text = (await page.evaluate(() => document.body?.innerText || "")).trim();
    const fname = tab ? `${id}__${slug(tab)}` : id;
    await page.screenshot({ path: `${OUT}/${fname}.png`, fullPage: true }).catch(() => {});
    const empty = EMPTY_RE.test(text), blank = text.replace(/\s+/g, " ").length < 40;
    const status = errors.length || badApi.length ? "ERROR" : empty || blank ? "EMPTY" : "OK";
    findings.push({
      id, tab: tab || "(default)", status, chars: text.length,
      empty_match: empty ? (text.match(EMPTY_RE) || [])[0] : null,
      bad_api: badApi.slice(0, 5), errors: errors.slice(0, 5), sample: text.replace(/\s+/g, " ").slice(0, 200),
    });
    console.log(`  ${status.padEnd(5)} ${id}${tab ? " / " + tab : ""}`);
  };

  for (const { name, page: p } of work) {
    const id = slug(name);
    const tabs = TABS[id] || [null];
    for (const tab of tabs) {
      const errors = [], badApi = [];
      const onC = (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); };
      const onP = (e) => errors.push("pageerror: " + String(e).slice(0, 160));
      const onR = (r) => { const u = r.url(); if (u.includes("/api/") && r.status() >= 400) badApi.push(`${r.status()} ${u.replace(BASE, "")}`); };
      page.on("console", onC); page.on("pageerror", onP); page.on("response", onR);
      try {
        await goHome();
        await gotoPage(p);
        const opened = await page.evaluate(({ tileSel, n }) => {
          const b = [...document.querySelectorAll(tileSel)].find((x) => x.querySelector("span")?.textContent?.trim() === n);
          if (b) { b.click(); return true; } return false;
        }, { tileSel: TILE, n: name });
        if (!opened) throw new Error("tile not found");
        await page.waitForTimeout(800);
        if (tab && !(await clickByText(tab))) errors.push(`tab '${tab}' not found`);
        await capture(id, tab, errors, badApi);
      } catch (e) {
        errors.push("open: " + String(e).slice(0, 160));
        await capture(id, tab, errors, badApi);
      }
      page.off("console", onC); page.off("pageerror", onP); page.off("response", onR);
    }
  }
  await browser.close();

  const order = { ERROR: 0, EMPTY: 1, OK: 2 };
  findings.sort((a, b) => order[a.status] - order[b.status] || a.id.localeCompare(b.id));
  await writeFile(`${OUT}/report.json`, JSON.stringify({ base: BASE, user: USER, findings }, null, 2));
  await writeFile(`${OUT}/report.md`,
    [`# UI audit — ${BASE} (as ${USER})`, "", `| status | app | tab | chars | detail |`, `|---|---|---|---|---|`,
      ...findings.map((f) => `| ${f.status} | ${f.id} | ${f.tab} | ${f.chars} | ${(f.bad_api[0] || f.errors[0] || f.empty_match || (f.status === "OK" ? "" : f.sample)).slice(0, 70)} |`),
    ].join("\n"));
  const n = (s) => findings.filter((f) => f.status === s).length;
  console.log(`\n[audit] ${findings.length} views — ERROR=${n("ERROR")} EMPTY=${n("EMPTY")} OK=${n("OK")}  ->  ${OUT}/report.md`);
}

main().catch((e) => { console.error(e); process.exit(1); });
