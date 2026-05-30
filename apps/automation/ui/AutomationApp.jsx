// =============================================================================
// Automation — Home Assistant dashboard
// =============================================================================
// Lists controllable Home Assistant entities (lights, switches, fans) with
// on/off toggles + light brightness, plus read-only sensors/climate. Talks to
// /api/apps/automation. Degrades to a setup card when HA isn't configured.
import { useState, useEffect, useCallback } from "react";
import {
  Lightbulb, Power, RefreshCw, Loader2, AlertCircle, Plug, Fan, ToggleRight,
  Thermometer, Activity, Lock, Blinds, MonitorPlay,
} from "lucide-react";

const API = "/api/apps/automation";

const DOMAIN_META = {
  light:        { label: "Lights",   icon: Lightbulb },
  switch:       { label: "Switches", icon: Plug },
  fan:          { label: "Fans",     icon: Fan },
  input_boolean:{ label: "Toggles",  icon: ToggleRight },
  climate:      { label: "Climate",  icon: Thermometer },
  sensor:       { label: "Sensors",  icon: Activity },
  binary_sensor:{ label: "Sensors",  icon: Activity },
  media_player: { label: "Media",    icon: MonitorPlay },
  cover:        { label: "Covers",   icon: Blinds },
  lock:         { label: "Locks",    icon: Lock },
};

function SetupCard({ message }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-6">
      <Lightbulb size={40} className="text-amber-400/70 mb-3" />
      <p className="text-base font-medium text-slate-200">Connect Home Assistant</p>
      <p className="text-sm text-slate-400 mt-2 max-w-md">
        {message || "Home Assistant isn't configured yet."} Skipper can already
        control your home by voice/chat once these are set.
      </p>
      <div className="mt-4 text-left text-xs font-mono bg-slate-900 border border-slate-700 rounded-lg p-4 text-slate-300 max-w-md w-full">
        <div className="text-slate-500"># add to .env, then restart the agent</div>
        <div>HOME_ASSISTANT_URL=http://homeassistant.local:8123</div>
        <div>HOME_ASSISTANT_TOKEN=&lt;long-lived access token&gt;</div>
      </div>
      <p className="text-xs text-slate-600 mt-3 max-w-md">
        Create a token in Home Assistant → your profile → Long-Lived Access Tokens.
      </p>
    </div>
  );
}

function EntityRow({ e, onControl, busy }) {
  const Icon = (DOMAIN_META[e.domain] || {}).icon || Activity;
  const isBusy = busy === e.entity_id;
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-slate-800/40 border border-slate-700/50">
      <Icon size={16} className={e.on ? "text-amber-300" : "text-slate-500"} />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-slate-200 truncate">{e.name}</div>
        <div className="text-[11px] text-slate-500 truncate">
          {e.state}{e.unit ? ` ${e.unit}` : ""}
          {typeof e.brightness_pct === "number" && e.on ? ` · ${e.brightness_pct}%` : ""}
        </div>
      </div>
      {e.domain === "light" && e.on && typeof e.brightness_pct === "number" && (
        <input
          type="range" min="1" max="100" value={e.brightness_pct} disabled={isBusy}
          onChange={(ev) => onControl(e, "on", Number(ev.target.value))}
          className="w-24 accent-amber-400"
          title="Brightness"
        />
      )}
      {e.toggleable ? (
        <button
          onClick={() => onControl(e, "toggle")}
          disabled={isBusy}
          className={`shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
            e.on ? "bg-amber-500/20 text-amber-300 hover:bg-amber-500/30"
                 : "bg-slate-700/60 text-slate-400 hover:bg-slate-700"
          }`}
        >
          {isBusy ? <Loader2 size={12} className="animate-spin" /> : <Power size={12} />}
          {e.on ? "On" : "Off"}
        </button>
      ) : (
        <span className="shrink-0 text-xs text-slate-500 px-2">{e.state}</span>
      )}
    </div>
  );
}

export default function AutomationApp() {
  const [status, setStatus] = useState(null);   // {configured, connected, message}
  const [groups, setGroups] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const s = await (await fetch(`${API}/status`)).json();
      setStatus(s);
      if (s.configured && s.connected) {
        const d = await (await fetch(`${API}/entities`)).json();
        setGroups(d.groups || {});
        if (d.message) setError(d.message);
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const control = useCallback(async (e, action, brightness_pct) => {
    setBusy(e.entity_id);
    try {
      const res = await fetch(`${API}/control`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: e.entity_id, action, brightness_pct }),
      });
      const data = await res.json();
      if (data.ok && data.entity) {
        setGroups((prev) => {
          const next = { ...prev };
          next[e.domain] = (next[e.domain] || []).map((x) => x.entity_id === e.entity_id ? data.entity : x);
          return next;
        });
      } else if (!data.ok) {
        setError(data.error || "Control failed");
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(null);
    }
  }, []);

  if (loading && !status) {
    return <div className="flex items-center justify-center h-full text-slate-500"><Loader2 className="animate-spin" /></div>;
  }
  if (!status?.configured) return <SetupCard message={status?.message} />;
  if (!status?.connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <AlertCircle size={36} className="text-rose-400/70 mb-3" />
        <p className="text-sm font-medium text-slate-300">Can't reach Home Assistant</p>
        <p className="text-xs text-slate-500 mt-2 max-w-md break-words">{status?.message}</p>
        <button onClick={load} className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-200">
          <RefreshCw size={12} /> Retry
        </button>
      </div>
    );
  }

  const order = ["light", "switch", "fan", "input_boolean", "climate", "media_player", "cover", "lock", "binary_sensor", "sensor"];
  const domains = Object.keys(groups).sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });

  return (
    <div className="h-full w-full overflow-y-auto bg-slate-950 p-5">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Lightbulb className="text-amber-400" size={20} />
            <h1 className="text-lg font-bold text-slate-100">Automation</h1>
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-900/40 text-emerald-300 border border-emerald-700/40">Home Assistant connected</span>
          </div>
          <button onClick={load} disabled={loading} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300">
            {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Refresh
          </button>
        </div>
        {error && <div className="mb-3 text-xs text-rose-400 flex items-center gap-1.5"><AlertCircle size={12} /> {error}</div>}
        {domains.length === 0 && <p className="text-sm text-slate-500">No entities found.</p>}
        {domains.map((dom) => {
          const meta = DOMAIN_META[dom] || { label: dom };
          return (
            <div key={dom} className="mb-5">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">{meta.label}</h2>
              <div className="grid sm:grid-cols-2 gap-2">
                {groups[dom].map((e) => (
                  <EntityRow key={e.entity_id} e={e} onControl={control} busy={busy} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
