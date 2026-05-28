import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search, Plus, Settings, Printer, Loader2, Trash2, Edit3, Save, X,
  ChevronDown, ChevronRight, Check, AlertTriangle,
} from "lucide-react";

/**
 * Homeopathy App — Track homeopathic remedy inventory
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 */

const API = "/api/apps/homeopathy";

const FULLNESS_OPTIONS = [0, 25, 33, 50, 67, 75, 100];
const FULLNESS_LABELS = { 0: "Empty", 25: "1/4", 33: "1/3", 50: "1/2", 67: "2/3", 75: "3/4", 100: "Full" };
const FULLNESS_COLORS = {
  0: "text-red-400", 25: "text-orange-400", 33: "text-orange-400",
  50: "text-yellow-400", 67: "text-emerald-400", 75: "text-emerald-400", 100: "text-emerald-400",
};

function fullnessLabel(v) { return FULLNESS_LABELS[v] || `${v}%`; }
function fullnessColor(v) { return FULLNESS_COLORS[v] || "text-gray-400"; }

function timeAgo(dateStr) {
  if (!dateStr) return "never";
  // Compare calendar dates (last_checked is a DATE, not a timestamp)
  const parts = dateStr.split("T")[0].split("-");
  const checked = new Date(+parts[0], +parts[1] - 1, +parts[2]);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today - checked) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  const months = Math.floor(days / 30.44);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(days / 365.25);
  return `${years}y ago`;
}

// ═══════════════════════════════════════════════════════════════════════════
//  Main App
// ═══════════════════════════════════════════════════════════════════════════

