import { useState, useEffect, useCallback } from "react";
import {
  Search, Plus, Settings, Loader2, Trash2, Edit3, Save, X,
  ChevronDown, ChevronRight, FlaskConical, Pill, Activity, Syringe, CalendarClock, Bell, BellOff,
  Wrench, CheckCircle2, History, AlertTriangle,
} from "lucide-react";

/**
 * Medical App — Medications, Treatments, Events, Labs
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 */

const API = "/api/apps/medical";

// ─── Helpers ────────────────────────────────────────────────────────────────

function daysFromToday(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + "T00:00:00");
  const today = new Date(); today.setHours(0,0,0,0);
  return Math.round((d - today) / 86400000);
}

function fmtDate(dateStr) {
  if (!dateStr) return "";
  const [y, m, d] = dateStr.split("T")[0].split("-");
  return `${m}/${d}/${y}`;
}

function daysLabel(days) {
  if (days === null) return "";
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "today";
  return `in ${days}d`;
}

function statusDot(days) {
  if (days === null) return "⚫";
  if (days < 0) return "🔴";
  if (days <= 7) return "🟡";
  return "🟢";
}

function intervalLabel(days) {
  if (!days) return "";
  if (days === 1) return "daily";
  if (days === 7) return "weekly";
  if (days === 14) return "every 2 wks";
  if (days === 30) return "monthly";
  if (days === 60) return "every 2 mo";
  if (days === 90) return "quarterly";
  if (days === 180) return "every 6 mo";
  if (days === 365) return "yearly";
  return `every ${days}d`;
}

// ─── Shared UI components ───────────────────────────────────────────────────

function ConfirmModal({ message, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 w-80 space-y-4" onClick={e => e.stopPropagation()}>
        <p className="text-sm text-gray-200">{message}</p>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm rounded bg-gray-700 text-gray-300 hover:bg-gray-600">Cancel</button>
          <button onClick={onConfirm} className="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-500">Delete</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-0.5">{label}</label>
      {children}
    </div>
  );
}

const inp = "w-full text-sm bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-gray-200 focus:outline-none focus:border-teal-500";
const btnPrimary = "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-50";
const btnSecondary = "px-3 py-1.5 text-sm rounded bg-gray-700 text-gray-300 hover:bg-gray-600";
const btnDanger = "px-3 py-1.5 text-sm rounded bg-red-700 text-white hover:bg-red-600";

// ═══════════════════════════════════════════════════════════════════════════
//  Main App
// ═══════════════════════════════════════════════════════════════════════════

function defaultMemberForUser(members, userId) {
  return members.find(m => m.name.toLowerCase() === (userId || "").toLowerCase())?.id || members[0]?.id || "";
}

const TABS = [
  { id: "medications",  label: "Medications",  Icon: Pill },
  { id: "treatments",   label: "Treatments",   Icon: Syringe },
  { id: "events",       label: "Events",       Icon: Activity },
  { id: "labs",         label: "Labs",         Icon: FlaskConical },
  { id: "appointments", label: "Appointments", Icon: CalendarClock },
  { id: "equipment",    label: "Equipment",    Icon: Wrench },
];

