// =============================================================================
// Weather — local forecast dashboard, three tabs
// =============================================================================
// Current | Forecast (12-hour hourly + 10-day daily) | Radar (~100-mi map) for
// any international location (defaults to the configured home location). One
// fetch to GET /api/apps/weather/summary. The agent can deep-link to a tab via
// open_app(app_type="weather", tab="radar") — see ui/index.js `tabs`.
// =============================================================================

import { useState, useEffect, useCallback, lazy, Suspense } from "react";
import { CloudSun, Loader2, Search, Wind, Droplets, Sun, RefreshCw, CalendarDays, Radar } from "lucide-react";

const API = "/api/apps/weather";
const WeatherMap = lazy(() => import("./WeatherMap"));

const TABS = [
  { id: "current", label: "Current", icon: CloudSun },
  { id: "forecast", label: "Forecast", icon: CalendarDays },
  { id: "radar", label: "Radar", icon: Radar },
];

// WMO weather code -> emoji.
const ICON = (code) => {
  const c = Number(code);
  if (c === 0) return "☀️";
  if (c === 1) return "🌤️";
  if (c === 2) return "⛅";
  if (c === 3) return "☁️";
  if (c === 45 || c === 48) return "🌫️";
  if (c >= 51 && c <= 57) return "🌦️";
  if ((c >= 61 && c <= 67) || (c >= 80 && c <= 82)) return "🌧️";
  if ((c >= 71 && c <= 77) || c === 85 || c === 86) return "🌨️";
  if (c >= 95) return "⛈️";
  return "🌡️";
};

