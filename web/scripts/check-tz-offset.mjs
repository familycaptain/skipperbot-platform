#!/usr/bin/env node
/**
 * Bound test for platform.onboarding.timezone-offset (issue #55).
 *
 * Exercises the pure tzOffset() helper (web/src/utils/tz.js) that the onboarding
 * timezone dropdown uses to label + sort its options. No JS unit runner exists
 * in this repo (vite + custom node check-*.mjs gates), so this is a plain-node
 * assert script: it prints PASS/FAIL and exits non-zero on any failure.
 *
 * Asserts: a zero-offset zone -> UTC+00:00/0; a DST zone stays in its seasonal
 * range; a HALF-HOUR zone's minutes SURVIVE normalization; every label is
 * `UTC±HH:MM` or '' (degrade); the (minutes,id) sort is monotonic; an INVALID
 * zone returns the degrade fallback and never throws.
 */
import { tzOffset } from "../src/utils/tz.js";

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log(`  PASS  ${name}`);
  } else {
    failures++;
    console.error(`  FAIL  ${name}`);
  }
}

// (a) Zero-offset zone: exact text + minutes.
{
  const r = tzOffset("Etc/UTC");
  check("Etc/UTC -> {text:'UTC+00:00', minutes:0}", r.text === "UTC+00:00" && r.minutes === 0);
}

// (b) DST-aware zone stays within its seasonal offset range.
{
  const r = tzOffset("America/New_York");
  check(
    "America/New_York text /^UTC-0[45]:00$/ and minutes in {-300,-240}",
    /^UTC-0[45]:00$/.test(r.text) && (r.minutes === -300 || r.minutes === -240),
  );
}

// (c) HALF-HOUR zone: minutes must survive normalization (Intl may emit 'GMT+5:30').
{
  const r = tzOffset("Asia/Kolkata");
  check("Asia/Kolkata -> {text:'UTC+05:30', minutes:330}", r.text === "UTC+05:30" && r.minutes === 330);
}

// (d) Every produced label matches the normalized shape OR is the empty degrade label.
{
  const zones = [
    "Etc/UTC", "America/New_York", "Asia/Kolkata", "Asia/Tokyo",
    "America/Los_Angeles", "Europe/London", "Australia/Sydney", "Not/AZone",
  ];
  const ok = zones.every((z) => {
    const t = tzOffset(z).text;
    return t === "" || /^UTC[+-]\d{2}:\d{2}$/.test(t);
  });
  check("every text is /^UTC[+-]\\d{2}:\\d{2}$/ or '' (fallback)", ok);
}

// (e) SORT invariant: (minutes,id) yields monotonic non-decreasing minutes.
{
  const fixture = ["Asia/Tokyo", "Etc/UTC", "America/Los_Angeles", "Asia/Kolkata", "America/New_York"];
  const sorted = fixture
    .map((id) => ({ id, off: tzOffset(id) }))
    .sort((a, b) => a.off.minutes - b.off.minutes || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  let monotonic = true;
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].off.minutes < sorted[i - 1].off.minutes) monotonic = false;
  }
  // Expected order: LA(-480) < NY(-300) < UTC(0) < Kolkata(330) < Tokyo(540).
  const order = sorted.map((x) => x.id).join(",");
  const expected = "America/Los_Angeles,America/New_York,Etc/UTC,Asia/Kolkata,Asia/Tokyo";
  check("fixture sorts monotonically by minutes", monotonic);
  check(`fixture order = ${expected}`, order === expected);
}

// (f) INVALID zone degrades: empty label, sentinel sort key, does NOT throw.
{
  let threw = false;
  let r;
  try {
    r = tzOffset("Not/AZone");
  } catch {
    threw = true;
  }
  check(
    "invalid zone -> {text:'', minutes:MAX_SAFE_INTEGER}, no throw",
    !threw && r && r.text === "" && r.minutes === Number.MAX_SAFE_INTEGER,
  );
}

if (failures) {
  console.error(`\n[check-tz-offset] FAIL — ${failures} assertion(s) failed.`);
  process.exit(1);
}
console.log("\n[check-tz-offset] OK — all tzOffset assertions passed.");
