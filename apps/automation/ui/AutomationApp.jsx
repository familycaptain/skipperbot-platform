// =============================================================================
// Automation — Home Assistant
// =============================================================================
// Two tabs:
//   • Dashboard — live entities (lights/switches/fans toggles + sensors).
//   • Names     — manage the device registry aliases + trained entity aliases
//                 (the same data Skipper uses for voice/chat; editable here or
//                 by chat: "the corner lamp means light.living_room_floor_lamp").
// Talks to /api/apps/automation. Degrades to a setup card when HA isn't set up.
import { useState, useEffect, useCallback } from "react";
import {
  Lightbulb, Power, RefreshCw, Loader2, AlertCircle, Plug, Fan, ToggleRight,
  Thermometer, Activity, Lock, Blinds, MonitorPlay, LayoutGrid, Tag, Cpu,
  Plus, Trash2, X, Pencil, Check,
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
        {message || "Home Assistant isn't configured yet."} Set the URL + token in
        Settings → Automation, then refresh.
      </p>
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

// ---------------------------------------------------------------------------
// Tab 1 — live dashboard
// ---------------------------------------------------------------------------
function DashboardView({ status }) {
  const [groups, setGroups] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const d = await (await fetch(`${API}/entities`)).json();
      setGroups(d.groups || {});
      if (d.message) setError(d.message);
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

  if (!status?.connected) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center px-6">
        <AlertCircle size={36} className="text-rose-400/70 mb-3" />
        <p className="text-sm font-medium text-slate-300">Can't reach Home Assistant</p>
        <p className="text-xs text-slate-500 mt-2 max-w-md break-words">{status?.message}</p>
      </div>
    );
  }

  const order = ["light", "switch", "fan", "input_boolean", "climate", "media_player", "cover", "lock", "binary_sensor", "sensor"];
  const domains = Object.keys(groups).sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });

  return (
    <div>
      <div className="flex items-center justify-end mb-3">
        <button onClick={load} disabled={loading} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300">
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Refresh
        </button>
      </div>
      {error && <div className="mb-3 text-xs text-rose-400 flex items-center gap-1.5"><AlertCircle size={12} /> {error}</div>}
      {loading && domains.length === 0 && <div className="flex justify-center py-12 text-slate-500"><Loader2 className="animate-spin" /></div>}
      {!loading && domains.length === 0 && <p className="text-sm text-slate-500">No entities found.</p>}
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
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — names management (devices + aliases)
// ---------------------------------------------------------------------------
function AliasChip({ text, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-200 text-[11px]">
      {text}
      <button onClick={onRemove} className="text-slate-400 hover:text-rose-300" title="Remove alias">
        <X size={11} />
      </button>
    </span>
  );
}

function DeviceRow({ d, onAddAlias, onRemoveAlias, busy }) {
  const [draft, setDraft] = useState("");
  const add = () => { const v = draft.trim(); if (v) { onAddAlias(d, v); setDraft(""); } };
  return (
    <div className="px-3 py-2.5 rounded-lg bg-slate-800/40 border border-slate-700/50">
      <div className="flex items-center gap-2">
        <Cpu size={14} className="text-slate-500 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-sm text-slate-200 truncate">{d.name || "(unnamed device)"}</div>
          {(d.manufacturer || d.model) && (
            <div className="text-[11px] text-slate-500 truncate">{[d.manufacturer, d.model].filter(Boolean).join(" · ")}</div>
          )}
        </div>
        {busy === d.device_id && <Loader2 size={12} className="animate-spin text-slate-500" />}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 mt-2">
        {(d.aliases || []).map((a) => (
          <AliasChip key={a} text={a} onRemove={() => onRemoveAlias(d, a)} />
        ))}
        <span className="inline-flex items-center gap-1">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="add alias…"
            className="w-28 px-2 py-0.5 text-[11px] rounded bg-slate-900 border border-slate-700 text-slate-200 placeholder:text-slate-600"
          />
          <button onClick={add} className="text-slate-400 hover:text-emerald-300" title="Add alias"><Plus size={13} /></button>
        </span>
      </div>
    </div>
  );
}

function NamesManager() {
  const [aliases, setAliases] = useState([]);
  const [devices, setDevices] = useState([]);
  const [entities, setEntities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null);
  const [form, setForm] = useState({ alias: "", entity_id: "", notes: "" });
  const [editing, setEditing] = useState(null);  // original alias key being edited
  const [editForm, setEditForm] = useState({ alias: "", entity_id: "", notes: "" });

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [al, dv, en] = await Promise.all([
        fetch(`${API}/aliases`).then((r) => r.json()),
        fetch(`${API}/devices`).then((r) => r.json()),
        fetch(`${API}/all-entities`).then((r) => r.json()),
      ]);
      setAliases(al.aliases || []);
      setDevices(dv.devices || []);
      setEntities(en.entities || []);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const addAlias = useCallback(async () => {
    if (!form.alias.trim() || !form.entity_id.trim()) { setError("Alias and entity are required."); return; }
    setError("");
    const res = await fetch(`${API}/aliases`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    const data = await res.json();
    if (!data.ok) { setError(data.message || "Could not save alias."); return; }
    setForm({ alias: "", entity_id: "", notes: "" });
    const al = await fetch(`${API}/aliases`).then((r) => r.json());
    setAliases(al.aliases || []);
  }, [form]);

  const deleteAlias = useCallback(async (alias) => {
    await fetch(`${API}/aliases/${encodeURIComponent(alias)}`, { method: "DELETE" });
    setAliases((prev) => prev.filter((a) => a.alias !== alias));
  }, []);

  const startEdit = useCallback((a) => {
    setError("");
    setEditing(a.alias);
    setEditForm({ alias: a.alias, entity_id: a.entity_id, notes: a.notes || "" });
  }, []);

  const cancelEdit = useCallback(() => { setEditing(null); }, []);

  const saveEdit = useCallback(async (originalAlias) => {
    if (!editForm.alias.trim() || !editForm.entity_id.trim()) { setError("Alias and entity are required."); return; }
    setError("");
    const res = await fetch(`${API}/aliases/${encodeURIComponent(originalAlias)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(editForm),
    });
    const data = await res.json();
    if (!data.ok) { setError(data.message || "Could not update alias."); return; }
    setEditing(null);
    const al = await fetch(`${API}/aliases`).then((r) => r.json());
    setAliases(al.aliases || []);
  }, [editForm]);

  const saveDeviceAliases = useCallback(async (device, nextAliases) => {
    setBusy(device.device_id);
    setDevices((prev) => prev.map((x) => x.device_id === device.device_id ? { ...x, aliases: nextAliases } : x));
    try {
      await fetch(`${API}/devices/${encodeURIComponent(device.device_id)}/aliases`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ aliases: nextAliases }),
      });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }, []);

  const addDeviceAlias = (d, alias) => saveDeviceAliases(d, [...(d.aliases || []), alias]);
  const removeDeviceAlias = (d, alias) => saveDeviceAliases(d, (d.aliases || []).filter((a) => a !== alias));

  if (loading) {
    return <div className="flex justify-center py-12 text-slate-500"><Loader2 className="animate-spin" /></div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-slate-500">
          Teach Skipper what things are called. You can also do this by chat — e.g.
          “the corner lamp means light.living_room_floor_lamp”.
        </p>
        <button onClick={load} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      {error && <div className="mb-3 text-xs text-rose-400 flex items-center gap-1.5"><AlertCircle size={12} /> {error}</div>}

      {/* Entity aliases */}
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2 flex items-center gap-1.5">
        <Tag size={12} /> Entity aliases
      </h2>
      <div className="rounded-lg bg-slate-800/40 border border-slate-700/50 p-3 mb-3">
        <div className="flex flex-wrap gap-2 items-end">
          <div className="flex flex-col">
            <label className="text-[10px] text-slate-500 mb-0.5">Name people say</label>
            <input value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })}
              placeholder="tv, kitchen lamp…"
              className="w-40 px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200 placeholder:text-slate-600" />
          </div>
          <div className="flex flex-col">
            <label className="text-[10px] text-slate-500 mb-0.5">Home Assistant entity</label>
            <input value={form.entity_id} onChange={(e) => setForm({ ...form, entity_id: e.target.value })}
              list="ha-entities" placeholder="media_player.living_room_tv"
              className="w-72 px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200 placeholder:text-slate-600 font-mono" />
            <datalist id="ha-entities">
              {entities.map((e) => <option key={e.entity_id} value={e.entity_id}>{e.name}</option>)}
            </datalist>
          </div>
          <div className="flex flex-col">
            <label className="text-[10px] text-slate-500 mb-0.5">Notes (optional)</label>
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="w-40 px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200" />
          </div>
          <button onClick={addAlias} className="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-emerald-600/80 hover:bg-emerald-600 text-white">
            <Plus size={13} /> Add
          </button>
        </div>
      </div>
      <div className="space-y-1.5 mb-6">
        {aliases.length === 0 && <p className="text-sm text-slate-500">No aliases yet.</p>}
        {aliases.map((a) => editing === a.alias ? (
          <div key={a.alias} className="flex flex-wrap items-end gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-amber-700/40">
            <div className="flex flex-col">
              <label className="text-[10px] text-slate-500 mb-0.5">Name</label>
              <input value={editForm.alias} onChange={(e) => setEditForm({ ...editForm, alias: e.target.value })}
                className="w-36 px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200" />
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] text-slate-500 mb-0.5">Entity</label>
              <input value={editForm.entity_id} onChange={(e) => setEditForm({ ...editForm, entity_id: e.target.value })}
                list="ha-entities"
                className="w-64 px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200 font-mono" />
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] text-slate-500 mb-0.5">Notes</label>
              <input value={editForm.notes} onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                className="w-36 px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200" />
            </div>
            <button onClick={() => saveEdit(a.alias)} className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded bg-emerald-600/80 hover:bg-emerald-600 text-white" title="Save">
              <Check size={13} /> Save
            </button>
            <button onClick={cancelEdit} className="inline-flex items-center gap-1 px-2 py-1.5 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-200" title="Cancel">
              <X size={13} />
            </button>
          </div>
        ) : (
          <div key={a.alias} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/50">
            <div className="min-w-0 flex-1">
              <div className="text-sm text-slate-200">
                <span className="font-medium">{a.alias}</span>
                <span className="text-slate-500"> → </span>
                <span className="font-mono text-xs text-slate-400">{a.entity_id}</span>
              </div>
              {a.notes && <div className="text-[11px] text-slate-500 truncate">{a.notes}</div>}
            </div>
            <button onClick={() => startEdit(a)} className="shrink-0 text-slate-500 hover:text-amber-300" title="Edit alias">
              <Pencil size={14} />
            </button>
            <button onClick={() => deleteAlias(a.alias)} className="shrink-0 text-slate-500 hover:text-rose-300" title="Delete alias">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Device registry */}
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2 flex items-center gap-1.5">
        <Cpu size={12} /> Devices ({devices.length})
      </h2>
      <p className="text-[11px] text-slate-600 mb-2">
        Synced hourly from Home Assistant. Add friendly names so voice/chat can find each device.
      </p>
      <div className="grid sm:grid-cols-2 gap-2">
        {devices.length === 0 && <p className="text-sm text-slate-500">No devices cached yet.</p>}
        {devices.map((d) => (
          <DeviceRow key={d.device_id} d={d} onAddAlias={addDeviceAlias} onRemoveAlias={removeDeviceAlias} busy={busy} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shell — tab bar + status gating
// ---------------------------------------------------------------------------
export default function AutomationApp() {
  const [status, setStatus] = useState(null);   // {configured, connected, message}
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("dashboard");

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await (await fetch(`${API}/status`)).json());
    } catch (e) {
      setStatus({ configured: false, connected: false, message: String(e.message || e) });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  if (loading && !status) {
    return <div className="flex items-center justify-center h-full text-slate-500"><Loader2 className="animate-spin" /></div>;
  }
  // The Names tab works without HA (reads the DB), but with nothing configured
  // there's nothing useful yet — show the setup card.
  if (!status?.configured) return <SetupCard message={status?.message} />;

  const TABS = [
    { id: "dashboard", label: "Dashboard", icon: LayoutGrid },
    { id: "names", label: "Names", icon: Tag },
  ];

  return (
    <div className="h-full w-full overflow-y-auto bg-slate-950 p-5">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-2 mb-4">
          <Lightbulb className="text-amber-400" size={20} />
          <h1 className="text-lg font-bold text-slate-100">Automation</h1>
          {status?.connected
            ? <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-900/40 text-emerald-300 border border-emerald-700/40">connected</span>
            : <span className="text-[11px] px-2 py-0.5 rounded-full bg-rose-900/40 text-rose-300 border border-rose-700/40">offline</span>}
        </div>

        <div className="flex gap-1 mb-4 border-b border-slate-800">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium -mb-px border-b-2 transition-colors ${
                  active ? "border-amber-400 text-amber-300" : "border-transparent text-slate-400 hover:text-slate-200"
                }`}>
                <Icon size={13} /> {t.label}
              </button>
            );
          })}
        </div>

        {tab === "dashboard" ? <DashboardView status={status} /> : <NamesManager />}
      </div>
    </div>
  );
}