const round = (v) => (v === null || v === undefined ? "–" : Math.round(v));
const hourLabel = (iso) => {
  const t = (iso || "").slice(11, 16);
  if (!t) return "";
  let h = parseInt(t.slice(0, 2), 10);
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h} ${ap}`;
};
const dayLabel = (iso, i) => {
  if (i === 0) return "Today";
  try {
    const [y, m, d] = (iso || "").split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short" });
  } catch {
    return iso;
  }
};
const uvLabel = (uv) => {
  if (uv === null || uv === undefined) return "";
  const v = Math.round(uv);
  const band = v <= 2 ? "Low" : v <= 5 ? "Moderate" : v <= 7 ? "High" : v <= 10 ? "Very high" : "Extreme";
  return `${v} ${band}`;
};

export default function WeatherApp({ context = {} }) {
  const validTab = (t) => TABS.some((x) => x.id === t);
  const [tab, setTab] = useState(validTab(context.tab) ? context.tab : "current");
  // React to deep-link re-opens (weather is a singleton — context updates in place).
  useEffect(() => { if (validTab(context.tab)) setTab(context.tab); }, [context.tab]);

  const [query, setQuery] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // load(q): geocode/resolve the place string `q` (blank = configured home).
  // load("", coords): refetch by KNOWN coordinates — no geocoding — used when
  // the user refreshes the place already shown (the box is unchanged).
  const load = useCallback(async (q, coords) => {
    setLoading(true);
    setErr("");
    try {
      const params = coords
        ? `lat=${encodeURIComponent(coords.lat)}&lon=${encodeURIComponent(coords.lon)}` +
          `&label=${encodeURIComponent(coords.label || "")}&cc=${encodeURIComponent(coords.cc || "")}`
        : `location=${encodeURIComponent(q || "")}`;
      const res = await fetch(`${API}/summary?${params}&hours=12&days=10`);
      const j = await res.json();
      if (j.error) { setErr(j.error); setData(null); }
      else { setData(j); if (j.place?.display_label) setQuery(j.place.display_label); }
    } catch {
      setErr("Couldn't reach the weather service.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(""); }, [load]);

  // Go/Refresh: if the box is UNCHANGED from the place already shown, the user is
  // refreshing — refetch by the stored lat/lon (no re-geocoding the verbose
  // display_label). If the box was changed to a different place, geocode it.
  const submitQuery = (q) => {
    const t = (q || "").trim();
    const cur = (data?.place?.display_label || "").trim();
    if (data?.place && t === cur) {
      load("", { lat: data.place.lat, lon: data.place.lon,
                 label: data.place.display_label, cc: data.place.country_code });
    } else {
      load(t);
    }
  };

  const submit = (e) => { e.preventDefault(); submitQuery(query); };

  return (
    <div className="h-full overflow-y-auto surface-page text-default">
      <div className="max-w-3xl mx-auto p-5">
        <div className="flex items-center gap-2 mb-4">
          <CloudSun className="text-accent" size={22} />
          <h1 className="text-xl font-bold">Weather</h1>
          <form onSubmit={submit} className="ml-auto flex items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="City, Region, Country or postal,country"
                title="e.g. Austin, Texas, US  —or—  SW1A 1AA, UK"
                className="w-56 rounded surface-panel border border-subtle pl-7 pr-2 py-1.5 text-sm focus:border-[var(--ds-accent)] focus:outline-none"
              />
            </div>
            <button type="submit" className="rounded btn-primary px-3 py-1.5 text-sm font-medium">Go</button>
            <button type="button" onClick={() => submitQuery(query)} title="Refresh" className="icon-btn p-1.5">
              <RefreshCw size={15} />
            </button>
          </form>
        </div>

        {/* tabs: Current | Forecast | Radar */}
        <div className="flex items-center gap-1 mb-4 border-b border-subtle">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${
                  active ? "border-[var(--ds-accent)] text-accent" : "border-transparent text-muted hover:text-[var(--ds-text)]"
                }`}
              >
                <Icon size={14} /> {t.label}
              </button>
            );
          })}
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-muted py-16 justify-center"><Loader2 className="animate-spin" size={16} /> Loading forecast…</div>
        ) : err ? (
          <div className="rounded-lg border border-amber-800/50 bg-amber-950/40 text-amber-300 px-4 py-3 text-sm">{err}</div>
        ) : !data ? null : (
          <>
            {/* ── Current ── */}
            {tab === "current" && (
              <div className="rounded-2xl border border-subtle surface-card p-5 mb-5">
                <div className="text-sm text-muted">{data.place.display_label}</div>
                <div className="flex items-center gap-4 mt-2">
                  <div className="text-6xl leading-none">{ICON(data.current.code)}</div>
                  <div>
                    <div className="text-5xl font-bold">{round(data.current.temp)}°</div>
                    <div className="text-default">{data.current.desc}</div>
                  </div>
                  <div className="ml-auto text-right text-sm text-default space-y-1">
                    <div>Feels like {round(data.current.feels)}°</div>
                    <div className="flex items-center justify-end gap-1.5"><Droplets size={13} className="text-accent" /> {round(data.current.humidity)}%</div>
                    <div className="flex items-center justify-end gap-1.5"><Wind size={13} className="text-muted" /> {round(data.current.wind)} mph</div>
                    {data.current.uv !== null && data.current.uv !== undefined && (
                      <div className="flex items-center justify-end gap-1.5"><Sun size={13} className="text-amber-400" /> UV {uvLabel(data.current.uv)}</div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── Forecast: hourly + 10-day ── */}
            {tab === "forecast" && (
              <>
                <h2 className="text-sm font-semibold text-default mb-2">Next 12 hours</h2>
                <div className="flex gap-2 overflow-x-auto pb-2 mb-5">
                  {data.hourly.map((h) => (
                    <div key={h.time} className="shrink-0 w-16 rounded-lg border border-subtle surface-panel p-2 text-center">
                      <div className="text-[11px] text-muted">{hourLabel(h.time)}</div>
                      <div className="text-xl my-1">{ICON(h.code)}</div>
                      <div className="text-sm font-medium">{round(h.temp)}°</div>
                      <div className="text-[10px] text-accent h-3">{h.pop ? `${h.pop}%` : ""}</div>
                    </div>
                  ))}
                </div>

                <h2 className="text-sm font-semibold text-default mb-2">10-day forecast</h2>
                <div className="rounded-xl border border-subtle surface-panel divide-y divide-[var(--ds-border)]">
                  {data.daily.map((d, i) => (
                    <div key={d.date} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                      <span className="w-12 text-default">{dayLabel(d.date, i)}</span>
                      <span className="text-lg w-7 text-center">{ICON(d.code)}</span>
                      <span className="flex-1 text-muted truncate">{d.desc}</span>
                      <span className="text-accent w-12 text-right text-xs">{d.pop ? `${d.pop}%` : ""}</span>
                      <span className="w-16 text-right"><span className="font-semibold">{round(d.hi)}°</span> <span className="text-faint">{round(d.lo)}°</span></span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* ── Radar: ~100-mile NEXRAD + severe-weather map ── */}
            {tab === "radar" && (
              <Suspense fallback={<div className="text-faint text-sm py-6 text-center">Loading map…</div>}>
                <WeatherMap place={data.place} />
              </Suspense>
            )}

            <p className="text-[11px] text-faint mt-4">
              Keyless data via open-meteo; base map © OpenStreetMap, radar © IEM NEXRAD, severe-weather alerts © NWS.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
