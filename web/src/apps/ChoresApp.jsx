import { useState, useEffect, useCallback } from "react";
import {
  CalendarDays, ListTodo, Settings, Plus, Pencil, Trash2, RefreshCw,
  Check, ChevronLeft, ChevronRight, X,
} from "lucide-react";
import { hasAnyRole } from "../utils/roles";

const API = "/api/apps/chores";

const TABS = [
  { id: "today",  label: "Today", icon: ListTodo },
  { id: "week",   label: "Week",  icon: CalendarDays },
  { id: "manage", label: "Manage", icon: Settings, parentOnly: true },
];

const DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DOW_LONG  = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function fmtDate(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function todayISO() {
  // Local-zone date. toISOString() returns UTC, which silently rolls the
  // date forward in the evening (e.g. Mon 7pm Central is Tue in UTC).
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDays(isoDate, n) {
  const d = new Date(isoDate + "T00:00:00");
  d.setDate(d.getDate() + n);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function ChoresApp({ appId, userId, userRole, refreshKey, isActive }) {
  const [activeTab, setActiveTab] = useState("today");
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);
  const visibleTabs = TABS.filter(t => !t.parentOnly || isParent);

  useEffect(() => {
    if (!visibleTabs.some(t => t.id === activeTab)) setActiveTab("today");
  }, [activeTab, visibleTabs]);

  return (
    <div className="flex flex-col h-full w-full bg-zinc-950 text-zinc-100">
      <div className="flex items-center gap-1 px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        {visibleTabs.map(tab => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md whitespace-nowrap transition-colors ${
                active ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              <Icon size={13} />
              {tab.label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTab === "today"  && <TodayTab  userId={userId} isParent={isParent} refreshKey={refreshKey} />}
        {activeTab === "week"   && <WeekTab   userId={userId} isParent={isParent} refreshKey={refreshKey} />}
        {activeTab === "manage" && <ManageTab userId={userId} refreshKey={refreshKey} />}
      </div>
    </div>
  );
}

// ===========================================================================
// Today tab
// ===========================================================================

function TodayTab({ userId, isParent, refreshKey }) {
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    try {
      const v = await apiFetch(`/today?date=${date}`);
      setData(v);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load, refreshKey]);

  // Silent auto-refresh every 30s so siblings see each other's check-offs.
  useEffect(() => {
    const t = setInterval(() => load(true), 30000);
    return () => clearInterval(t);
  }, [load]);

  const canActOn = useCallback((kid) => {
    if (isParent) return true;
    return kid.user_id === userId;
  }, [isParent, userId]);

  const toggle = async (kid, assignment) => {
    if (!canActOn(kid)) return;
    try {
      if (assignment.completed) {
        await apiFetch(`/complete/${assignment.completion.id}?acted_by=${encodeURIComponent(userId)}`, { method: "DELETE" });
      } else {
        await apiFetch(`/complete`, {
          method: "POST",
          body: JSON.stringify({
            chore_id: assignment.chore_id,
            kid_id: kid.id,
            date,
            acted_by: userId,
          }),
        });
      }
      load(true);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        <button onClick={() => setDate(addDays(date, -1))} className="p-1.5 hover:bg-slate-800 rounded">
          <ChevronLeft size={16} />
        </button>
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm"
        />
        <button onClick={() => setDate(addDays(date, 1))} className="p-1.5 hover:bg-slate-800 rounded">
          <ChevronRight size={16} />
        </button>
        <button
          onClick={() => setDate(todayISO())}
          className="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 rounded ml-2"
        >Today</button>
        <div className="flex-1" />
        <button onClick={() => load()} className="p-1.5 hover:bg-slate-800 rounded">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 text-red-300 text-sm rounded p-2">
          {error}
        </div>
      )}

      {!data && <div className="text-slate-500 text-sm">Loading…</div>}

      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {data.kids.map(kid => {
            const isYou = kid.user_id === userId;
            const interactive = canActOn(kid);
            return (
              <div
                key={kid.id}
                className="bg-slate-900 border border-slate-800 rounded-lg p-3"
                style={{ borderTopColor: kid.color, borderTopWidth: 3 }}
              >
                <div className="flex items-baseline justify-between mb-2">
                  <div className="text-sm font-semibold" style={{ color: kid.color }}>
                    {kid.name}{isYou ? " (you)" : ""}
                  </div>
                  {kid.assignments.length === 0 && (
                    <span className="text-xs text-slate-500">nothing today</span>
                  )}
                </div>
                <ul className="space-y-1">
                  {kid.assignments.map(a => (
                    <li key={a.chore_id} className="flex items-start gap-2 text-sm">
                      <button
                        onClick={() => toggle(kid, a)}
                        disabled={!interactive}
                        className={`mt-0.5 w-5 h-5 flex items-center justify-center rounded border ${
                          a.completed
                            ? "bg-emerald-600 border-emerald-500 text-white"
                            : "border-slate-600"
                        } ${interactive ? "cursor-pointer hover:border-indigo-500" : "cursor-not-allowed opacity-70"}`}
                        title={interactive ? "Toggle done" : "View only"}
                      >
                        {a.completed && <Check size={12} />}
                      </button>
                      <div className="flex-1 min-w-0">
                        <div className={a.completed ? "line-through text-slate-500" : ""}>
                          {a.chore_name}
                        </div>
                        <div className="text-xs text-slate-500">
                          {a.zone_name}
                          {a.note && <span> · {a.note}</span>}
                          {a.completion?.completed_at && (
                            <span> · {new Date(a.completion.completed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
                          )}
                          {a.completion?.completed_by && a.completion.completed_by !== kid.user_id && (
                            <span> · by {a.completion.completed_by}</span>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Week tab
// ===========================================================================

function WeekTab({ userId, isParent, refreshKey }) {
  const [start, setStart] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - ((d.getDay() + 7) % 7)); // Sunday
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  });
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const v = await apiFetch(`/week?start=${start}`);
      setData(v);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, [start]);

  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <button onClick={() => setStart(addDays(start, -7))} className="p-1.5 hover:bg-slate-800 rounded">
          <ChevronLeft size={16} />
        </button>
        <input
          type="date"
          value={start}
          onChange={e => setStart(e.target.value)}
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm"
        />
        <button onClick={() => setStart(addDays(start, 7))} className="p-1.5 hover:bg-slate-800 rounded">
          <ChevronRight size={16} />
        </button>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}
      {!data && <div className="text-slate-500 text-sm">Loading…</div>}

      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 border-b border-slate-800">
                <th className="py-2 px-2">Kid</th>
                {data.days.map(day => (
                  <th key={day.date} className="py-2 px-2">{fmtDate(day.date)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.kids.map(k => (
                <tr key={k.id} className="border-b border-slate-900 align-top">
                  <td className="py-2 px-2 font-semibold" style={{ color: k.color }}>{k.name}</td>
                  {data.days.map(day => {
                    const kidDay = day.kids.find(x => x.id === k.id);
                    const ass = kidDay?.assignments || [];
                    return (
                      <td key={day.date} className="py-2 px-2 text-xs">
                        {ass.length === 0
                          ? <span className="text-slate-600">—</span>
                          : ass.map(a => (
                              <div key={a.chore_id} className={a.completed ? "line-through text-slate-500" : ""}>
                                {a.completed ? "✓" : "•"} {a.chore_name}
                              </div>
                            ))}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Manage tab (parent-only)
// ===========================================================================

function ManageTab({ userId, refreshKey }) {
  const [tab, setTab] = useState("kids");
  return (
    <div className="p-4 space-y-3">
      <div className="flex gap-1 mb-2">
        {[["kids", "Kids"], ["zones", "Zones"]].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-3 py-1 text-xs rounded ${
              tab === id ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >{label}</button>
        ))}
      </div>
      {tab === "kids"  && <ManageKids  userId={userId} refreshKey={refreshKey} />}
      {tab === "zones" && <ManageZones userId={userId} refreshKey={refreshKey} />}
    </div>
  );
}

// --- Kids ----

function ManageKids({ userId, refreshKey }) {
  const [kids, setKids] = useState([]);
  const [draft, setDraft] = useState({ name: "", color: "#888888", user_id: "", sort_order: 0 });
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null); // kid being edited

  const load = useCallback(async () => {
    setError("");
    try {
      const v = await apiFetch(`/kids?include_inactive=true`);
      setKids(v.kids);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const add = async () => {
    if (!draft.name.trim()) return;
    try {
      await apiFetch(`/kids`, {
        method: "POST",
        body: JSON.stringify({ ...draft, acted_by: userId }),
      });
      setDraft({ name: "", color: "#888888", user_id: "", sort_order: 0 });
      load();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const save = async (kid, fields) => {
    try {
      await apiFetch(`/kids/${kid.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...fields, acted_by: userId }),
      });
      setEditing(null);
      load();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const remove = async (kid) => {
    if (!confirm(`Remove ${kid.name}? (Soft delete — history kept)`)) return;
    try {
      await apiFetch(`/kids/${kid.id}?acted_by=${encodeURIComponent(userId)}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="space-y-2">
      {error && <div className="text-red-400 text-sm">{error}</div>}

      <div className="bg-slate-900 border border-slate-800 rounded p-2 flex flex-wrap gap-2 items-end text-sm">
        <input value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} placeholder="Name" className="bg-slate-800 px-2 py-1 rounded w-32"/>
        <input type="color" value={draft.color} onChange={e => setDraft({ ...draft, color: e.target.value })} className="h-8 w-8 rounded"/>
        <input value={draft.user_id} onChange={e => setDraft({ ...draft, user_id: e.target.value })} placeholder="username (optional)" className="bg-slate-800 px-2 py-1 rounded w-40"/>
        <input type="number" value={draft.sort_order} onChange={e => setDraft({ ...draft, sort_order: parseInt(e.target.value || "0") })} className="bg-slate-800 px-2 py-1 rounded w-16" placeholder="order"/>
        <button onClick={add} className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded flex items-center gap-1">
          <Plus size={14}/> Add kid
        </button>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400 border-b border-slate-800">
            <th className="py-1 px-2">Name</th>
            <th className="py-1 px-2">Color</th>
            <th className="py-1 px-2">User</th>
            <th className="py-1 px-2">Notify 9am</th>
            <th className="py-1 px-2">Active</th>
            <th className="py-1 px-2"></th>
          </tr>
        </thead>
        <tbody>
          {kids.map(k => (
            <KidRow key={k.id} kid={k} onSave={(fields) => save(k, fields)} onRemove={() => remove(k)} editing={editing === k.id} setEditing={(v) => setEditing(v ? k.id : null)} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KidRow({ kid, onSave, onRemove, editing, setEditing }) {
  const [draft, setDraft] = useState(kid);
  useEffect(() => { setDraft(kid); }, [kid]);

  if (!editing) {
    return (
      <tr className="border-b border-slate-900">
        <td className="py-1 px-2" style={{ color: kid.color }}>{kid.name}</td>
        <td className="py-1 px-2"><span className="inline-block w-4 h-4 rounded" style={{ backgroundColor: kid.color }} /> {kid.color}</td>
        <td className="py-1 px-2">{kid.user_id || <span className="text-slate-600">—</span>}</td>
        <td className="py-1 px-2">{kid.notify_morning ? "✓" : "—"}</td>
        <td className="py-1 px-2">{kid.active ? "✓" : <span className="text-slate-500">inactive</span>}</td>
        <td className="py-1 px-2 flex gap-1 justify-end">
          <button onClick={() => setEditing(true)} className="p-1 hover:bg-slate-800 rounded"><Pencil size={12}/></button>
          <button onClick={onRemove} className="p-1 hover:bg-slate-800 text-red-400 rounded"><Trash2 size={12}/></button>
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-slate-900 bg-slate-900/50">
      <td className="py-1 px-2"><input value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} className="bg-slate-800 px-2 py-1 rounded w-full"/></td>
      <td className="py-1 px-2"><input type="color" value={draft.color} onChange={e => setDraft({ ...draft, color: e.target.value })} className="h-7 w-7"/></td>
      <td className="py-1 px-2"><input value={draft.user_id || ""} onChange={e => setDraft({ ...draft, user_id: e.target.value })} className="bg-slate-800 px-2 py-1 rounded w-full"/></td>
      <td className="py-1 px-2"><input type="checkbox" checked={!!draft.notify_morning} onChange={e => setDraft({ ...draft, notify_morning: e.target.checked })}/></td>
      <td className="py-1 px-2"><input type="checkbox" checked={!!draft.active} onChange={e => setDraft({ ...draft, active: e.target.checked })}/></td>
      <td className="py-1 px-2 flex gap-1 justify-end">
        <button onClick={() => onSave(draft)} className="px-2 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs">Save</button>
        <button onClick={() => setEditing(false)} className="p-1 hover:bg-slate-800 rounded"><X size={12}/></button>
      </td>
    </tr>
  );
}

// --- Zones ----

function ManageZones({ userId, refreshKey }) {
  const [zones, setZones] = useState([]);
  const [kids, setKids] = useState([]);
  const [openZone, setOpenZone] = useState(null);  // zone_id currently expanded
  const [newZone, setNewZone] = useState({ name: "", rotation_start: todayISO(), member_kid_ids: [] });
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [z, k] = await Promise.all([
        apiFetch("/zones"),
        apiFetch("/kids"),
      ]);
      setZones(z.zones);
      setKids(k.kids);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const addZone = async () => {
    if (!newZone.name.trim()) return;
    try {
      await apiFetch("/zones", {
        method: "POST",
        body: JSON.stringify({ ...newZone, acted_by: userId }),
      });
      setNewZone({ name: "", rotation_start: todayISO(), member_kid_ids: [] });
      load();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const removeZone = async (zone) => {
    if (!confirm(`Delete zone "${zone.name}" and all its chores?`)) return;
    try {
      await apiFetch(`/zones/${zone.id}?acted_by=${encodeURIComponent(userId)}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="space-y-2">
      {error && <div className="text-red-400 text-sm">{error}</div>}

      <div className="bg-slate-900 border border-slate-800 rounded p-2 flex flex-wrap gap-2 items-end text-sm">
        <input value={newZone.name} onChange={e => setNewZone({ ...newZone, name: e.target.value })} placeholder="Zone name" className="bg-slate-800 px-2 py-1 rounded w-40"/>
        <input type="date" value={newZone.rotation_start} onChange={e => setNewZone({ ...newZone, rotation_start: e.target.value })} className="bg-slate-800 px-2 py-1 rounded"/>
        <select
          multiple
          value={newZone.member_kid_ids}
          onChange={e => setNewZone({ ...newZone, member_kid_ids: Array.from(e.target.selectedOptions).map(o => o.value) })}
          className="bg-slate-800 px-2 py-1 rounded text-xs"
        >
          {kids.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
        </select>
        <button onClick={addZone} className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded flex items-center gap-1">
          <Plus size={14}/> Add zone
        </button>
      </div>

      <div className="space-y-2">
        {zones.map(z => (
          <ZoneCard
            key={z.id}
            zone={z}
            kids={kids}
            userId={userId}
            expanded={openZone === z.id}
            setExpanded={(v) => setOpenZone(v ? z.id : null)}
            onChange={load}
            onRemove={() => removeZone(z)}
          />
        ))}
      </div>
    </div>
  );
}

function ZoneCard({ zone, kids, userId, expanded, setExpanded, onChange, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({
    name: zone.name,
    rotation_start: zone.rotation_start,
    member_kid_ids: zone.members.map(m => m.kid_id),
  });
  const [chores, setChores] = useState([]);
  const [error, setError] = useState("");

  const loadChores = useCallback(async () => {
    try {
      const v = await apiFetch(`/chores?zone_id=${zone.id}&include_inactive=true`);
      setChores(v.chores);
    } catch (e) {
      setError(String(e.message || e));
    }
  }, [zone.id]);

  useEffect(() => { if (expanded) loadChores(); }, [expanded, loadChores]);

  const saveZone = async () => {
    try {
      await apiFetch(`/zones/${zone.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...draft, acted_by: userId }),
      });
      setEditing(false);
      onChange();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const addChoreSlot = async (dow) => {
    const name = prompt(`New chore for ${DOW_LONG[dow]} (in ${zone.name}):`);
    if (!name) return;
    const note = prompt("Optional note:", "") || "";
    try {
      await apiFetch(`/chores`, {
        method: "POST",
        body: JSON.stringify({ zone_id: zone.id, dow, name, note, acted_by: userId }),
      });
      loadChores();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const editChore = async (chore) => {
    const name = prompt("Chore name:", chore.name);
    if (name === null) return;
    const note = prompt("Note:", chore.note);
    if (note === null) return;
    try {
      await apiFetch(`/chores/${chore.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, note, acted_by: userId }),
      });
      loadChores();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const deleteChore = async (chore) => {
    if (!confirm(`Remove chore "${chore.name}"? (Soft delete)`)) return;
    try {
      await apiFetch(`/chores/${chore.id}?acted_by=${encodeURIComponent(userId)}`, { method: "DELETE" });
      loadChores();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const memberNames = zone.members.map(m => m.kid_name).join(" → ");

  return (
    <div className="bg-slate-900 border border-slate-800 rounded">
      <div className="flex items-center gap-2 p-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-sm font-semibold flex-1 text-left hover:text-indigo-300"
        >
          {zone.name}
          <span className="text-xs text-slate-500 ml-2">
            ({memberNames || "no members"}) · {zone.chore_count} chore(s)
          </span>
        </button>
        <button onClick={() => setEditing(!editing)} className="p-1 hover:bg-slate-800 rounded"><Pencil size={12}/></button>
        <button onClick={onRemove} className="p-1 hover:bg-slate-800 text-red-400 rounded"><Trash2 size={12}/></button>
      </div>

      {editing && (
        <div className="bg-slate-950 border-t border-slate-800 p-2 flex flex-wrap gap-2 items-end text-sm">
          <input value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} className="bg-slate-800 px-2 py-1 rounded"/>
          <label className="text-xs text-slate-400 flex flex-col gap-1">
            rotation_start
            <input type="date" value={draft.rotation_start} onChange={e => setDraft({ ...draft, rotation_start: e.target.value })} className="bg-slate-800 px-2 py-1 rounded"/>
          </label>
          <label className="text-xs text-slate-400 flex flex-col gap-1">
            members (ordered)
            <select
              multiple
              value={draft.member_kid_ids}
              onChange={e => setDraft({ ...draft, member_kid_ids: Array.from(e.target.selectedOptions).map(o => o.value) })}
              className="bg-slate-800 px-2 py-1 rounded text-xs"
            >
              {kids.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select>
          </label>
          <button onClick={saveZone} className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded">Save</button>
          <button onClick={() => setEditing(false)} className="p-1 hover:bg-slate-800 rounded"><X size={12}/></button>
        </div>
      )}

      {expanded && (
        <div className="bg-slate-950 border-t border-slate-800 p-2">
          {error && <div className="text-red-400 text-xs mb-2">{error}</div>}
          {DOW_NAMES.map((d, dow) => {
            const dayChores = chores.filter(c => c.dow === dow).sort((a, b) => a.position - b.position);
            return (
              <div key={dow} className="flex items-start gap-2 text-sm border-b border-slate-900 py-1">
                <div className="w-12 shrink-0 text-xs text-slate-400 pt-1">{d}</div>
                <div className="flex-1">
                  {dayChores.length === 0
                    ? <span className="text-slate-600 text-xs">—</span>
                    : dayChores.map(c => (
                        <div key={c.id} className="flex items-center gap-2 text-xs py-0.5">
                          <span className={c.active ? "" : "text-slate-500 line-through"}>
                            [{c.position}] {c.name}
                          </span>
                          {c.note && <span className="text-slate-500">— {c.note}</span>}
                          <button onClick={() => editChore(c)} className="p-0.5 hover:bg-slate-800 rounded"><Pencil size={10}/></button>
                          <button onClick={() => deleteChore(c)} className="p-0.5 hover:bg-slate-800 text-red-400 rounded"><Trash2 size={10}/></button>
                        </div>
                      ))}
                </div>
                <button onClick={() => addChoreSlot(dow)} className="p-1 hover:bg-slate-800 rounded text-xs flex items-center gap-1 text-slate-400">
                  <Plus size={11}/>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