export default function HomeopathyApp({ appId, userId, onTitle, refreshKey }) {
  const [view, setView] = useState("inventory"); // inventory | manage
  const [bottles, setBottles] = useState([]);
  const [sources, setSources] = useState([]);
  const [medicines, setMedicines] = useState([]);
  const [remedies, setRemedies] = useState([]);
  const [sizes, setSizes] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [strengthFilter, setStrengthFilter] = useState("");

  useEffect(() => { if (onTitle) onTitle("Homeopathy"); }, [onTitle]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [bRes, srcRes, medRes, remRes, szRes, locRes] = await Promise.all([
        fetch(`${API}/bottles`).then(r => r.json()),
        fetch(`${API}/sources`).then(r => r.json()),
        fetch(`${API}/medicines`).then(r => r.json()),
        fetch(`${API}/remedies`).then(r => r.json()),
        fetch(`${API}/sizes`).then(r => r.json()),
        fetch(`${API}/locations`).then(r => r.json()),
      ]);
      setBottles(bRes.bottles || []);
      setSources(srcRes.sources || []);
      setMedicines(medRes.medicines || []);
      setRemedies(remRes.remedies || []);
      setSizes(szRes.sizes || []);
      setLocations(locRes.locations || []);
    } catch (e) { console.error("Load error:", e); }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (loading) {
    return <div className="flex items-center justify-center h-full"><Loader2 className="animate-spin text-rose-400" size={32} /></div>;
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-700/50 print:hidden">
        <div className="relative flex-1 min-w-[180px]">
          <Search size={16} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            className="w-full pl-8 pr-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-gray-200 placeholder-gray-500"
            placeholder="Search..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300"
          value={strengthFilter}
          onChange={e => setStrengthFilter(e.target.value)}
        >
          <option value="">All Strengths</option>
          {[...new Set(bottles.map(b => b.strength))].sort().map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
          <input type="checkbox" checked={lowOnly} onChange={e => setLowOnly(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800 text-rose-500 focus:ring-rose-500" />
          Low only
        </label>
        <div className="flex-1" />
        <button onClick={() => setView(v => v === "manage" ? "inventory" : "manage")}
          className={`p-1.5 rounded hover:bg-gray-700 ${view === "manage" ? "text-rose-400 bg-gray-700" : "text-gray-400"}`}
          title="Manage reference data">
          <Settings size={18} />
        </button>
        <button onClick={() => window.print()}
          className="p-1.5 rounded hover:bg-gray-700 text-gray-400" title="Print inventory">
          <Printer size={18} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto p-4">
        {view === "manage" ? (
          <ManagePanel
            sources={sources} medicines={medicines} remedies={remedies}
            sizes={sizes} locations={locations} onRefresh={load}
          />
        ) : (
          <InventoryView
            bottles={bottles} search={search} lowOnly={lowOnly}
            strengthFilter={strengthFilter} remedies={remedies}
            sizes={sizes} locations={locations} onRefresh={load}
          />
        )}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Inventory View — grouped by strength
// ═══════════════════════════════════════════════════════════════════════════

function InventoryView({ bottles, search, lowOnly, strengthFilter, remedies, sizes, locations, onRefresh }) {
  const [expandedMed, setExpandedMed] = useState(null);
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [showAdd, setShowAdd] = useState(false);

  // Filter
  let filtered = bottles;
  if (search.trim()) {
    const q = search.toLowerCase();
    filtered = filtered.filter(b =>
      b.medicine_name?.toLowerCase().includes(q) ||
      b.strength?.toLowerCase().includes(q) ||
      b.size_name?.toLowerCase().includes(q) ||
      b.location_name?.toLowerCase().includes(q) ||
      b.notes?.toLowerCase().includes(q)
    );
  }
  if (lowOnly) filtered = filtered.filter(b => b.fullness <= 25);
  if (strengthFilter) filtered = filtered.filter(b => b.strength === strengthFilter);

  // Group by strength, then by medicine
  const groups = {};
  for (const b of filtered) {
    const s = b.strength || "?";
    if (!groups[s]) groups[s] = {};
    const m = b.medicine_name || "?";
    if (!groups[s][m]) groups[s][m] = [];
    groups[s][m].push(b);
  }

  const sortedStrengths = Object.keys(groups).sort(strengthSortKey);

  const startEdit = (bot) => {
    setEditId(bot.id);
    setEditForm({ fullness: bot.fullness, location_id: bot.location_id, size_id: bot.size_id, notes: bot.notes });
  };

  const saveEdit = async () => {
    await fetch(`${API}/bottles/${editId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editForm),
    });
    setEditId(null);
    onRefresh();
  };

  const deleteBottle = async (id) => {
    if (!confirm("Delete this bottle?")) return;
    await fetch(`${API}/bottles/${id}`, { method: "DELETE" });
    onRefresh();
  };

  const quickCheck = async (id, fullness) => {
    await fetch(`${API}/bottles/${id}/check`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fullness }),
    });
    onRefresh();
  };

  if (filtered.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 text-base mb-4">
          {bottles.length === 0 ? "No bottles in inventory yet." : "No bottles match your filters."}
        </p>
        <button onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded bg-rose-600 hover:bg-rose-500 text-white">
          <Plus size={16} /> Add First Bottle
        </button>
        {showAdd && <AddBottleModal remedies={remedies} sizes={sizes} locations={locations}
          onClose={() => setShowAdd(false)} onSave={onRefresh} />}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Add button */}
      <div className="flex justify-end print:hidden">
        <button onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded bg-rose-600 hover:bg-rose-500 text-white">
          <Plus size={16} /> Add Bottle
        </button>
      </div>

      {sortedStrengths.map(strength => (
        <div key={strength}>
          <h3 className="text-base font-bold text-rose-400 border-b border-rose-500/30 pb-1 mb-2">{strength}</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-left">
                <th className="pb-1 pr-2 font-medium w-1/4">Medicine</th>
                <th className="pb-1 pr-2 font-medium w-1/3">Size & Location</th>
                <th className="pb-1 pr-2 font-medium">Amount</th>
                <th className="pb-1 font-medium">Checked</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(groups[strength]).sort().map(medName => {
                const bots = groups[strength][medName];
                const hasLow = bots.some(b => b.fullness <= 25);
                const isExpanded = expandedMed === `${strength}:${medName}`;
                const rowKey = `${strength}:${medName}`;

                return (
                  <tr key={rowKey}
                    className={`border-t border-gray-700/40 align-top cursor-pointer hover:bg-gray-800/50 ${hasLow ? "bg-red-900/10" : ""}`}
                    onClick={() => setExpandedMed(isExpanded ? null : rowKey)}
                  >
                    <td className="py-1.5 pr-2">
                      <span className="flex items-center gap-1">
                        {isExpanded ? <ChevronDown size={14} className="text-gray-500 print:hidden" /> : <ChevronRight size={14} className="text-gray-500 print:hidden" />}
                        <span className="font-medium text-gray-200">{medName}</span>
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-gray-400">
                      {bots.map((b, i) => (
                        <div key={b.id} className="leading-snug">
                          {b.size_name || "?"} ({b.location_name || "?"})
                          {i < bots.length - 1 ? ";" : ""}
                          {/* Expanded: show edit controls */}
                          {isExpanded && (
                            <div className="mt-1 mb-2 ml-1 flex items-center gap-1 print:hidden">
                              {editId === b.id ? (
                                <div className="flex flex-wrap items-center gap-1" onClick={e => e.stopPropagation()}>
                                  <select value={editForm.fullness} onChange={e => setEditForm(f => ({ ...f, fullness: +e.target.value }))}
                                    className="text-sm bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200">
                                    {FULLNESS_OPTIONS.map(v => <option key={v} value={v}>{fullnessLabel(v)}</option>)}
                                  </select>
                                  <select value={editForm.location_id || ""} onChange={e => setEditForm(f => ({ ...f, location_id: e.target.value }))}
                                    className="text-sm bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200">
                                    <option value="">No location</option>
                                    {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                                  </select>
                                  <select value={editForm.size_id || ""} onChange={e => setEditForm(f => ({ ...f, size_id: e.target.value }))}
                                    className="text-sm bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200">
                                    <option value="">No size</option>
                                    {sizes.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                                  </select>
                                  <button onClick={(e) => { e.stopPropagation(); saveEdit(); }}
                                    className="p-1 rounded hover:bg-emerald-700 text-emerald-400"><Save size={14} /></button>
                                  <button onClick={(e) => { e.stopPropagation(); setEditId(null); }}
                                    className="p-1 rounded hover:bg-gray-600 text-gray-400"><X size={14} /></button>
                                </div>
                              ) : (
                                <div className="flex items-center gap-1">
                                  {/* Quick-check buttons */}
                                  {FULLNESS_OPTIONS.map(v => (
                                    <button key={v} onClick={(e) => { e.stopPropagation(); quickCheck(b.id, v); }}
                                      className={`px-1.5 py-1 rounded text-xs border ${
                                        b.fullness === v ? "border-rose-500 bg-rose-600/20 text-rose-300" : "border-gray-600 hover:border-gray-500 text-gray-400"
                                      }`}>
                                      {fullnessLabel(v)}
                                    </button>
                                  ))}
                                  <button onClick={(e) => { e.stopPropagation(); startEdit(b); }}
                                    className="p-1 rounded hover:bg-gray-600 text-gray-400 ml-1"><Edit3 size={14} /></button>
                                  <button onClick={(e) => { e.stopPropagation(); deleteBottle(b.id); }}
                                    className="p-1 rounded hover:bg-red-700 text-gray-500 hover:text-red-300"><Trash2 size={14} /></button>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </td>
                    <td className="py-1.5 pr-2">
                      {bots.map((b, i) => (
                        <div key={b.id} className={`leading-snug font-medium ${fullnessColor(b.fullness)}`}>
                          {fullnessLabel(b.fullness)}{i < bots.length - 1 ? ";" : ""}
                        </div>
                      ))}
                    </td>
                    <td className="py-1.5 text-gray-500">
                      {bots.map((b, i) => (
                        <div key={b.id} className="leading-snug">
                          {timeAgo(b.last_checked)}
                        </div>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}

      {showAdd && <AddBottleModal remedies={remedies} sizes={sizes} locations={locations}
        onClose={() => setShowAdd(false)} onSave={onRefresh} />}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Add Bottle Modal
// ═══════════════════════════════════════════════════════════════════════════

function AddBottleModal({ remedies, sizes, locations, onClose, onSave }) {
  const [form, setForm] = useState({ remedy_id: "", size_id: "", location_id: "", fullness: 100, notes: "" });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.remedy_id) return;
    setSaving(true);
    await fetch(`${API}/bottles`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        remedy_id: form.remedy_id,
        size_id: form.size_id || null,
        location_id: form.location_id || null,
        fullness: form.fullness,
        notes: form.notes,
        last_checked: new Date().toISOString().slice(0, 10),
      }),
    });
    setSaving(false);
    onClose();
    onSave();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-80 space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Add Bottle</h3>
        <div>
          <label className="block text-xs text-gray-500 mb-0.5">Remedy</label>
          <select value={form.remedy_id} onChange={e => setForm(f => ({ ...f, remedy_id: e.target.value }))}
            className="w-full text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200">
            <option value="">Select remedy...</option>
            {remedies.map(r => (
              <option key={r.id} value={r.id}>{r.medicine_name} {r.strength}</option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-0.5">Size</label>
            <select value={form.size_id} onChange={e => setForm(f => ({ ...f, size_id: e.target.value }))}
              className="w-full text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200">
              <option value="">None</option>
              {sizes.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-0.5">Location</label>
            <select value={form.location_id} onChange={e => setForm(f => ({ ...f, location_id: e.target.value }))}
              className="w-full text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200">
              <option value="">None</option>
              {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-0.5">Fullness</label>
          <div className="flex gap-1">
            {FULLNESS_OPTIONS.map(v => (
              <button key={v} onClick={() => setForm(f => ({ ...f, fullness: v }))}
                className={`flex-1 py-1.5 rounded text-xs border ${
                  form.fullness === v ? "border-rose-500 bg-rose-600/20 text-rose-300" : "border-gray-600 text-gray-400 hover:border-gray-500"
                }`}>
                {fullnessLabel(v)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-0.5">Notes</label>
          <input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
            className="w-full text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200" />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded bg-gray-700 text-gray-300 hover:bg-gray-600">Cancel</button>
          <button onClick={submit} disabled={!form.remedy_id || saving}
            className="px-3 py-1.5 text-sm rounded bg-rose-600 text-white hover:bg-rose-500 disabled:opacity-50">
            {saving ? "Saving..." : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Manage Panel — CRUD for reference data
// ═══════════════════════════════════════════════════════════════════════════

const MANAGE_TABS = [
  { id: "sources", label: "Sources" },
  { id: "medicines", label: "Medicines" },
  { id: "remedies", label: "Remedies" },
  { id: "sizes", label: "Bottle Sizes" },
  { id: "locations", label: "Locations" },
];

function ManagePanel({ sources, medicines, remedies, sizes, locations, onRefresh }) {
  const [tab, setTab] = useState("sources");

  return (
    <div>
      <div className="flex gap-1 mb-4 print:hidden">
        {MANAGE_TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-sm rounded-full ${
              tab === t.id ? "bg-rose-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"
            }`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "sources" && <CrudList items={sources} endpoint="sources" fields={["name", "website", "phone"]} onRefresh={onRefresh} idPrefix="hsrc" />}
      {tab === "medicines" && <CrudList items={medicines} endpoint="medicines" fields={["name", "description"]} onRefresh={onRefresh} idPrefix="hmed" />}
      {tab === "remedies" && <RemedyManager remedies={remedies} medicines={medicines} sources={sources} onRefresh={onRefresh} />}
      {tab === "sizes" && <CrudList items={sizes} endpoint="sizes" fields={["name", "sort_order"]} onRefresh={onRefresh} idPrefix="hsize" />}
      {tab === "locations" && <CrudList items={locations} endpoint="locations" fields={["name", "sort_order"]} onRefresh={onRefresh} idPrefix="hloc" />}
    </div>
  );
}


// Generic CRUD list for simple entities (sources, medicines, sizes, locations)
function CrudList({ items, endpoint, fields, onRefresh, idPrefix }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({});
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});

  const startAdd = () => { setAdding(true); setForm(Object.fromEntries(fields.map(f => [f, ""]))); };

  const saveAdd = async () => {
    const body = { ...form };
    if (body.sort_order !== undefined) body.sort_order = parseInt(body.sort_order) || 0;
    await fetch(`${API}/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    setAdding(false);
    onRefresh();
  };

  const startEdit = (item) => {
    setEditId(item.id);
    setEditForm(Object.fromEntries(fields.map(f => [f, item[f] ?? ""])));
  };

  const saveEdit = async () => {
    const body = { ...editForm };
    if (body.sort_order !== undefined) body.sort_order = parseInt(body.sort_order) || 0;
    await fetch(`${API}/${endpoint}/${editId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    setEditId(null);
    onRefresh();
  };

  const remove = async (id) => {
    if (!confirm("Delete this item?")) return;
    await fetch(`${API}/${endpoint}/${id}`, { method: "DELETE" });
    onRefresh();
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button onClick={startAdd} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-rose-600 text-white hover:bg-rose-500">
          <Plus size={14} /> Add
        </button>
      </div>
      {adding && (
        <div className="flex items-center gap-1 bg-gray-800/50 p-2 rounded border border-gray-700">
          {fields.map(f => (
            <input key={f} placeholder={f} value={form[f] ?? ""}
              onChange={e => setForm(prev => ({ ...prev, [f]: e.target.value }))}
              className="text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200 flex-1" />
          ))}
          <button onClick={saveAdd} className="p-1 rounded hover:bg-emerald-700 text-emerald-400"><Save size={16} /></button>
          <button onClick={() => setAdding(false)} className="p-1 rounded hover:bg-gray-600 text-gray-400"><X size={16} /></button>
        </div>
      )}
      {items.length === 0 && !adding && <p className="text-gray-500 text-sm text-center py-4">None yet.</p>}
      {items.map(item => (
        <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800/50 group border border-transparent hover:border-gray-700/50">
          {editId === item.id ? (
            <>
              {fields.map(f => (
                <input key={f} value={editForm[f] ?? ""}
                  onChange={e => setEditForm(prev => ({ ...prev, [f]: e.target.value }))}
                  className="text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200 flex-1" />
              ))}
              <button onClick={saveEdit} className="p-1 rounded hover:bg-emerald-700 text-emerald-400"><Save size={16} /></button>
              <button onClick={() => setEditId(null)} className="p-1 rounded hover:bg-gray-600 text-gray-400"><X size={16} /></button>
            </>
          ) : (
            <>
              <span className="text-sm text-gray-200 flex-1">{fields.map(f => item[f]).filter(Boolean).join(" — ")}</span>
              <button onClick={() => startEdit(item)} className="p-1 rounded hover:bg-gray-600 text-gray-400 opacity-0 group-hover:opacity-100"><Edit3 size={14} /></button>
              <button onClick={() => remove(item.id)} className="p-1 rounded hover:bg-red-700 text-gray-500 hover:text-red-300 opacity-0 group-hover:opacity-100"><Trash2 size={14} /></button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}


// Remedy manager — needs medicine and source dropdowns
function RemedyManager({ remedies, medicines, sources, onRefresh }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ medicine_id: "", strength: "", source_id: "" });

  const saveAdd = async () => {
    if (!form.medicine_id || !form.strength) return;
    await fetch(`${API}/remedies`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setAdding(false);
    onRefresh();
  };

  const remove = async (id) => {
    if (!confirm("Delete this remedy? This will also delete all bottles for it.")) return;
    await fetch(`${API}/remedies/${id}`, { method: "DELETE" });
    onRefresh();
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-rose-600 text-white hover:bg-rose-500">
          <Plus size={14} /> Add
        </button>
      </div>
      {adding && (
        <div className="flex items-center gap-1 bg-gray-800/50 p-2 rounded border border-gray-700">
          <select value={form.medicine_id} onChange={e => setForm(f => ({ ...f, medicine_id: e.target.value }))}
            className="text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200 flex-1">
            <option value="">Medicine...</option>
            {medicines.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <input placeholder="Strength" value={form.strength}
            onChange={e => setForm(f => ({ ...f, strength: e.target.value }))}
            className="text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200 w-24" />
          <select value={form.source_id} onChange={e => setForm(f => ({ ...f, source_id: e.target.value }))}
            className="text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200 flex-1">
            <option value="">Source...</option>
            {sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={saveAdd} className="p-1 rounded hover:bg-emerald-700 text-emerald-400"><Save size={14} /></button>
          <button onClick={() => setAdding(false)} className="p-1 rounded hover:bg-gray-600 text-gray-400"><X size={14} /></button>
        </div>
      )}
      {remedies.length === 0 && !adding && <p className="text-gray-500 text-sm text-center py-4">No remedies yet. Add medicines and sources first.</p>}
      {remedies.map(r => (
        <div key={r.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800/50 group border border-transparent hover:border-gray-700/50">
          <span className="text-sm text-gray-200 flex-1">
            <span className="font-medium">{r.medicine_name}</span> {r.strength}
            {r.source_name ? <span className="text-gray-500"> — {r.source_name}</span> : ""}
          </span>
          <button onClick={() => remove(r.id)} className="p-1 rounded hover:bg-red-700 text-gray-500 hover:text-red-300 opacity-0 group-hover:opacity-100"><Trash2 size={14} /></button>
        </div>
      ))}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════════════════════════

function strengthSortKey(a, b) {
  return _strengthVal(a) - _strengthVal(b);
}

function _strengthVal(s) {
  const u = s.toUpperCase().trim();
  if (u.endsWith("M")) { const n = parseInt(u); return isNaN(n) ? 3000 : -n * 100; }
  if (u.endsWith("C")) { const n = parseInt(u); return isNaN(n) ? 2000 : 1000 - n; }
  if (u.endsWith("X")) { const n = parseInt(u); return isNaN(n) ? 4000 : 2000 - n; }
  return 5000;
}
