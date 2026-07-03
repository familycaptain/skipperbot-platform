// UTC-offset helper for the onboarding timezone picker.
//
// Given an IANA zone id, compute its CURRENT (DST-aware) UTC offset via the
// built-in Intl API and normalize it to a signed `UTC±HH:MM` string plus a
// signed integer minute count usable as a sort key.
//
// Runtimes vary in what `timeZoneName: 'shortOffset'` emits — 'GMT+5:30',
// 'GMT-5', 'UTC+05:30', or a bare 'GMT'/'UTC' for a zero offset — so we parse
// all of those shapes, pad the hours to two digits, and PRESERVE minutes
// (e.g. Asia/Kolkata -> 'UTC+05:30', minutes 330).
//
// Intl usage is wrapped in try/catch (mirrors detectTimezone in
// pages/Onboarding.jsx): an un-formattable zone DEGRADES to an empty label and
// a sentinel sort key so it renders as the bare id and sorts LAST — never
// mislabeled as UTC+00:00.

export function tzOffset(zone) {
  try {
    const parts = Intl.DateTimeFormat(undefined, {
      timeZone: zone,
      timeZoneName: "shortOffset",
    }).formatToParts(new Date());
    const raw = parts.find((p) => p.type === "timeZoneName")?.value;
    if (!raw) return { text: "", minutes: Number.MAX_SAFE_INTEGER };

    // Strip the leading GMT/UTC token; what remains is the offset (or "").
    const rest = raw.replace(/^(?:GMT|UTC)/i, "").trim();
    if (rest === "") {
      // Bare 'GMT'/'UTC' means a zero offset.
      return { text: "UTC+00:00", minutes: 0 };
    }

    const m = /^([+-])(\d{1,2})(?::?(\d{2}))?$/.exec(rest);
    if (!m) return { text: "", minutes: Number.MAX_SAFE_INTEGER };

    const sign = m[1] === "-" ? -1 : 1;
    const hours = parseInt(m[2], 10);
    const mins = m[3] ? parseInt(m[3], 10) : 0;
    const minutes = sign * (hours * 60 + mins);
    const pad = (n) => String(n).padStart(2, "0");
    const text = `UTC${m[1]}${pad(hours)}:${pad(mins)}`;
    return { text, minutes };
  } catch {
    return { text: "", minutes: Number.MAX_SAFE_INTEGER };
  }
}
