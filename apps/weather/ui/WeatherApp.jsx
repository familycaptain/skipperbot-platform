// =============================================================================
// Weather — local forecast dashboard
// =============================================================================
// Current conditions + 12-hour hourly + 10-day daily for a US ZIP (defaults to
// the configured home ZIP). One fetch to GET /api/apps/weather/summary.
// (A ~100-mile radar/alerts map is a planned follow-up — see the issue.)
// =============================================================================

import { useState, useEffect, useCallback, lazy, Suspense } from "react";
import { CloudSun, Loader2, Search, Wind, Droplets, Sun, RefreshCw } from "lucide-react";

const API = "/api/apps/weather";
const WeatherMap = lazy(() => import("./WeatherMap"));

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

export default function WeatherApp() {
  const [zip, setZip] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async (z) => {
    setLoading(true);
    setErr("");
    try {
      const res = await fetch(`${API}/summary?zip=${encodeURIComponent(z || "")}&hours=12&days=10`);
      const j = await res.json();
      if (j.error) { setErr(j.error); setData(null); }
      else { setData(j); if (j.place?.zip) setZip(j.place.zip); }
    } catch {
      setErr("Couldn't reach the weather service.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(""); }, [load]);

  const submit = (e) => { e.preventDefault(); load(zip.trim()); };

  return (
    <div className="h-full overflow-y-auto bg-gradient-to-b from-sky-950 to-slate-950 text-slate-100">
      <div className="max-w-3xl mx-auto p-5">
        <div className="flex items-center gap-2 mb-4">
          <CloudSun className="text-sky-400" size={22} />
          <h1 className="text-xl font-bold">Weather</h1>
          <form onSubmit={submit} className="ml-auto flex items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={zip}
                onChange={(e) => setZip(e.target.value)}
                placeholder="ZIP"
                inputMode="numeric"
                className="w-28 rounded bg-slate-900 border border-slate-700 pl-7 pr-2 py-1.5 text-sm focus:border-sky-500 focus:outline-none"
              />
            </div>
            <button type="submit" className="rounded bg-sky-600 hover:bg-sky-500 px-3 py-1.5 text-sm font-medium">Go</button>
            <button type="button" onClick={() => load(zip.trim())} title="Refresh" className="text-slate-400 hover:text-white p-1.5">
              <RefreshCw size={15} />
            </button>
          </form>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 py-16 justify-center"><Loader2 className="animate-spin" size={16} /> Loading forecast…</div>
        ) : err ? (
          <div className="rounded-lg border border-amber-800/50 bg-amber-950/40 text-amber-300 px-4 py-3 text-sm">{err}</div>
        ) : !data ? null : (
          <>
            {/* current conditions */}
            <div className="rounded-2xl border border-sky-800/40 bg-sky-900/20 p-5 mb-5">
              <div className="text-sm text-slate-400">{data.place.city}, {data.place.region} · {data.place.zip}</div>
              <div className="flex items-center gap-4 mt-2">
                <div className="text-6xl leading-none">{ICON(data.current.code)}</div>
                <div>
                  <div className="text-5xl font-bold">{round(data.current.temp)}°</div>
                  <div className="text-slate-300">{data.current.desc}</div>
                </div>
                <div className="ml-auto text-right text-sm text-slate-300 space-y-1">
                  <div>Feels like {round(data.current.feels)}°</div>
                  <div className="flex items-center justify-end gap-1.5"><Droplets size={13} className="text-sky-400" /> {round(data.current.humidity)}%</div>
                  <div className="flex items-center justify-end gap-1.5"><Wind size={13} className="text-slate-400" /> {round(data.current.wind)} mph</div>
                  {data.current.uv !== null && data.current.uv !== undefined && (
                    <div className="flex items-center justify-end gap-1.5"><Sun size={13} className="text-amber-400" /> UV {uvLabel(data.current.uv)}</div>
                  )}
                </div>
              </div>
            </div>

            {/* hourly */}
            <h2 className="text-sm font-semibold text-slate-300 mb-2">Next 12 hours</h2>
            <div className="flex gap-2 overflow-x-auto pb-2 mb-5">
              {data.hourly.map((h) => (
                <div key={h.time} className="shrink-0 w-16 rounded-lg border border-slate-700/50 bg-slate-900/40 p-2 text-center">
                  <div className="text-[11px] text-slate-400">{hourLabel(h.time)}</div>
                  <div className="text-xl my-1">{ICON(h.code)}</div>
                  <div className="text-sm font-medium">{round(h.temp)}°</div>
                  <div className="text-[10px] text-sky-400 h-3">{h.pop ? `${h.pop}%` : ""}</div>
                </div>
              ))}
            </div>

            {/* daily */}
            <h2 className="text-sm font-semibold text-slate-300 mb-2">10-day forecast</h2>
            <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 divide-y divide-slate-800">
              {data.daily.map((d, i) => (
                <div key={d.date} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                  <span className="w-12 text-slate-300">{dayLabel(d.date, i)}</span>
                  <span className="text-lg w-7 text-center">{ICON(d.code)}</span>
                  <span className="flex-1 text-slate-400 truncate">{d.desc}</span>
                  <span className="text-sky-400 w-12 text-right text-xs">{d.pop ? `${d.pop}%` : ""}</span>
                  <span className="w-16 text-right"><span className="font-semibold">{round(d.hi)}°</span> <span className="text-slate-500">{round(d.lo)}°</span></span>
                </div>
              ))}
            </div>

            {/* radar + severe-weather map (~100 mi) */}
            <h2 className="text-sm font-semibold text-slate-300 mt-5 mb-2">Radar &amp; severe-weather (~100 mi)</h2>
            <Suspense fallback={<div className="text-slate-500 text-sm py-6 text-center">Loading map…</div>}>
              <WeatherMap place={data.place} />
            </Suspense>

            <p className="text-[11px] text-slate-600 mt-4">
              Keyless data via open-meteo; base map © OpenStreetMap, radar © IEM NEXRAD, severe-weather alerts © NWS.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