export default function MedicalApp({ appId, userId, onTitle, refreshKey }) {
  const [tab, setTab] = useState("medications");
  const [members, setMembers] = useState([]);
  const [memberId, setMemberId] = useState("");
  const [refreshCtr, setRefreshCtr] = useState(0);

  useEffect(() => { if (onTitle) onTitle("Medical"); }, [onTitle]);

  const loadMembers = useCallback(async () => {
    try {
      const res = await fetch(`${API}/members`);
      const data = await res.json();
      const ms = data.members || [];
      setMembers(ms);
      setMemberId(prev => prev || ms.find(m => m.name.toLowerCase() === (userId || "").toLowerCase())?.id || "");
    } catch (e) { console.error("Failed to load members", e); }
  }, [userId]);

  useEffect(() => { loadMembers(); }, [loadMembers, refreshKey]);

  const refresh = () => setRefreshCtr(c => c + 1);

  return (
    <div className="flex flex-col h-full w-full bg-gray-900 text-gray-200">
      {/* Header bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700/60 shrink-0">
        {/* Member filter */}
        <select
          value={memberId}
          onChange={e => setMemberId(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300 min-w-[140px]"
        >
          <option value="">All Members</option>
          {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        {/* Tabs */}
        <div className="flex gap-0.5 flex-1">
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded transition-colors ${
                tab === id
                  ? "bg-teal-600 text-white"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              }`}>
              <Icon size={14} />{label}
            </button>
          ))}
        </div>
        {/* Manage members */}
        <button onClick={() => setTab("_members")}
          className={`p-1.5 rounded hover:bg-gray-700 ${tab === "_members" ? "text-teal-400 bg-gray-700" : "text-gray-500"}`}
          title="Manage members">
          <Settings size={16} />
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {tab === "medications"  && <MedicationsTab  memberId={memberId} userId={userId} refreshKey={refreshCtr} onMembersChange={loadMembers} />}
        {tab === "treatments"   && <TreatmentsTab   memberId={memberId} userId={userId} refreshKey={refreshCtr} />}
        {tab === "events"       && <EventsTab       memberId={memberId} userId={userId} refreshKey={refreshCtr} />}
        {tab === "labs"         && <LabsTab         memberId={memberId} userId={userId} refreshKey={refreshCtr} />}
        {tab === "appointments" && <AppointmentsTab memberId={memberId} userId={userId} refreshKey={refreshCtr} />}
        {tab === "equipment"    && <EquipmentTab    memberId={memberId} userId={userId} refreshKey={refreshCtr} />}
        {tab === "_members"     && <MembersPanel    members={members}   onRefresh={() => { loadMembers(); refresh(); }} />}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Members Panel
// ═══════════════════════════════════════════════════════════════════════════

function MembersPanel({ members, onRefresh }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", notes: "" });
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [confirm, setConfirm] = useState(null);

  const saveAdd = async () => {
    if (!form.name.trim()) return;
    await fetch(`${API}/members`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    setAdding(false); setForm({ name: "", notes: "" }); onRefresh();
  };
  const saveEdit = async () => {
    await fetch(`${API}/members/${editId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(editForm) });
    setEditId(null); onRefresh();
  };
  const doDelete = async (id) => {
    await fetch(`${API}/members/${id}`, { method: "DELETE" });
    setConfirm(null); onRefresh();
  };

  return (
    <div className="p-4 max-w-lg space-y-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-300">Family Members</h3>
        <button onClick={() => setAdding(true)} className={btnPrimary}><Plus size={14} />Add</button>
      </div>
      {adding && (
        <div className="flex gap-2 p-2 bg-gray-800/60 rounded border border-gray-700">
          <input placeholder="Name" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className={inp + " flex-1"} />
          <input placeholder="Notes" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} className={inp + " flex-1"} />
          <button onClick={saveAdd} className="p-1 text-emerald-400 hover:bg-emerald-900/40 rounded"><Save size={16} /></button>
          <button onClick={() => setAdding(false)} className="p-1 text-gray-500 hover:bg-gray-700 rounded"><X size={16} /></button>
        </div>
      )}
      {members.map(m => (
        <div key={m.id} className="flex items-center gap-2 p-2 bg-gray-800/40 rounded border border-gray-700/50 group">
          {editId === m.id ? (
            <>
              <input value={editForm.name || ""} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} className={inp + " flex-1"} />
              <input value={editForm.notes || ""} onChange={e => setEditForm(f => ({ ...f, notes: e.target.value }))} className={inp + " flex-1"} />
              <button onClick={saveEdit} className="p-1 text-emerald-400 hover:bg-emerald-900/40 rounded"><Save size={16} /></button>
              <button onClick={() => setEditId(null)} className="p-1 text-gray-500 hover:bg-gray-700 rounded"><X size={16} /></button>
            </>
          ) : (
            <>
              <span className="font-medium text-gray-200 flex-1">{m.name}</span>
              <span className="text-gray-500 text-sm flex-1">{m.notes}</span>
              <button onClick={() => { setEditId(m.id); setEditForm({ name: m.name, notes: m.notes }); }} className="p-1 text-gray-500 hover:text-gray-300 hover:bg-gray-700 rounded opacity-0 group-hover:opacity-100"><Edit3 size={14} /></button>
              <button onClick={() => setConfirm(m.id)} className="p-1 text-gray-500 hover:text-red-400 hover:bg-red-900/30 rounded opacity-0 group-hover:opacity-100"><Trash2 size={14} /></button>
            </>
          )}
        </div>
      ))}
      {confirm && <ConfirmModal message="Delete this member? All their medical records will be deleted." onConfirm={() => doDelete(confirm)} onCancel={() => setConfirm(null)} />}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Medications Tab
// ═══════════════════════════════════════════════════════════════════════════

const REFILL_BADGE = {
  active:   { cls: "bg-emerald-900/40 text-emerald-400 border-emerald-700/50", label: "On Track" },
  nagging:  { cls: "bg-yellow-900/40 text-yellow-400 border-yellow-700/50",   label: "Refill Soon" },
  ordered:  { cls: "bg-blue-900/40 text-blue-400 border-blue-700/50",         label: "Ordered" },
  filled:   { cls: "bg-gray-700/40 text-gray-400 border-gray-600/50",         label: "Filled" },
};

function MedicationsTab({ memberId, userId, refreshKey }) {
  const [meds, setMeds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInactive, setShowInactive] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [members, setMembers] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [mRes, mbRes] = await Promise.all([
        fetch(`${API}/medications?member_id=${memberId}&active=${!showInactive}`).then(r => r.json()),
        fetch(`${API}/members`).then(r => r.json()),
      ]);
      setMeds(mRes.medications || []);
      setMembers(mbRes.members || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [memberId, showInactive, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const memberName = (id) => members.find(m => m.id === id)?.name || "";

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-teal-400" size={24} /></div>;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800 text-teal-500" />
          Show inactive
        </label>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}><Plus size={14} />Add Medication</button>
      </div>

      {meds.length === 0 && <p className="text-gray-500 text-sm text-center py-8">No medications yet.</p>}

      <div className="space-y-2">
        {meds.map(med => {
          const days = daysFromToday(med.last_dose_date);
          const badge = REFILL_BADGE[med.refill_status] || REFILL_BADGE.active;
          const isExpanded = expandedId === med.id;
          return (
            <MedCard key={med.id} med={med} days={days} badge={badge} memberName={memberName(med.member_id)}
              isExpanded={isExpanded} onToggle={() => setExpandedId(isExpanded ? null : med.id)}
              members={members} onRefresh={load} />
          );
        })}
      </div>

      {showAdd && <AddMedModal members={members} userId={userId} defaultMemberId={defaultMemberForUser(members, userId)} onClose={() => setShowAdd(false)} onSave={load} />}
    </div>
  );
}

function MedCard({ med, days, badge, memberName, isExpanded, onToggle, members, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const startEdit = () => {
    setForm({
      name: med.name, dosage_notes: med.dosage_notes, prescriber: med.prescriber,
      pharmacy: med.pharmacy, start_date: med.start_date, last_dose_date: med.last_dose_date,
      duration_days: med.duration_days || "", reminder_days: med.reminder_days || 7,
      active: med.active, notes: med.notes,
    });
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    await fetch(`${API}/medications/${med.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    setSaving(false); setEditing(false); onRefresh();
  };

  const markOrdered = async () => {
    await fetch(`${API}/medications/${med.id}/ordered`, { method: "POST" });
    onRefresh();
  };

  const markFilled = async () => {
    await fetch(`${API}/medications/${med.id}/filled`, { method: "POST" });
    onRefresh();
  };

  const doDelete = async () => {
    await fetch(`${API}/medications/${med.id}`, { method: "DELETE" });
    setConfirm(false); onRefresh();
  };

  return (
    <div className={`rounded-lg border ${med.active ? "border-gray-700/60 bg-gray-800/30" : "border-gray-700/30 bg-gray-900/30 opacity-60"}`}>
      <div className="flex items-center gap-3 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className="text-base">{statusDot(days)}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-200 text-sm">{med.name}</span>
            {memberName && <span className="text-xs text-gray-500">{memberName}</span>}
            <span className={`text-xs px-2 py-0.5 rounded-full border ${badge.cls}`}>{badge.label}</span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {med.dosage_notes && <span className="mr-2">{med.dosage_notes}</span>}
            {med.last_dose_date && <span>runs out {fmtDate(med.last_dose_date)} ({daysLabel(days)})</span>}
          </div>
        </div>
        {med.refill_status === "nagging" && (
          <button onClick={e => { e.stopPropagation(); markOrdered(); }}
            className="text-xs px-2 py-1 rounded bg-blue-700 text-white hover:bg-blue-600 shrink-0">Mark Ordered</button>
        )}
        {med.refill_status === "ordered" && (
          <button onClick={e => { e.stopPropagation(); markFilled(); }}
            className="text-xs px-2 py-1 rounded bg-emerald-700 text-white hover:bg-emerald-600 shrink-0">Mark Filled</button>
        )}
        {isExpanded ? <ChevronDown size={14} className="text-gray-500 shrink-0" /> : <ChevronRight size={14} className="text-gray-500 shrink-0" />}
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700/40 px-3 py-3">
          {editing ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Name"><input value={form.name || ""} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} /></Field>
                <Field label="Dosage notes"><input value={form.dosage_notes || ""} onChange={e => setForm(f => ({...f, dosage_notes: e.target.value}))} className={inp} /></Field>
                <Field label="Prescriber"><input value={form.prescriber || ""} onChange={e => setForm(f => ({...f, prescriber: e.target.value}))} className={inp} /></Field>
                <Field label="Pharmacy"><input value={form.pharmacy || ""} onChange={e => setForm(f => ({...f, pharmacy: e.target.value}))} className={inp} /></Field>
                <Field label="Start date"><input type="date" value={form.start_date || ""} onChange={e => setForm(f => ({...f, start_date: e.target.value}))} className={inp} /></Field>
                <Field label="Last dose date"><input type="date" value={form.last_dose_date || ""} onChange={e => setForm(f => ({...f, last_dose_date: e.target.value}))} className={inp} /></Field>
                <Field label="Duration (days)"><input type="number" value={form.duration_days || ""} onChange={e => setForm(f => ({...f, duration_days: e.target.value ? +e.target.value : null}))} className={inp} /></Field>
                <Field label="Reminder (days before)"><input type="number" value={form.reminder_days || 7} onChange={e => setForm(f => ({...f, reminder_days: +e.target.value}))} className={inp} /></Field>
              </div>
              <Field label="Notes"><textarea value={form.notes || ""} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
                  <input type="checkbox" checked={form.active ?? true} onChange={e => setForm(f => ({...f, active: e.target.checked}))} className="rounded border-gray-600 bg-gray-800 text-teal-500" />
                  Active
                </label>
                <div className="flex-1" />
                <button onClick={() => setConfirm(true)} className={btnDanger}><Trash2 size={14} />Delete</button>
                <button onClick={() => setEditing(false)} className={btnSecondary}>Cancel</button>
                <button onClick={save} disabled={saving} className={btnPrimary}><Save size={14} />{saving ? "Saving…" : "Save"}</button>
              </div>
            </div>
          ) : (
            <div className="space-y-1 text-sm text-gray-400">
              {med.prescriber && <div>Prescriber: <span className="text-gray-300">{med.prescriber}</span></div>}
              {med.pharmacy && <div>Pharmacy: <span className="text-gray-300">{med.pharmacy}</span></div>}
              {med.duration_days && <div>Supply: <span className="text-gray-300">{med.duration_days}d ({intervalLabel(med.duration_days)})</span></div>}
              {med.notes && <div className="text-gray-500 mt-1">{med.notes}</div>}
              <div className="flex gap-2 pt-2">
                <button onClick={startEdit} className={btnSecondary}><Edit3 size={13} />Edit</button>
              </div>
            </div>
          )}
        </div>
      )}
      {confirm && <ConfirmModal message={`Delete "${med.name}"?`} onConfirm={doDelete} onCancel={() => setConfirm(false)} />}
    </div>
  );
}

function AddMedModal({ members, userId, defaultMemberId, onClose, onSave }) {
  const [form, setForm] = useState({ member_id: defaultMemberId || members[0]?.id || "", name: "", dosage_notes: "", prescriber: "", pharmacy: "", last_dose_date: "", duration_days: "", reminder_days: 7, start_date: "", notes: "", created_by: userId || "" });
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    if (!form.member_id || !form.name.trim()) return;
    setSaving(true);
    await fetch(`${API}/medications`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, duration_days: form.duration_days ? +form.duration_days : null }),
    });
    setSaving(false); onClose(); onSave();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[480px] space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Add Medication</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="For"><select value={form.member_id} onChange={e => setForm(f => ({...f, member_id: e.target.value}))} className={inp}>
            {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select></Field>
          <Field label="Medication name"><input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} placeholder="Lisinopril 10mg" /></Field>
          <Field label="Dosage notes"><input value={form.dosage_notes} onChange={e => setForm(f => ({...f, dosage_notes: e.target.value}))} className={inp} placeholder="1 tablet daily" /></Field>
          <Field label="Prescriber"><input value={form.prescriber} onChange={e => setForm(f => ({...f, prescriber: e.target.value}))} className={inp} /></Field>
          <Field label="Pharmacy"><input value={form.pharmacy} onChange={e => setForm(f => ({...f, pharmacy: e.target.value}))} className={inp} /></Field>
          <Field label="Start date"><input type="date" value={form.start_date} onChange={e => setForm(f => ({...f, start_date: e.target.value}))} className={inp} /></Field>
          <Field label="Last dose date (runs out)"><input type="date" value={form.last_dose_date} onChange={e => setForm(f => ({...f, last_dose_date: e.target.value}))} className={inp} /></Field>
          <Field label="Supply duration (days)"><input type="number" value={form.duration_days} onChange={e => setForm(f => ({...f, duration_days: e.target.value}))} className={inp} placeholder="30" /></Field>
          <Field label="Remind days before"><input type="number" value={form.reminder_days} onChange={e => setForm(f => ({...f, reminder_days: +e.target.value}))} className={inp} /></Field>
        </div>
        <Field label="Notes"><textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.member_id || !form.name.trim() || saving} className={btnPrimary}>{saving ? "Saving…" : "Add Medication"}</button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Treatments Tab
// ═══════════════════════════════════════════════════════════════════════════

function TreatmentsTab({ memberId, userId, refreshKey }) {
  const [treatments, setTreatments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInactive, setShowInactive] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [members, setMembers] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, mRes] = await Promise.all([
        fetch(`${API}/treatments?member_id=${memberId}&active=${!showInactive}`).then(r => r.json()),
        fetch(`${API}/members`).then(r => r.json()),
      ]);
      setTreatments(tRes.treatments || []);
      setMembers(mRes.members || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [memberId, showInactive, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const memberName = (id) => members.find(m => m.id === id)?.name || "";

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-teal-400" size={24} /></div>;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800 text-teal-500" />
          Show inactive
        </label>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}><Plus size={14} />Add Treatment</button>
      </div>

      {treatments.length === 0 && <p className="text-gray-500 text-sm text-center py-8">No treatments yet.</p>}

      <div className="space-y-2">
        {treatments.map(t => {
          const days = daysFromToday(t.next_due_at);
          return (
            <TreatmentCard key={t.id} treatment={t} days={days} memberName={memberName(t.member_id)}
              isExpanded={expandedId === t.id} onToggle={() => setExpandedId(expandedId === t.id ? null : t.id)}
              members={members} userId={userId} onRefresh={load} />
          );
        })}
      </div>

      {showAdd && <AddTreatmentModal members={members} userId={userId} defaultMemberId={defaultMemberForUser(members, userId)} onClose={() => setShowAdd(false)} onSave={load} />}
    </div>
  );
}

function TreatmentCard({ treatment: t, days, memberName, isExpanded, onToggle, members, userId, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [log, setLog] = useState([]);
  const [logModal, setLogModal] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [confirmLogId, setConfirmLogId] = useState(null);

  const loadLog = async () => {
    const res = await fetch(`${API}/treatments/${t.id}/log`);
    const data = await res.json();
    setLog(data.log || []);
  };

  useEffect(() => { if (isExpanded) loadLog(); }, [isExpanded]);

  const startEdit = () => {
    setForm({ name: t.name, description: t.description, interval_days: t.interval_days, next_due_at: t.next_due_at, active: t.active, notes: t.notes });
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    await fetch(`${API}/treatments/${t.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    setSaving(false); setEditing(false); onRefresh();
  };

  const doDelete = async () => {
    await fetch(`${API}/treatments/${t.id}`, { method: "DELETE" });
    setConfirm(false); onRefresh();
  };

  const deleteLogEntry = async (logId) => {
    await fetch(`${API}/treatments/log/${logId}`, { method: "DELETE" });
    setConfirmLogId(null); loadLog(); onRefresh();
  };

  return (
    <div className={`rounded-lg border ${t.active ? "border-gray-700/60 bg-gray-800/30" : "border-gray-700/30 bg-gray-900/30 opacity-60"}`}>
      <div className="flex items-center gap-3 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className="text-base">{statusDot(days)}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-200 text-sm">{t.name}</span>
            {memberName && <span className="text-xs text-gray-500">{memberName}</span>}
            <span className="text-xs text-gray-500">{intervalLabel(t.interval_days)}</span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {t.last_done_at && <span className="mr-2">last: {fmtDate(t.last_done_at)}</span>}
            {t.next_due_at && <span>due {fmtDate(t.next_due_at)} ({daysLabel(days)})</span>}
          </div>
        </div>
        <button onClick={e => { e.stopPropagation(); setLogModal(true); }}
          className="text-xs px-2 py-1 rounded bg-teal-700 text-white hover:bg-teal-600 shrink-0">Log It</button>
        {isExpanded ? <ChevronDown size={14} className="text-gray-500 shrink-0" /> : <ChevronRight size={14} className="text-gray-500 shrink-0" />}
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700/40 px-3 py-3">
          {editing ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Name"><input value={form.name || ""} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} /></Field>
                <Field label="Interval (days)"><input type="number" value={form.interval_days || ""} onChange={e => setForm(f => ({...f, interval_days: +e.target.value}))} className={inp} /></Field>
                <Field label="Next due"><input type="date" value={form.next_due_at || ""} onChange={e => setForm(f => ({...f, next_due_at: e.target.value}))} className={inp} /></Field>
                <Field label="Description"><input value={form.description || ""} onChange={e => setForm(f => ({...f, description: e.target.value}))} className={inp} /></Field>
              </div>
              <Field label="Notes"><textarea value={form.notes || ""} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
                  <input type="checkbox" checked={form.active ?? true} onChange={e => setForm(f => ({...f, active: e.target.checked}))} className="rounded border-gray-600 bg-gray-800 text-teal-500" />Active
                </label>
                <div className="flex-1" />
                <button onClick={() => setConfirm(true)} className={btnDanger}><Trash2 size={14} />Delete</button>
                <button onClick={() => setEditing(false)} className={btnSecondary}>Cancel</button>
                <button onClick={save} disabled={saving} className={btnPrimary}><Save size={14} />{saving ? "Saving…" : "Save"}</button>
              </div>
            </div>
          ) : (
            <div className="space-y-1 text-sm text-gray-400">
              {t.description && <div className="text-gray-300">{t.description}</div>}
              {t.notes && <div>{t.notes}</div>}
              <button onClick={startEdit} className={btnSecondary + " mt-2"}><Edit3 size={13} />Edit</button>
            </div>
          )}

          {/* Log history */}
          <div className="mt-3 border-t border-gray-700/30 pt-3">
            <button onClick={() => setShowLog(v => !v)} className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
              {showLog ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Log history ({log.length})
            </button>
            {showLog && (
              <div className="mt-2 space-y-1">
                {log.length === 0 && <p className="text-xs text-gray-600">No log entries yet.</p>}
                {log.map(entry => (
                  <div key={entry.id} className="flex items-center gap-2 text-xs text-gray-400 group">
                    <span className="text-gray-300">{fmtDate(entry.done_at)}</span>
                    {entry.medication && <span className="text-gray-500">{entry.medication}</span>}
                    {entry.notes && <span className="text-gray-500">{entry.notes}</span>}
                    <button onClick={() => setConfirmLogId(entry.id)} className="ml-auto opacity-0 group-hover:opacity-100 p-0.5 text-red-500 hover:text-red-400"><Trash2 size={12} /></button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {logModal && <LogTreatmentModal treatment={t} userId={userId} onClose={() => setLogModal(false)} onSave={() => { loadLog(); onRefresh(); }} />}
      {confirm && <ConfirmModal message={`Delete "${t.name}"?`} onConfirm={doDelete} onCancel={() => setConfirm(false)} />}
      {confirmLogId && <ConfirmModal message="Delete this log entry?" onConfirm={() => deleteLogEntry(confirmLogId)} onCancel={() => setConfirmLogId(null)} />}
    </div>
  );
}

function LogTreatmentModal({ treatment, userId, onClose, onSave }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ done_at: today, medication: "", notes: "", created_by: userId || "" });
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    await fetch(`${API}/treatments/${treatment.id}/log`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    setSaving(false); onClose(); onSave();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-80 space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Log: {treatment.name}</h3>
        <Field label="Date done"><input type="date" value={form.done_at} onChange={e => setForm(f => ({...f, done_at: e.target.value}))} className={inp} /></Field>
        <Field label="Medication / lot# (optional)"><input value={form.medication} onChange={e => setForm(f => ({...f, medication: e.target.value}))} className={inp} /></Field>
        <Field label="Notes"><textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={saving} className={btnPrimary}>{saving ? "Saving…" : "Log It"}</button>
        </div>
      </div>
    </div>
  );
}

function AddTreatmentModal({ members, userId, defaultMemberId, onClose, onSave }) {
  const [form, setForm] = useState({ member_id: defaultMemberId || members[0]?.id || "", name: "", description: "", interval_days: 14, last_done_at: "", next_due_at: "", notes: "", created_by: userId || "" });
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    if (!form.member_id || !form.name.trim()) return;
    setSaving(true);
    await fetch(`${API}/treatments`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    setSaving(false); onClose(); onSave();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[420px] space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Add Treatment</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="For"><select value={form.member_id} onChange={e => setForm(f => ({...f, member_id: e.target.value}))} className={inp}>
            {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select></Field>
          <Field label="Name"><input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} placeholder="Epoetin Alfa injection" /></Field>
          <Field label="Every (days)"><input type="number" value={form.interval_days} onChange={e => setForm(f => ({...f, interval_days: +e.target.value}))} className={inp} /></Field>
          <Field label="Last done"><input type="date" value={form.last_done_at} onChange={e => setForm(f => ({...f, last_done_at: e.target.value}))} className={inp} /></Field>
          <Field label="Next due"><input type="date" value={form.next_due_at} onChange={e => setForm(f => ({...f, next_due_at: e.target.value}))} className={inp} /></Field>
        </div>
        <Field label="Description"><input value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))} className={inp} /></Field>
        <Field label="Notes"><textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.member_id || !form.name.trim() || saving} className={btnPrimary}>{saving ? "Saving…" : "Add Treatment"}</button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Events Tab
// ═══════════════════════════════════════════════════════════════════════════

const EVENT_TYPES = ["visit","surgery","procedure","lab","note","emergency"];
const EVENT_TYPE_COLORS = {
  visit: "text-blue-400", surgery: "text-red-400", procedure: "text-orange-400",
  lab: "text-purple-400", note: "text-gray-400", emergency: "text-red-500",
};

function EventsTab({ memberId, userId, refreshKey }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [members, setMembers] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [eRes, mRes] = await Promise.all([
        fetch(`${API}/events?member_id=${memberId}&type=${typeFilter}`).then(r => r.json()),
        fetch(`${API}/members`).then(r => r.json()),
      ]);
      setEvents(eRes.events || []);
      setMembers(mRes.members || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [memberId, typeFilter, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const memberName = (id) => members.find(m => m.id === id)?.name || "";

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-teal-400" size={24} /></div>;

  return (
    <div className="p-4">
      <div className="flex items-center gap-2 justify-between mb-3">
        <div className="flex gap-1 flex-wrap">
          {["", ...EVENT_TYPES].map(t => (
            <button key={t} onClick={() => setTypeFilter(t)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                typeFilter === t ? "bg-teal-700 text-white border-teal-600" : "border-gray-700 text-gray-400 hover:border-gray-600"
              }`}>
              {t || "All"}
            </button>
          ))}
        </div>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}><Plus size={14} />Log Event</button>
      </div>

      {events.length === 0 && <p className="text-gray-500 text-sm text-center py-8">No events yet.</p>}

      <div className="space-y-2">
        {events.map(ev => (
          <EventCard key={ev.id} event={ev} memberName={memberName(ev.member_id)}
            isExpanded={expandedId === ev.id} onToggle={() => setExpandedId(expandedId === ev.id ? null : ev.id)}
            members={members} onRefresh={load} />
        ))}
      </div>

      {showAdd && <AddEventModal members={members} userId={userId} defaultMemberId={defaultMemberForUser(members, userId)} onClose={() => setShowAdd(false)} onSave={load} />}
    </div>
  );
}

function EventCard({ event: ev, memberName, isExpanded, onToggle, members, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const followDays = daysFromToday(ev.follow_up_date);

  const startEdit = () => {
    setForm({ event_type: ev.event_type, title: ev.title, event_date: ev.event_date, provider: ev.provider, summary: ev.summary, follow_up_date: ev.follow_up_date, follow_up_notes: ev.follow_up_notes, tags: (ev.tags || []).join(", "), notes: ev.notes });
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    const body = { ...form, tags: form.tags ? form.tags.split(",").map(t => t.trim()).filter(Boolean) : [] };
    await fetch(`${API}/events/${ev.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    setSaving(false); setEditing(false); onRefresh();
  };

  const doDelete = async () => {
    await fetch(`${API}/events/${ev.id}`, { method: "DELETE" });
    setConfirm(false); onRefresh();
  };

  const typeColor = EVENT_TYPE_COLORS[ev.event_type] || "text-gray-400";

  return (
    <div className="rounded-lg border border-gray-700/60 bg-gray-800/30">
      <div className="flex items-center gap-3 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className={`text-xs font-mono uppercase font-bold ${typeColor} w-14 shrink-0`}>{ev.event_type}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-200 text-sm">{ev.title}</span>
            {memberName && <span className="text-xs text-gray-500">{memberName}</span>}
            {ev.follow_up_date && (
              <span className={`text-xs px-1.5 py-0.5 rounded border ${followDays !== null && followDays <= 3 ? "text-yellow-400 border-yellow-700/50 bg-yellow-900/20" : "text-gray-500 border-gray-700/50"}`}>
                follow-up {fmtDate(ev.follow_up_date)}
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {fmtDate(ev.event_date)}{ev.provider ? ` — ${ev.provider}` : ""}
            {ev.summary && <span className="ml-2 text-gray-600 truncate">{ev.summary.slice(0, 80)}</span>}
          </div>
        </div>
        {isExpanded ? <ChevronDown size={14} className="text-gray-500 shrink-0" /> : <ChevronRight size={14} className="text-gray-500 shrink-0" />}
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700/40 px-3 py-3">
          {editing ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Type"><select value={form.event_type} onChange={e => setForm(f => ({...f, event_type: e.target.value}))} className={inp}>
                  {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select></Field>
                <Field label="Title"><input value={form.title || ""} onChange={e => setForm(f => ({...f, title: e.target.value}))} className={inp} /></Field>
                <Field label="Date"><input type="date" value={form.event_date || ""} onChange={e => setForm(f => ({...f, event_date: e.target.value}))} className={inp} /></Field>
                <Field label="Provider"><input value={form.provider || ""} onChange={e => setForm(f => ({...f, provider: e.target.value}))} className={inp} /></Field>
                <Field label="Follow-up date"><input type="date" value={form.follow_up_date || ""} onChange={e => setForm(f => ({...f, follow_up_date: e.target.value}))} className={inp} /></Field>
                <Field label="Follow-up notes"><input value={form.follow_up_notes || ""} onChange={e => setForm(f => ({...f, follow_up_notes: e.target.value}))} className={inp} /></Field>
              </div>
              <Field label="Summary"><textarea value={form.summary || ""} onChange={e => setForm(f => ({...f, summary: e.target.value}))} rows={3} className={inp} /></Field>
              <Field label="Tags (comma separated)"><input value={form.tags || ""} onChange={e => setForm(f => ({...f, tags: e.target.value}))} className={inp} /></Field>
              <Field label="Notes"><textarea value={form.notes || ""} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
              <div className="flex justify-end gap-2">
                <button onClick={() => setConfirm(true)} className={btnDanger}><Trash2 size={14} />Delete</button>
                <button onClick={() => setEditing(false)} className={btnSecondary}>Cancel</button>
                <button onClick={save} disabled={saving} className={btnPrimary}><Save size={14} />{saving ? "Saving…" : "Save"}</button>
              </div>
            </div>
          ) : (
            <div className="space-y-1.5 text-sm text-gray-400">
              {ev.summary && <p className="text-gray-300 leading-relaxed">{ev.summary}</p>}
              {ev.follow_up_date && <p>Follow-up: <span className="text-gray-300">{fmtDate(ev.follow_up_date)}</span>{ev.follow_up_notes ? ` — ${ev.follow_up_notes}` : ""}</p>}
              {ev.tags?.length > 0 && <div className="flex gap-1 flex-wrap">{ev.tags.map(tag => <span key={tag} className="text-xs px-1.5 py-0.5 rounded bg-gray-700/60 text-gray-400">{tag}</span>)}</div>}
              {ev.notes && <p className="text-gray-500">{ev.notes}</p>}
              <button onClick={startEdit} className={btnSecondary + " mt-2"}><Edit3 size={13} />Edit</button>
            </div>
          )}
        </div>
      )}
      {confirm && <ConfirmModal message={`Delete "${ev.title}"?`} onConfirm={doDelete} onCancel={() => setConfirm(false)} />}
    </div>
  );
}

function AddEventModal({ members, userId, defaultMemberId, onClose, onSave }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ member_id: defaultMemberId || members[0]?.id || "", event_type: "visit", title: "", event_date: today, provider: "", summary: "", follow_up_date: "", follow_up_notes: "", tags: "", notes: "", created_by: userId || "" });
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    if (!form.member_id || !form.title.trim()) return;
    setSaving(true);
    const body = { ...form, tags: form.tags ? form.tags.split(",").map(t => t.trim()).filter(Boolean) : [] };
    await fetch(`${API}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    setSaving(false); onClose(); onSave();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[500px] space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Log Medical Event</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="For"><select value={form.member_id} onChange={e => setForm(f => ({...f, member_id: e.target.value}))} className={inp}>
            {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select></Field>
          <Field label="Type"><select value={form.event_type} onChange={e => setForm(f => ({...f, event_type: e.target.value}))} className={inp}>
            {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select></Field>
          <Field label="Title" ><input value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} className={inp} placeholder="Annual Physical" /></Field>
          <Field label="Date"><input type="date" value={form.event_date} onChange={e => setForm(f => ({...f, event_date: e.target.value}))} className={inp} /></Field>
          <Field label="Provider"><input value={form.provider} onChange={e => setForm(f => ({...f, provider: e.target.value}))} className={inp} /></Field>
          <Field label="Follow-up date"><input type="date" value={form.follow_up_date} onChange={e => setForm(f => ({...f, follow_up_date: e.target.value}))} className={inp} /></Field>
          <Field label="Follow-up notes"><input value={form.follow_up_notes} onChange={e => setForm(f => ({...f, follow_up_notes: e.target.value}))} className={inp} /></Field>
          <Field label="Tags (comma separated)"><input value={form.tags} onChange={e => setForm(f => ({...f, tags: e.target.value}))} className={inp} /></Field>
        </div>
        <Field label="Summary"><textarea value={form.summary} onChange={e => setForm(f => ({...f, summary: e.target.value}))} rows={3} className={inp} /></Field>
        <Field label="Notes"><textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.member_id || !form.title.trim() || saving} className={btnPrimary}>{saving ? "Saving…" : "Log Event"}</button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Labs Tab
// ═══════════════════════════════════════════════════════════════════════════

function LabsTab({ memberId, userId, refreshKey }) {
  const [tests, setTests] = useState([]);
  const [results, setResults] = useState([]);
  const [members, setMembers] = useState([]);
  const [labEvents, setLabEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterTestId, setFilterTestId] = useState("");
  const [filterEventId, setFilterEventId] = useState("");
  const [showManage, setShowManage] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, rRes, mRes, evRes] = await Promise.all([
        fetch(`${API}/lab-tests`).then(r => r.json()),
        fetch(`${API}/lab-results?member_id=${memberId}&test_id=${filterTestId}&event_id=${filterEventId}`).then(r => r.json()),
        fetch(`${API}/members`).then(r => r.json()),
        fetch(`${API}/events/lab-events?member_id=${memberId}`).then(r => r.json()),
      ]);
      setTests(tRes.lab_tests || []);
      setResults(rRes.results || []);
      setMembers(mRes.members || []);
      setLabEvents(evRes.events || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [memberId, filterTestId, filterEventId, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const memberName = (id) => members.find(m => m.id === id)?.name || "";

  // Build results grid: rows by date, cols by test
  const dateMap = {};
  for (const r of results) {
    const key = `${r.result_date}::${r.member_id}`;
    if (!dateMap[key]) dateMap[key] = { date: r.result_date, member_id: r.member_id, values: {}, event_id: r.event_id };
    dateMap[key].values[r.lab_test_id] = r;
  }
  const rows = Object.values(dateMap).sort((a, b) => b.date.localeCompare(a.date));
  const displayTests = filterTestId ? tests.filter(t => t.id === filterTestId) : tests;

  const deleteRow = async (member_id, date) => {
    if (!confirm(`Delete all results for ${fmtDate(date)}?`)) return;
    await fetch(`${API}/lab-results/by-date/${member_id}/${date}`, { method: "DELETE" });
    load();
  };

  const updateCell = async (resultId, value) => {
    await fetch(`${API}/lab-results/${resultId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: parseFloat(value) }),
    });
    load();
  };

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-teal-400" size={24} /></div>;

  return (
    <div className="p-4">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <select value={filterTestId} onChange={e => setFilterTestId(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300">
          <option value="">All Tests</option>
          {tests.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select value={filterEventId} onChange={e => setFilterEventId(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300 max-w-[200px]">
          <option value="">All Draws</option>
          {labEvents.map(ev => <option key={ev.id} value={ev.id}>{fmtDate(ev.event_date)} — {ev.title}</option>)}
        </select>
        <div className="flex-1" />
        <button onClick={() => setShowManage(v => !v)} className={`p-1.5 rounded hover:bg-gray-700 ${showManage ? "text-teal-400 bg-gray-700" : "text-gray-500"}`} title="Manage lab tests"><Settings size={16} /></button>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}><Plus size={14} />Log Results</button>
      </div>

      {showManage && <ManageLabTests tests={tests} onRefresh={load} />}

      {rows.length === 0 && !showManage && <p className="text-gray-500 text-sm text-center py-8">No lab results yet.</p>}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-gray-500 text-left border-b border-gray-700/50">
                <th className="py-1.5 pr-3 font-medium">Date</th>
                <th className="py-1.5 pr-3 font-medium">Who</th>
                {displayTests.map(t => (
                  <th key={t.id} className="py-1.5 pr-3 font-medium whitespace-nowrap">
                    {t.name}{t.unit ? <span className="text-xs text-gray-600 ml-1">({t.unit})</span> : ""}
                  </th>
                ))}
                <th className="py-1.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <LabResultRow key={`${row.date}::${row.member_id}`} row={row} displayTests={displayTests}
                  memberName={memberName(row.member_id)} onDelete={() => deleteRow(row.member_id, row.date)}
                  onUpdateCell={updateCell} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && <LogLabResultsModal members={members} tests={tests} labEvents={labEvents} userId={userId} defaultMemberId={defaultMemberForUser(members, userId)} onClose={() => setShowAdd(false)} onSave={load} />}
    </div>
  );
}

function LabResultRow({ row, displayTests, memberName, onDelete, onUpdateCell }) {
  const [editingCell, setEditingCell] = useState(null);
  const [cellVal, setCellVal] = useState("");
  const [confirm, setConfirm] = useState(false);

  return (
    <tr className="border-b border-gray-700/30 hover:bg-gray-800/20 group">
      <td className="py-1.5 pr-3 text-gray-300 whitespace-nowrap">{fmtDate(row.date)}</td>
      <td className="py-1.5 pr-3 text-gray-500 whitespace-nowrap">{memberName}</td>
      {displayTests.map(t => {
        const result = row.values[t.id];
        const val = result?.value;
        const abnormal = val !== undefined && val !== null && ((t.normal_min !== null && val < t.normal_min) || (t.normal_max !== null && val > t.normal_max));
        const isEditing = editingCell === t.id;
        return (
          <td key={t.id} className="py-1.5 pr-3">
            {result ? (
              isEditing ? (
                <input autoFocus type="number" step="any" value={cellVal}
                  onChange={e => setCellVal(e.target.value)}
                  onBlur={() => { onUpdateCell(result.id, cellVal); setEditingCell(null); }}
                  onKeyDown={e => { if (e.key === "Enter") { onUpdateCell(result.id, cellVal); setEditingCell(null); } if (e.key === "Escape") setEditingCell(null); }}
                  className="w-20 text-sm bg-gray-900 border border-teal-500 rounded px-1.5 py-0.5 text-gray-200" />
              ) : (
                <span
                  className={`cursor-pointer hover:underline ${abnormal ? "text-yellow-400 font-medium" : "text-gray-300"}`}
                  onClick={() => { setEditingCell(t.id); setCellVal(String(val)); }}
                  title="Click to edit"
                >
                  {val}
                </span>
              )
            ) : (
              <span className="text-gray-700">—</span>
            )}
          </td>
        );
      })}
      <td className="py-1.5">
        <button onClick={() => setConfirm(true)} className="opacity-0 group-hover:opacity-100 p-1 text-gray-600 hover:text-red-400 rounded"><Trash2 size={12} /></button>
        {confirm && <ConfirmModal message={`Delete all results for ${fmtDate(row.date)}?`} onConfirm={onDelete} onCancel={() => setConfirm(false)} />}
      </td>
    </tr>
  );
}

function ManageLabTests({ tests, onRefresh }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", unit: "", normal_min: "", normal_max: "", sort_order: 0 });
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [confirm, setConfirm] = useState(null);

  const saveAdd = async () => {
    if (!form.name.trim()) return;
    await fetch(`${API}/lab-tests`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, normal_min: form.normal_min ? +form.normal_min : null, normal_max: form.normal_max ? +form.normal_max : null }),
    });
    setAdding(false); setForm({ name: "", unit: "", normal_min: "", normal_max: "", sort_order: 0 }); onRefresh();
  };

  const saveEdit = async () => {
    await fetch(`${API}/lab-tests/${editId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...editForm, normal_min: editForm.normal_min ? +editForm.normal_min : null, normal_max: editForm.normal_max ? +editForm.normal_max : null }),
    });
    setEditId(null); onRefresh();
  };

  const doDelete = async (id) => {
    const res = await fetch(`${API}/lab-tests/${id}`, { method: "DELETE" });
    if (!res.ok) { alert("Cannot delete — results exist for this test"); }
    setConfirm(null); onRefresh();
  };

  return (
    <div className="mb-4 p-3 bg-gray-800/40 rounded-lg border border-gray-700/60">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Lab Tests</span>
        <button onClick={() => setAdding(true)} className="text-xs flex items-center gap-1 text-teal-400 hover:text-teal-300"><Plus size={12} />Add</button>
      </div>
      {adding && (
        <div className="flex gap-1 mb-2 flex-wrap">
          <input placeholder="Name" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp + " flex-1 min-w-[100px]"} />
          <input placeholder="Unit" value={form.unit} onChange={e => setForm(f => ({...f, unit: e.target.value}))} className={inp + " w-20"} />
          <input placeholder="Min" type="number" value={form.normal_min} onChange={e => setForm(f => ({...f, normal_min: e.target.value}))} className={inp + " w-16"} />
          <input placeholder="Max" type="number" value={form.normal_max} onChange={e => setForm(f => ({...f, normal_max: e.target.value}))} className={inp + " w-16"} />
          <button onClick={saveAdd} className="p-1 text-emerald-400 hover:bg-emerald-900/40 rounded"><Save size={16} /></button>
          <button onClick={() => setAdding(false)} className="p-1 text-gray-500 hover:bg-gray-700 rounded"><X size={16} /></button>
        </div>
      )}
      <div className="space-y-1">
        {tests.map(t => (
          <div key={t.id} className="flex items-center gap-2 text-xs group">
            {editId === t.id ? (
              <>
                <input value={editForm.name || ""} onChange={e => setEditForm(f => ({...f, name: e.target.value}))} className={inp + " flex-1"} />
                <input placeholder="Unit" value={editForm.unit || ""} onChange={e => setEditForm(f => ({...f, unit: e.target.value}))} className={inp + " w-16"} />
                <input placeholder="Min" type="number" value={editForm.normal_min ?? ""} onChange={e => setEditForm(f => ({...f, normal_min: e.target.value}))} className={inp + " w-16"} />
                <input placeholder="Max" type="number" value={editForm.normal_max ?? ""} onChange={e => setEditForm(f => ({...f, normal_max: e.target.value}))} className={inp + " w-16"} />
                <button onClick={saveEdit} className="p-1 text-emerald-400 hover:bg-emerald-900/40 rounded"><Save size={14} /></button>
                <button onClick={() => setEditId(null)} className="p-1 text-gray-500 hover:bg-gray-700 rounded"><X size={14} /></button>
              </>
            ) : (
              <>
                <span className="text-gray-300 flex-1">{t.name}</span>
                {t.unit && <span className="text-gray-600">{t.unit}</span>}
                {(t.normal_min !== null || t.normal_max !== null) && <span className="text-gray-600">{t.normal_min ?? "?"}–{t.normal_max ?? "?"}</span>}
                <button onClick={() => { setEditId(t.id); setEditForm({ name: t.name, unit: t.unit, normal_min: t.normal_min ?? "", normal_max: t.normal_max ?? "" }); }} className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-500 hover:text-gray-300 rounded"><Edit3 size={12} /></button>
                <button onClick={() => setConfirm(t.id)} className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-600 hover:text-red-400 rounded"><Trash2 size={12} /></button>
              </>
            )}
          </div>
        ))}
      </div>
      {confirm && <ConfirmModal message="Delete this lab test? (Only allowed if no results exist)" onConfirm={() => doDelete(confirm)} onCancel={() => setConfirm(null)} />}
    </div>
  );
}

function LogLabResultsModal({ members, tests, labEvents, userId, defaultMemberId, onClose, onSave }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ member_id: defaultMemberId || members[0]?.id || "", result_date: today, event_id: "", created_by: userId || "" });
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const results = Object.entries(values)
      .filter(([, v]) => v !== "" && v !== undefined)
      .map(([lab_test_id, value]) => ({ lab_test_id, value: parseFloat(value) }));
    if (!form.member_id || results.length === 0) return;
    setSaving(true);
    await fetch(`${API}/lab-results/bulk`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, event_id: form.event_id || null, results }),
    });
    setSaving(false); onClose(); onSave();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[440px] space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Log Lab Results</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="For"><select value={form.member_id} onChange={e => setForm(f => ({...f, member_id: e.target.value}))} className={inp}>
            {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select></Field>
          <Field label="Draw date"><input type="date" value={form.result_date} onChange={e => setForm(f => ({...f, result_date: e.target.value}))} className={inp} /></Field>
        </div>
        <Field label="Link to lab event (optional)">
          <select value={form.event_id} onChange={e => {
            const ev = labEvents.find(ev => ev.id === e.target.value);
            setForm(f => ({ ...f, event_id: e.target.value, ...(ev ? { result_date: ev.event_date } : {}) }));
          }} className={inp}>
            <option value="">None</option>
            {labEvents.map(ev => <option key={ev.id} value={ev.id}>{fmtDate(ev.event_date)} — {ev.title}</option>)}
          </select>
        </Field>
        <div className="border-t border-gray-700/40 pt-2">
          <p className="text-xs text-gray-500 mb-2">Enter values (leave blank to skip):</p>
          <div className="grid grid-cols-2 gap-2">
            {tests.map(t => (
              <Field key={t.id} label={`${t.name}${t.unit ? ` (${t.unit})` : ""}`}>
                <input type="number" step="any" value={values[t.id] ?? ""} onChange={e => setValues(v => ({...v, [t.id]: e.target.value}))} className={inp} />
              </Field>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.member_id || Object.values(values).every(v => !v) || saving} className={btnPrimary}>{saving ? "Saving…" : "Save Results"}</button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Appointments Tab
// ═══════════════════════════════════════════════════════════════════════════

const APPT_TYPES = ["visit", "specialist", "procedure", "lab", "dentist", "followup", "other"];
const APPT_TYPE_COLORS = {
  visit:      "text-blue-400",
  specialist: "text-purple-400",
  procedure:  "text-orange-400",
  lab:        "text-teal-400",
  dentist:    "text-green-400",
  followup:   "text-yellow-400",
  other:      "text-gray-400",
};

function fmtDateTime(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return d.toLocaleString("en-US", {
      weekday: "short", month: "numeric", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch { return isoStr; }
}

function fmtTimeOnly(isoStr) {
  if (!isoStr) return "";
  try {
    return new Date(isoStr).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch { return ""; }
}

function apptCountdown(isoStr) {
  if (!isoStr) return null;
  const diffMs = new Date(isoStr) - Date.now();
  if (diffMs < 0) return { label: "past", cls: "text-gray-500" };
  const diffH = diffMs / 3600000;
  if (diffH < 2)   return { label: `in ${Math.round(diffMs / 60000)}m`, cls: "text-red-400 font-semibold" };
  if (diffH < 24)  return { label: `in ${Math.round(diffH)}h`, cls: "text-yellow-400" };
  const diffD = Math.ceil(diffH / 24);
  if (diffD === 1) return { label: "tomorrow", cls: "text-yellow-400" };
  return { label: `in ${diffD}d`, cls: "text-gray-400" };
}

function NotifyBadges({ appt }) {
  return (
    <div className="flex gap-1">
      <span title="24h reminder" className={`text-xs ${appt.notified_24h ? "text-teal-500" : "text-gray-700"}`}>
        {appt.notified_24h ? <Bell size={11} /> : <BellOff size={11} />}
        <span className="sr-only">24h</span>
      </span>
      <span title="2h reminder" className={`text-xs ${appt.notified_2h ? "text-teal-500" : "text-gray-700"}`}>
        {appt.notified_2h ? <Bell size={11} /> : <BellOff size={11} />}
        <span className="sr-only">2h</span>
      </span>
    </div>
  );
}

function AppointmentsTab({ memberId, userId, refreshKey }) {
  const [appts, setAppts] = useState([]);
  const [unloggedIds, setUnloggedIds] = useState(new Set());
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showPast, setShowPast] = useState(false);
  const [showCancelled, setShowCancelled] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [aRes, mRes, ulRes] = await Promise.all([
        fetch(`${API}/appointments?member_id=${memberId}&include_past=${showPast}&include_cancelled=${showCancelled}`).then(r => r.json()),
        fetch(`${API}/members`).then(r => r.json()),
        fetch(`${API}/appointments/unlogged?member_id=${memberId}`).then(r => r.json()),
      ]);
      setAppts(aRes.appointments || []);
      setMembers(mRes.members || []);
      setUnloggedIds(new Set((ulRes.appointments || []).map(a => a.id)));
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [memberId, showPast, showCancelled, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const memberName = (id) => members.find(m => m.id === id)?.name || "";

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-teal-400" size={24} /></div>;

  const upcoming = appts.filter(a => !a.cancelled);
  const cancelled = appts.filter(a => a.cancelled);

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
            <input type="checkbox" checked={showPast} onChange={e => setShowPast(e.target.checked)}
              className="rounded border-gray-600 bg-gray-800 text-teal-500" />
            Past
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
            <input type="checkbox" checked={showCancelled} onChange={e => setShowCancelled(e.target.checked)}
              className="rounded border-gray-600 bg-gray-800 text-teal-500" />
            Cancelled
          </label>
          {unloggedIds.size > 0 && (
            <span className="text-xs text-amber-400 flex items-center gap-1">
              <AlertTriangle size={12} />{unloggedIds.size} need visit log
            </span>
          )}
        </div>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}><Plus size={14} />Schedule Appointment</button>
      </div>

      {appts.length === 0 && (
        <p className="text-gray-500 text-sm text-center py-8">No appointments scheduled.</p>
      )}

      <div className="space-y-2">
        {upcoming.map(appt => (
          <ApptCard key={appt.id} appt={appt} memberName={memberName(appt.member_id)}
            isExpanded={expandedId === appt.id}
            onToggle={() => setExpandedId(expandedId === appt.id ? null : appt.id)}
            members={members} userId={userId} onRefresh={load}
            needsLog={unloggedIds.has(appt.id)} />
        ))}
        {showCancelled && cancelled.length > 0 && (
          <>
            <p className="text-xs text-gray-600 uppercase tracking-wide pt-2">Cancelled</p>
            {cancelled.map(appt => (
              <ApptCard key={appt.id} appt={appt} memberName={memberName(appt.member_id)}
                isExpanded={expandedId === appt.id}
                onToggle={() => setExpandedId(expandedId === appt.id ? null : appt.id)}
                members={members} userId={userId} onRefresh={load}
                needsLog={false} />
            ))}
          </>
        )}
      </div>

      {showAdd && (
        <AddApptModal
          members={members} userId={userId}
          defaultMemberId={defaultMemberForUser(members, userId)}
          onClose={() => setShowAdd(false)} onSave={load}
        />
      )}
    </div>
  );
}

function ApptCard({ appt, memberName, isExpanded, onToggle, members, userId, onRefresh, needsLog }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [showLogVisit, setShowLogVisit] = useState(false);

  const countdown = apptCountdown(appt.appointment_at);
  const typeColor = APPT_TYPE_COLORS[appt.appointment_type] || "text-gray-400";

  const startEdit = () => {
    const localDt = appt.appointment_at
      ? (() => { const d = new Date(appt.appointment_at); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); })()
      : "";
    setForm({
      title: appt.title,
      appointment_at: localDt,
      provider: appt.provider,
      location: appt.location,
      appointment_type: appt.appointment_type,
      notes: appt.notes,
      cancelled: appt.cancelled,
    });
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    const payload = { ...form };
    if (payload.appointment_at) payload.appointment_at = new Date(payload.appointment_at).toISOString();
    await fetch(`${API}/appointments/${appt.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSaving(false); setEditing(false); onRefresh();
  };

  const doDelete = async () => {
    await fetch(`${API}/appointments/${appt.id}`, { method: "DELETE" });
    setConfirm(false); onRefresh();
  };

  const toggleCancel = async () => {
    await fetch(`${API}/appointments/${appt.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cancelled: !appt.cancelled }),
    });
    onRefresh();
  };

  return (
    <div className={`rounded-lg border ${
      appt.cancelled
        ? "border-gray-700/30 bg-gray-900/30 opacity-60"
        : countdown?.label === "past"
          ? "border-gray-700/40 bg-gray-800/20 opacity-70"
          : "border-gray-700/60 bg-gray-800/30"
    }`}>
      <div className="flex items-center gap-3 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className={`text-xs font-mono uppercase font-bold ${typeColor} w-16 shrink-0`}>
          {appt.appointment_type}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-200 text-sm">{appt.title}</span>
            {memberName && <span className="text-xs text-gray-500">{memberName}</span>}
            {appt.cancelled && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700/60 text-gray-500">cancelled</span>
            )}
            {countdown && !appt.cancelled && (
              <span className={`text-xs ${countdown.cls}`}>{countdown.label}</span>
            )}
            {needsLog && (
              <span className="flex items-center gap-0.5 text-xs text-amber-400 font-medium">
                <AlertTriangle size={11} />no visit log
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            <span>{fmtDateTime(appt.appointment_at)}</span>
            {appt.provider && <span className="ml-2">— {appt.provider}</span>}
            {appt.location && <span className="ml-2 text-gray-600">📍 {appt.location}</span>}
          </div>
        </div>
        <NotifyBadges appt={appt} />
        {isExpanded ? <ChevronDown size={14} className="text-gray-500 shrink-0" /> : <ChevronRight size={14} className="text-gray-500 shrink-0" />}
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700/40 px-3 py-3">
          {editing ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Title">
                  <input value={form.title || ""} onChange={e => setForm(f => ({...f, title: e.target.value}))} className={inp} />
                </Field>
                <Field label="Type">
                  <select value={form.appointment_type} onChange={e => setForm(f => ({...f, appointment_type: e.target.value}))} className={inp}>
                    {APPT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
                <Field label="Date & Time">
                  <input type="datetime-local" value={form.appointment_at || ""} onChange={e => setForm(f => ({...f, appointment_at: e.target.value}))} className={inp} />
                </Field>
                <Field label="Provider / Doctor">
                  <input value={form.provider || ""} onChange={e => setForm(f => ({...f, provider: e.target.value}))} className={inp} />
                </Field>
                <Field label="Location">
                  <input value={form.location || ""} onChange={e => setForm(f => ({...f, location: e.target.value}))} className={inp} />
                </Field>
              </div>
              <Field label="Notes">
                <textarea value={form.notes || ""} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} />
              </Field>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
                  <input type="checkbox" checked={form.cancelled ?? false} onChange={e => setForm(f => ({...f, cancelled: e.target.checked}))}
                    className="rounded border-gray-600 bg-gray-800 text-red-500" />
                  Cancelled
                </label>
                <div className="flex-1" />
                <button onClick={() => setConfirm(true)} className={btnDanger}><Trash2 size={14} />Delete</button>
                <button onClick={() => setEditing(false)} className={btnSecondary}>Cancel</button>
                <button onClick={save} disabled={saving} className={btnPrimary}><Save size={14} />{saving ? "Saving…" : "Save"}</button>
              </div>
            </div>
          ) : (
            <div className="space-y-1.5 text-sm text-gray-400">
              {appt.location && <div>Location: <span className="text-gray-300">{appt.location}</span></div>}
              {appt.notes && <p className="text-gray-500">{appt.notes}</p>}
              <div className="flex items-center gap-2 pt-1 flex-wrap">
                <div className="flex items-center gap-1 text-xs text-gray-600">
                  <Bell size={11} className={appt.notified_24h ? "text-teal-500" : ""} />
                  <span className={appt.notified_24h ? "text-teal-500" : ""}>24h sent</span>
                  <Bell size={11} className={`ml-2 ${appt.notified_2h ? "text-teal-500" : ""}`} />
                  <span className={appt.notified_2h ? "text-teal-500" : ""}>2h sent</span>
                </div>
                <div className="flex-1" />
                {needsLog && (
                  <button onClick={() => setShowLogVisit(true)}
                    className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-amber-900/40 text-amber-400 hover:bg-amber-800/60 transition-colors">
                    <Plus size={12} />Log Visit Results
                  </button>
                )}
                <button onClick={toggleCancel} className={btnSecondary}>
                  {appt.cancelled ? "Uncancel" : "Cancel Appt"}
                </button>
                <button onClick={startEdit} className={btnSecondary}><Edit3 size={13} />Edit</button>
              </div>
            </div>
          )}
        </div>
      )}
      {confirm && <ConfirmModal message={`Delete "${appt.title}"?`} onConfirm={doDelete} onCancel={() => setConfirm(false)} />}
      {showLogVisit && (
        <LogVisitModal appt={appt} userId={userId}
          onClose={() => setShowLogVisit(false)} onSave={() => { setShowLogVisit(false); onRefresh(); }} />
      )}
    </div>
  );
}

function LogVisitModal({ appt, userId, onClose, onSave }) {
  const apptDate = appt.appointment_at ? appt.appointment_at.slice(0, 10) : new Date().toISOString().slice(0, 10);
  const apptTypeToEventType = { visit: "visit", specialist: "visit", procedure: "procedure",
    lab: "lab", dentist: "visit", followup: "visit", other: "note" };
  const [form, setForm] = useState({
    title: appt.title || "",
    event_type: apptTypeToEventType[appt.appointment_type] || "visit",
    event_date: apptDate,
    provider: appt.provider || "",
    summary: "",
    follow_up_date: "",
    follow_up_notes: "",
    notes: "",
    created_by: userId || "",
  });
  const [saving, setSaving] = useState(false);

  const EVENT_TYPES = ["visit", "lab", "procedure", "note", "hospitalization", "emergency", "surgery", "other"];

  const submit = async () => {
    if (!form.title.trim() || !form.event_date) return;
    setSaving(true);
    await fetch(`${API}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        member_id: appt.member_id,
        appointment_id: appt.id,
        ...form,
        follow_up_date: form.follow_up_date || null,
      }),
    });
    setSaving(false);
    onSave();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[480px] space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div>
          <h3 className="text-base font-bold text-gray-200">Log Visit Results</h3>
          <p className="text-xs text-gray-500 mt-0.5">Linked to: <span className="text-amber-400">{appt.title}</span></p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Event Title">
            <input value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} className={inp} />
          </Field>
          <Field label="Event Type">
            <select value={form.event_type} onChange={e => setForm(f => ({...f, event_type: e.target.value}))} className={inp}>
              {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Visit Date">
            <input type="date" value={form.event_date} onChange={e => setForm(f => ({...f, event_date: e.target.value}))} className={inp} />
          </Field>
          <Field label="Provider">
            <input value={form.provider} onChange={e => setForm(f => ({...f, provider: e.target.value}))} className={inp} />
          </Field>
          <Field label="Follow-up Date">
            <input type="date" value={form.follow_up_date} onChange={e => setForm(f => ({...f, follow_up_date: e.target.value}))} className={inp} />
          </Field>
          <Field label="Follow-up Notes">
            <input value={form.follow_up_notes} onChange={e => setForm(f => ({...f, follow_up_notes: e.target.value}))} className={inp} />
          </Field>
        </div>
        <Field label="Visit Summary">
          <textarea value={form.summary} onChange={e => setForm(f => ({...f, summary: e.target.value}))}
            rows={4} className={inp} placeholder="Diagnosis, findings, recommendations…" />
        </Field>
        <Field label="Additional Notes">
          <textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.title.trim() || !form.event_date || saving} className={btnPrimary}>
            {saving ? "Saving…" : "Save Visit Log"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Equipment Tab
// ═══════════════════════════════════════════════════════════════════════════

function fmtInterval(days) {
  if (!days) return null;
  if (days === 1)   return "daily";
  if (days === 7)   return "weekly";
  if (days === 14)  return "every 2 weeks";
  if (days === 30)  return "monthly";
  if (days === 60)  return "every 2 months";
  if (days === 90)  return "quarterly";
  if (days === 180) return "every 6 months";
  if (days === 365) return "yearly";
  return `every ${days}d`;
}

function taskDueStatus(next_due_at) {
  if (!next_due_at) return null;
  const today = new Date(); today.setHours(0,0,0,0);
  const due = new Date(next_due_at + "T00:00:00");
  const diffDays = Math.round((due - today) / 86400000);
  if (diffDays < 0)  return { label: `${Math.abs(diffDays)}d overdue`, cls: "text-red-400 font-semibold", overdue: true };
  if (diffDays === 0) return { label: "due today", cls: "text-yellow-400 font-semibold", overdue: false };
  if (diffDays <= 7)  return { label: `due in ${diffDays}d`, cls: "text-yellow-400", overdue: false };
  return { label: `due ${fmtDate(next_due_at)}`, cls: "text-gray-500", overdue: false };
}

function EquipmentTab({ memberId, userId, refreshKey }) {
  const [equipment, setEquipment] = useState([]);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInactive, setShowInactive] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [eRes, mRes] = await Promise.all([
        fetch(`${API}/equipment?member_id=${memberId}&include_inactive=${showInactive}`).then(r => r.json()),
        fetch(`${API}/members`).then(r => r.json()),
      ]);
      setEquipment(eRes.equipment || []);
      setMembers(mRes.members || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [memberId, showInactive, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const memberName = (id) => members.find(m => m.id === id)?.name || "";

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-teal-400" size={24} /></div>;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
          <input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800 text-teal-500" />
          Show inactive
        </label>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}><Plus size={14} />Add Equipment</button>
      </div>

      {equipment.length === 0 && (
        <p className="text-gray-500 text-sm text-center py-8">No medical equipment tracked yet.</p>
      )}

      <div className="space-y-3">
        {equipment.map(equip => (
          <EquipmentCard key={equip.id} equip={equip}
            memberName={memberName(equip.member_id)}
            isExpanded={expandedId === equip.id}
            onToggle={() => setExpandedId(expandedId === equip.id ? null : equip.id)}
            members={members} userId={userId} onRefresh={load} />
        ))}
      </div>

      {showAdd && (
        <AddEquipmentModal members={members} userId={userId}
          defaultMemberId={defaultMemberForUser(members, userId)}
          onClose={() => setShowAdd(false)} onSave={load} />
      )}
    </div>
  );
}

function EquipmentCard({ equip, memberName, isExpanded, onToggle, members, userId, onRefresh }) {
  const [tasks, setTasks] = useState([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [showAddTask, setShowAddTask] = useState(false);

  const loadTasks = useCallback(async () => {
    if (!isExpanded) return;
    setLoadingTasks(true);
    try {
      const res = await fetch(`${API}/equipment/${equip.id}/tasks`).then(r => r.json());
      setTasks(res.tasks || []);
    } catch (e) { console.error(e); }
    setLoadingTasks(false);
  }, [equip.id, isExpanded]);

  useEffect(() => { loadTasks(); }, [loadTasks]);

  const overdueCount = tasks.filter(t => {
    if (!t.next_due_at) return false;
    const today = new Date(); today.setHours(0,0,0,0);
    return new Date(t.next_due_at + "T00:00:00") < today;
  }).length;

  const startEdit = () => {
    setForm({ name: equip.name, description: equip.description, brand: equip.brand,
               model: equip.model, serial_no: equip.serial_no, notes: equip.notes, active: equip.active });
    setEditing(true);
  };

  const saveEquip = async () => {
    setSaving(true);
    await fetch(`${API}/equipment/${equip.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setSaving(false); setEditing(false); onRefresh();
  };

  const doDelete = async () => {
    await fetch(`${API}/equipment/${equip.id}`, { method: "DELETE" });
    setConfirm(false); onRefresh();
  };

  return (
    <div className={`rounded-lg border ${equip.active ? "border-gray-700/60 bg-gray-800/30" : "border-gray-700/30 bg-gray-900/30 opacity-60"}`}>
      <div className="flex items-center gap-3 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <Wrench size={15} className="text-teal-500 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-200 text-sm">{equip.name}</span>
            {memberName && <span className="text-xs text-gray-500">{memberName}</span>}
            {!equip.active && <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700/60 text-gray-500">inactive</span>}
            {overdueCount > 0 && (
              <span className="flex items-center gap-1 text-xs text-red-400">
                <AlertTriangle size={11} />{overdueCount} overdue
              </span>
            )}
          </div>
          {(equip.brand || equip.model) && (
            <div className="text-xs text-gray-600 mt-0.5">
              {[equip.brand, equip.model].filter(Boolean).join(" · ")}
              {equip.serial_no && <span className="ml-2">S/N: {equip.serial_no}</span>}
            </div>
          )}
        </div>
        <span className="text-xs text-gray-600">{tasks.length > 0 ? `${tasks.length} task${tasks.length !== 1 ? "s" : ""}` : ""}</span>
        {isExpanded ? <ChevronDown size={14} className="text-gray-500 shrink-0" /> : <ChevronRight size={14} className="text-gray-500 shrink-0" />}
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700/40">
          {editing ? (
            <div className="px-3 py-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Name"><input value={form.name || ""} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} /></Field>
                <Field label="Brand"><input value={form.brand || ""} onChange={e => setForm(f => ({...f, brand: e.target.value}))} className={inp} /></Field>
                <Field label="Model"><input value={form.model || ""} onChange={e => setForm(f => ({...f, model: e.target.value}))} className={inp} /></Field>
                <Field label="Serial #"><input value={form.serial_no || ""} onChange={e => setForm(f => ({...f, serial_no: e.target.value}))} className={inp} /></Field>
              </div>
              <Field label="Description"><input value={form.description || ""} onChange={e => setForm(f => ({...f, description: e.target.value}))} className={inp} /></Field>
              <Field label="Notes"><textarea value={form.notes || ""} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} /></Field>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
                  <input type="checkbox" checked={form.active ?? true} onChange={e => setForm(f => ({...f, active: e.target.checked}))}
                    className="rounded border-gray-600 bg-gray-800 text-teal-500" />
                  Active
                </label>
                <div className="flex-1" />
                <button onClick={() => setConfirm(true)} className={btnDanger}><Trash2 size={14} />Delete</button>
                <button onClick={() => setEditing(false)} className={btnSecondary}>Cancel</button>
                <button onClick={saveEquip} disabled={saving} className={btnPrimary}><Save size={14} />{saving ? "Saving…" : "Save"}</button>
              </div>
            </div>
          ) : (
            <div className="px-3 pt-2 pb-1 flex items-center gap-2 flex-wrap">
              {equip.description && <span className="text-xs text-gray-500 flex-1">{equip.description}</span>}
              {equip.notes && <span className="text-xs text-gray-600 flex-1">{equip.notes}</span>}
              <div className="flex items-center gap-2 ml-auto">
                <button onClick={() => setShowAddTask(true)} className={btnSecondary}><Plus size={13} />Add Task</button>
                <button onClick={startEdit} className={btnSecondary}><Edit3 size={13} />Edit</button>
              </div>
            </div>
          )}

          {/* Tasks */}
          <div className="px-3 pb-3">
            {loadingTasks
              ? <div className="flex justify-center py-3"><Loader2 className="animate-spin text-gray-600" size={16} /></div>
              : tasks.length === 0
                ? <p className="text-xs text-gray-600 py-2">No maintenance tasks yet. <button onClick={() => setShowAddTask(true)} className="text-teal-500 hover:underline">Add one</button></p>
                : <div className="space-y-1 mt-1">
                    {tasks.map(task => (
                      <TaskRow key={task.id} task={task} equipId={equip.id} userId={userId} onRefresh={loadTasks} />
                    ))}
                  </div>
            }
          </div>
        </div>
      )}

      {confirm && <ConfirmModal message={`Delete "${equip.name}" and all its tasks?`} onConfirm={doDelete} onCancel={() => setConfirm(false)} />}
      {showAddTask && (
        <AddTaskModal equipId={equip.id} userId={userId}
          onClose={() => setShowAddTask(false)} onSave={loadTasks} />
      )}
    </div>
  );
}

function TaskRow({ task, equipId, userId, onRefresh }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [completeNotes, setCompleteNotes] = useState("");
  const [log, setLog] = useState([]);
  const [loadingLog, setLoadingLog] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const due = taskDueStatus(task.next_due_at);

  const loadLog = async () => {
    setLoadingLog(true);
    try {
      const res = await fetch(`${API}/equipment/tasks/${task.id}/log?limit=10`).then(r => r.json());
      setLog(res.log || []);
    } catch (e) { console.error(e); }
    setLoadingLog(false);
  };

  const toggleExpand = () => {
    if (!expanded) loadLog();
    setExpanded(e => !e);
  };

  const markDone = async () => {
    setSaving(true);
    await fetch(`${API}/equipment/tasks/${task.id}/complete`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: completeNotes, created_by: userId || "" }),
    });
    setSaving(false); setCompleting(false); setCompleteNotes(""); onRefresh();
  };

  const saveTask = async () => {
    setSaving(true);
    await fetch(`${API}/equipment/tasks/${task.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setSaving(false); setEditing(false); onRefresh();
  };

  const doDelete = async () => {
    await fetch(`${API}/equipment/tasks/${task.id}`, { method: "DELETE" });
    setConfirm(false); onRefresh();
  };

  const startEdit = (e) => {
    e.stopPropagation();
    setForm({ name: task.name, description: task.description, interval_days: task.interval_days ?? "",
               next_due_at: task.next_due_at || "", notes: task.notes });
    setEditing(true);
  };

  return (
    <div className={`rounded border ${due?.overdue ? "border-red-900/40 bg-red-950/20" : "border-gray-700/30 bg-gray-900/20"}`}>
      <div className="flex items-center gap-2 px-2.5 py-2">
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="space-y-1.5">
              <div className="grid grid-cols-2 gap-1.5">
                <Field label="Task name"><input value={form.name || ""} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} /></Field>
                <Field label="Interval (days)"><input type="number" value={form.interval_days ?? ""} onChange={e => setForm(f => ({...f, interval_days: e.target.value ? parseInt(e.target.value) : null}))} className={inp} placeholder="e.g. 30" /></Field>
                <Field label="Next due"><input type="date" value={form.next_due_at || ""} onChange={e => setForm(f => ({...f, next_due_at: e.target.value}))} className={inp} /></Field>
                <Field label="Description"><input value={form.description || ""} onChange={e => setForm(f => ({...f, description: e.target.value}))} className={inp} /></Field>
              </div>
              <Field label="Notes"><input value={form.notes || ""} onChange={e => setForm(f => ({...f, notes: e.target.value}))} className={inp} /></Field>
              <div className="flex gap-1.5 justify-end">
                <button onClick={() => setConfirm(true)} className={btnDanger}><Trash2 size={12} /></button>
                <button onClick={() => setEditing(false)} className={btnSecondary}>Cancel</button>
                <button onClick={saveTask} disabled={saving} className={btnPrimary}><Save size={12} />{saving ? "…" : "Save"}</button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-gray-300">{task.name}</span>
              {task.interval_days && (
                <span className="text-xs text-gray-600 bg-gray-800/60 rounded px-1.5 py-0.5">{fmtInterval(task.interval_days)}</span>
              )}
              {due && <span className={`text-xs ${due.cls}`}>{due.label}</span>}
              {task.last_done_at && <span className="text-xs text-gray-600">last: {fmtDate(task.last_done_at)}</span>}
            </div>
          )}
        </div>
        {!editing && (
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={toggleExpand} className="p-1 text-gray-600 hover:text-gray-400" title="History">
              <History size={13} />
            </button>
            <button onClick={startEdit} className="p-1 text-gray-600 hover:text-gray-400" title="Edit">
              <Edit3 size={13} />
            </button>
            <button onClick={() => setCompleting(c => !c)}
              className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${completing ? "bg-teal-700 text-white" : "bg-teal-900/40 text-teal-400 hover:bg-teal-800/60"}`}>
              <CheckCircle2 size={13} />Done
            </button>
          </div>
        )}
      </div>

      {completing && (
        <div className="px-2.5 pb-2 flex items-center gap-2 border-t border-gray-700/30 pt-1.5">
          <input value={completeNotes} onChange={e => setCompleteNotes(e.target.value)}
            placeholder="Notes (optional)" className={`${inp} flex-1 text-xs`} />
          <button onClick={markDone} disabled={saving} className={btnPrimary}>
            <CheckCircle2 size={12} />{saving ? "…" : "Mark Done"}
          </button>
          <button onClick={() => setCompleting(false)} className={btnSecondary}>Cancel</button>
        </div>
      )}

      {expanded && (
        <div className="px-2.5 pb-2 border-t border-gray-700/20 pt-1.5">
          {loadingLog
            ? <div className="flex justify-center py-2"><Loader2 className="animate-spin text-gray-600" size={13} /></div>
            : log.length === 0
              ? <p className="text-xs text-gray-600">No completions logged yet.</p>
              : <div className="space-y-0.5">
                  {log.map(entry => (
                    <div key={entry.id} className="flex items-center gap-2 text-xs text-gray-500">
                      <CheckCircle2 size={11} className="text-teal-700 shrink-0" />
                      <span>{fmtDate(entry.completed_at)}</span>
                      {entry.notes && <span className="text-gray-600">— {entry.notes}</span>}
                    </div>
                  ))}
                </div>
          }
        </div>
      )}
      {confirm && <ConfirmModal message={`Delete task "${task.name}"?`} onConfirm={doDelete} onCancel={() => setConfirm(false)} />}
    </div>
  );
}

function AddEquipmentModal({ members, userId, defaultMemberId, onClose, onSave }) {
  const [form, setForm] = useState({
    member_id: defaultMemberId || members[0]?.id || "",
    name: "", description: "", brand: "", model: "", serial_no: "", notes: "",
    created_by: userId || "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.member_id || !form.name.trim()) return;
    setSaving(true);
    await fetch(`${API}/equipment`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setSaving(false); onClose(); onSave();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[440px] space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Add Equipment</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="For">
            <select value={form.member_id} onChange={e => setForm(f => ({...f, member_id: e.target.value}))} className={inp}>
              {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </Field>
          <Field label="Equipment Name">
            <input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} placeholder="CPAP Machine" />
          </Field>
          <Field label="Brand">
            <input value={form.brand} onChange={e => setForm(f => ({...f, brand: e.target.value}))} className={inp} placeholder="ResMed" />
          </Field>
          <Field label="Model">
            <input value={form.model} onChange={e => setForm(f => ({...f, model: e.target.value}))} className={inp} placeholder="AirSense 11" />
          </Field>
          <Field label="Serial #">
            <input value={form.serial_no} onChange={e => setForm(f => ({...f, serial_no: e.target.value}))} className={inp} />
          </Field>
        </div>
        <Field label="Description">
          <input value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))} className={inp} />
        </Field>
        <Field label="Notes">
          <textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.member_id || !form.name.trim() || saving} className={btnPrimary}>
            {saving ? "Saving…" : "Add Equipment"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddTaskModal({ equipId, userId, onClose, onSave }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    equipment_id: equipId, name: "", description: "",
    interval_days: "", next_due_at: today, notes: "", created_by: userId || "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    const payload = {
      ...form,
      interval_days: form.interval_days ? parseInt(form.interval_days) : null,
      next_due_at: form.next_due_at || null,
    };
    await fetch(`${API}/equipment/${equipId}/tasks`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSaving(false); onClose(); onSave();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[400px] space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Add Maintenance Task</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Task Name">
            <input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inp} placeholder="Replace filter" />
          </Field>
          <Field label="Interval (days)">
            <input type="number" value={form.interval_days} onChange={e => setForm(f => ({...f, interval_days: e.target.value}))} className={inp} placeholder="30" />
          </Field>
          <Field label="Next Due">
            <input type="date" value={form.next_due_at} onChange={e => setForm(f => ({...f, next_due_at: e.target.value}))} className={inp} />
          </Field>
          <Field label="Description">
            <input value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))} className={inp} />
          </Field>
        </div>
        <Field label="Notes">
          <input value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} className={inp} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.name.trim() || saving} className={btnPrimary}>
            {saving ? "Saving…" : "Add Task"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddApptModal({ members, userId, defaultMemberId, onClose, onSave }) {
  const nowLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
  const [form, setForm] = useState({
    member_id: defaultMemberId || members[0]?.id || "",
    title: "",
    appointment_at: nowLocal,
    provider: "",
    location: "",
    appointment_type: "visit",
    notes: "",
    created_by: userId || "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.member_id || !form.title.trim() || !form.appointment_at) return;
    setSaving(true);
    const payload = { ...form, appointment_at: new Date(form.appointment_at).toISOString() };
    await fetch(`${API}/appointments`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSaving(false); onClose(); onSave();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 w-[480px] space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-base font-bold text-gray-200">Schedule Appointment</h3>
        <div className="grid grid-cols-2 gap-2">
          <Field label="For">
            <select value={form.member_id} onChange={e => setForm(f => ({...f, member_id: e.target.value}))} className={inp}>
              {members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </Field>
          <Field label="Type">
            <select value={form.appointment_type} onChange={e => setForm(f => ({...f, appointment_type: e.target.value}))} className={inp}>
              {APPT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Title / Description">
            <input value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} className={inp} placeholder="Annual Physical" />
          </Field>
          <Field label="Date & Time">
            <input type="datetime-local" value={form.appointment_at} onChange={e => setForm(f => ({...f, appointment_at: e.target.value}))} className={inp} />
          </Field>
          <Field label="Provider / Doctor">
            <input value={form.provider} onChange={e => setForm(f => ({...f, provider: e.target.value}))} className={inp} placeholder="Dr. Smith" />
          </Field>
          <Field label="Location / Clinic">
            <input value={form.location} onChange={e => setForm(f => ({...f, location: e.target.value}))} className={inp} placeholder="Family Health Clinic" />
          </Field>
        </div>
        <Field label="Notes">
          <textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={2} className={inp} />
        </Field>
        <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-900/40 rounded px-2 py-1.5">
          <Bell size={12} className="text-teal-500 shrink-0" />
          Reminders will be sent 24 hours before and 2 hours before this appointment.
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} disabled={!form.member_id || !form.title.trim() || !form.appointment_at || saving} className={btnPrimary}>
            {saving ? "Saving…" : "Schedule"}
          </button>
        </div>
      </div>
    </div>
  );
}
