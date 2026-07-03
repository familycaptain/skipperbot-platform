import { useState, useEffect, useCallback, useRef } from "react";
import {
  Wrench, ShoppingCart, Shield, MapPin, HardHat, Settings,
  CheckCircle, Plus, ChevronDown, ChevronUp, X, Search,
  Clock, AlertCircle, CalendarCheck, RotateCcw, Trash2, Edit2,
  AlertTriangle, Camera, Image as ImageIcon,
  Star, Phone, Mail,
} from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

/**
 * Home App — combined hub for home-related features.
 *
 * Tabs:
 *   Maintenance  – ad hoc tasks, recurring reminders
 *   Appliances   – purchase history
 *   Insurance    – valuations, coverage, asset list
 *   Contractors  – electricians, plumbers, roofers, painters, etc.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey, isActive
 */

const TABS = [
  { id: "maintenance", label: "Maintenance", icon: Wrench },
  { id: "issues",      label: "Issues",      icon: AlertTriangle },
  { id: "appliances",  label: "Appliances",  icon: ShoppingCart },
  { id: "insurance",   label: "Insurance",   icon: Shield },
  { id: "contractors", label: "Contractors", icon: HardHat },
];

export default function HomeApp({ appId, userId, context = {}, onTitle, onOpenApp, refreshKey, isActive }) {
  const initialTab = TABS.some((tab) => tab.id === context.tab) ? context.tab : "maintenance";
  const [activeTab, setActiveTab] = useState(initialTab);

  return (
    <div className="flex flex-col h-full w-full">
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-3 h-10 surface-panel border-b border-subtle shrink-0 overflow-x-auto">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md whitespace-nowrap transition-colors ${
                active
                  ? "bg-indigo-600 text-on-accent"
                  : "text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"
              }`}
            >
              <Icon size={13} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 flex flex-col min-h-0">
        {activeTab === "maintenance" && (
          <MaintenanceTab userId={userId} />
        )}
        {activeTab === "issues" && (
          <HomeIssuesTab userId={userId} />
        )}
        {activeTab === "appliances" && (
          <AppliancesTab userId={userId} />
        )}
        {activeTab === "insurance" && (
          <InsuranceTab userId={userId} />
        )}
        {activeTab === "contractors" && (
          <ContractorsTab userId={userId} />
        )}
      </div>
    </div>
  );
}

/* ── Maintenance Tab helpers ── */

function daysDiff(dateStr) {
  if (!dateStr) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const due = new Date(dateStr + "T00:00:00"); due.setHours(0, 0, 0, 0);
  return Math.round((due - today) / 86400000);
}

function fmtDate(dateStr) {
  if (!dateStr) return "—";
  return new Date(dateStr + "T00:00:00").toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

function fmtRelative(dateStr) {
  const diff = daysDiff(dateStr);
  if (diff == null) return "—";
  const ago = -diff;
  if (ago < 0) return fmtDate(dateStr);
  if (ago === 0) return "today";
  if (ago === 1) return "yesterday";
  if (ago < 30) return `${ago} days ago`;
  if (ago < 365) { const m = Math.round(ago / 30); return `${m} month${m === 1 ? "" : "s"} ago`; }
  const y = Math.round(ago / 365); return `${y} year${y === 1 ? "" : "s"} ago`;
}

function intervalLabel(days) {
  if (!days) return "";
  if (days === 1) return "daily";
  if (days === 7) return "weekly";
  if (days === 14) return "bi-weekly";
  if (days === 30 || days === 31) return "monthly";
  if (days === 60) return "every 2 months";
  if (days === 90 || days === 91) return "quarterly";
  if (days === 180) return "every 6 months";
  if (days === 365) return "yearly";
  return `every ${days}d`;
}

function taskStatus(task) {
  if (!task.next_due_at) return "none";
  const diff = daysDiff(task.next_due_at);
  if (diff < 0) return "overdue";
  if (diff <= 7) return "due_soon";
  return "ok";
}

const STATUS_STYLES = {
  overdue:  { bg: "bg-red-500/10 border-red-500/30",  badge: "bg-red-500/20 text-red-400",  dot: "bg-red-500"  },
  due_soon: { bg: "bg-amber-500/10 border-amber-500/30", badge: "bg-amber-500/20 text-amber-400", dot: "bg-amber-400" },
  ok:       { bg: "surface-card border-subtle",  badge: "bg-green-500/20 text-green-400", dot: "bg-green-500" },
  none:     { bg: "surface-card border-subtle",  badge: "surface-raised text-muted",   dot: "surface-raised" },
};

const COLOR_OPTIONS = {
  blue:   "bg-blue-500/20 text-blue-400",
  cyan:   "bg-[var(--ds-accent)] text-accent",
  green:  "bg-green-500/20 text-green-400",
  orange: "bg-orange-500/20 text-orange-400",
  purple: "bg-purple-500/20 text-purple-400",
  red:    "bg-red-500/20 text-red-400",
  amber:  "bg-amber-500/20 text-amber-400",
  slate:  "surface-raised text-default",
};

const COLOR_DOTS = {
  blue:   "bg-blue-500",
  cyan:   "bg-[var(--ds-accent)]",
  green:  "bg-green-500",
  orange: "bg-orange-500",
  purple: "bg-purple-500",
  red:    "bg-red-500",
  amber:  "bg-amber-400",
  slate:  "surface-raised",
};

const CATEGORY_COLORS = {
  "HVAC":         COLOR_OPTIONS.blue,
  "Plumbing":     COLOR_OPTIONS.cyan,
  "Exterior":     COLOR_OPTIONS.green,
  "Electrical":   COLOR_OPTIONS.orange,
  "Pest Control": COLOR_OPTIONS.purple,
  "General":      COLOR_OPTIONS.slate,
};

function CatBadge({ category, colorCls }) {
  const cls = colorCls || CATEGORY_COLORS[category] || "surface-raised text-default";
  return <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${cls}`}>{category || "General"}</span>;
}

/* ── Add Task Form ── */
function AddTaskForm({ onSave, onCancel, catObjects = [] }) {
  const [form, setForm] = useState({
    name: "", category: "General", task_type: "recurring",
    interval_days: "", next_due_at: "", description: "", notes: "",
  });
  const [saving, setSaving] = useState(false);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        category: form.category || "General",
        task_type: form.task_type,
        description: form.description.trim(),
        notes: form.notes.trim(),
        interval_days: form.task_type === "recurring" && form.interval_days ? parseInt(form.interval_days) : null,
        next_due_at: form.next_due_at || null,
      };
      const res = await fetch("/api/apps/home/maintenance/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      onSave(await res.json());
    } catch (err) {
      alert("Failed to create task: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  const cats = catObjects.length > 0 ? catObjects.map(c => c.name) : ["General", "HVAC", "Plumbing", "Exterior", "Electrical", "Pest Control"];
  const inputCls = "w-full surface-panel border border-subtle rounded px-2.5 py-1.5 text-sm text-default focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={handleSubmit} className="surface-card border border-subtle rounded-lg p-4 space-y-3">
      <p className="text-xs font-semibold text-muted uppercase tracking-wide">New Maintenance Task</p>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <input className={inputCls} placeholder="Task name (e.g. Clean A/C filter)" value={form.name}
            onChange={e => set("name", e.target.value)} autoFocus required />
        </div>
        <div>
          <select className={inputCls} value={form.category} onChange={e => set("category", e.target.value)}>
            {cats.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <select className={inputCls} value={form.task_type} onChange={e => set("task_type", e.target.value)}>
            <option value="recurring">Recurring</option>
            <option value="adhoc">One-time</option>
          </select>
        </div>
        {form.task_type === "recurring" && (
          <div>
            <input className={inputCls} type="number" min="1" placeholder="Repeat every N days"
              value={form.interval_days} onChange={e => set("interval_days", e.target.value)} />
          </div>
        )}
        <div>
          <label className="block text-xs text-faint mb-1">{form.task_type === "recurring" ? "First due date" : "Due date"}</label>
          <input className={inputCls} type="date" value={form.next_due_at} onChange={e => set("next_due_at", e.target.value)} />
        </div>
        <div className="col-span-2">
          <input className={inputCls} placeholder="Description (optional)" value={form.description}
            onChange={e => set("description", e.target.value)} />
        </div>
      </div>
      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel}
          className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)] transition-colors">
          Cancel
        </button>
        <button type="submit" disabled={saving || !form.name.trim()}
          className="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded transition-colors">
          {saving ? "Saving..." : "Add Task"}
        </button>
      </div>
    </form>
  );
}

/* ── Edit Task Form (inline) ── */
function EditTaskForm({ task, onSave, onCancel, catObjects = [] }) {
  const [form, setForm] = useState({
    name: task.name || "",
    category: task.category || "General",
    task_type: task.task_type || "recurring",
    interval_days: task.interval_days || "",
    next_due_at: task.next_due_at || "",
    description: task.description || "",
    notes: task.notes || "",
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        category: form.category,
        task_type: form.task_type,
        interval_days: form.task_type === "recurring" && form.interval_days ? parseInt(form.interval_days) : null,
        next_due_at: form.next_due_at || null,
        description: form.description.trim(),
        notes: form.notes.trim(),
      };
      const res = await fetch(`/api/apps/home/maintenance/tasks/${task.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      onSave(await res.json());
    } catch (err) {
      alert("Failed to update: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  const cats = catObjects.length > 0 ? catObjects.map(c => c.name) : ["General", "HVAC", "Plumbing", "Exterior", "Electrical", "Pest Control"];
  const inputCls = "w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={handleSubmit} className="mt-2 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <div className="col-span-2">
          <input className={inputCls} value={form.name} onChange={e => set("name", e.target.value)} required />
        </div>
        <select className={inputCls} value={form.category} onChange={e => set("category", e.target.value)}>
          {cats.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className={inputCls} value={form.task_type} onChange={e => set("task_type", e.target.value)}>
          <option value="recurring">Recurring</option>
          <option value="adhoc">One-time</option>
        </select>
        {form.task_type === "recurring" && (
          <input className={inputCls} type="number" min="1" placeholder="Interval (days)"
            value={form.interval_days} onChange={e => set("interval_days", e.target.value)} />
        )}
        <div>
          <label className="block text-xs text-faint mb-0.5">Next due</label>
          <input className={inputCls} type="date" value={form.next_due_at} onChange={e => set("next_due_at", e.target.value)} />
        </div>
        <div className="col-span-2">
          <input className={inputCls} placeholder="Description" value={form.description} onChange={e => set("description", e.target.value)} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button type="submit" disabled={saving}
          className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded">
          {saving ? "Saving..." : "Save"}
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
      </div>
    </form>
  );
}

/* ── Done confirmation popover ── */
function DoneModal({ task, onConfirm, onCancel }) {
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleConfirm() {
    setSaving(true);
    try {
      const res = await fetch(`/api/apps/home/maintenance/tasks/${task.id}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: notes.trim() }),
      });
      if (!res.ok) throw new Error(await res.text());
      onConfirm(await res.json());
    } catch (err) {
      alert("Failed: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 surface-overlay flex items-center justify-center z-50">
      <div className="surface-card border border-subtle rounded-xl p-5 w-80 shadow-2xl">
        <p className="text-sm font-medium text-default mb-1">Mark as done</p>
        <p className="text-xs text-muted mb-3">"{task.name}"</p>
        <textarea
          className="w-full surface-panel border border-subtle rounded px-2.5 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500 resize-none"
          rows={2} placeholder="Notes (optional, e.g. 'Used MERV-13 filter')"
          value={notes} onChange={e => setNotes(e.target.value)} autoFocus
        />
        <div className="flex items-center justify-end gap-2 mt-3">
          <button onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
          <button onClick={handleConfirm} disabled={saving}
            className="px-4 py-1.5 text-xs bg-green-600 hover:bg-green-500 disabled:opacity-50 text-on-accent rounded flex items-center gap-1.5">
            <CheckCircle size={12} />
            {saving ? "Saving..." : "Done"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Task card with expandable log ── */
function TaskCard({ task, expanded, onToggle, onComplete, onUpdate, onDelete, catColorMap = {}, catObjects = [] }) {
  const status = taskStatus(task);
  const styles = STATUS_STYLES[status] || STATUS_STYLES.none;
  const diff = task.next_due_at ? daysDiff(task.next_due_at) : null;
  const [editing, setEditing] = useState(false);

  function dueLabel() {
    if (diff === null) return "";
    if (diff < 0) return `${Math.abs(diff)}d overdue`;
    if (diff === 0) return "due today";
    if (diff === 1) return "due tomorrow";
    return `due in ${diff}d`;
  }

  return (
    <div className={`border rounded-lg overflow-hidden transition-all ${styles.bg}`}>
      <div className="flex items-center gap-3 px-3 py-2.5">
        <span className={`w-2 h-2 rounded-full shrink-0 ${styles.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-default truncate">{task.name}</span>
            <CatBadge category={task.category} colorCls={catColorMap[task.category]} />
            {task.task_type === "recurring" && task.interval_days && (
              <span className="text-xs text-faint flex items-center gap-1">
                <RotateCcw size={10} />{intervalLabel(task.interval_days)}
              </span>
            )}
            {task.task_type === "adhoc" && (
              <span className="text-xs text-faint">one-time</span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-faint">
            {task.last_done_at && <span>Last: {fmtDate(task.last_done_at)}</span>}
            {task.next_due_at && (
              <span className={diff !== null && diff < 0 ? "text-red-400 font-medium" : diff !== null && diff <= 7 ? "text-amber-400" : ""}>
                {dueLabel()}
              </span>
            )}
            {!task.next_due_at && !task.last_done_at && <span className="text-faint">No due date</span>}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); onComplete(task); }}
            className="flex items-center gap-1 px-2.5 py-1 text-xs bg-green-600/20 hover:bg-green-600/40 text-green-400 rounded transition-colors border border-green-600/30"
            title="Mark as done"
          >
            <CheckCircle size={12} /> Done
          </button>
          <button
            onClick={() => { setEditing(false); onToggle(); }}
            className="p-1.5 text-faint hover:text-[var(--ds-text)] rounded transition-colors"
            title={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-subtle px-3 py-3">
          {editing ? (
            <EditTaskForm
              task={task}
              onSave={(updated) => { onUpdate(updated); setEditing(false); }}
              onCancel={() => setEditing(false)}
              catObjects={catObjects}
            />
          ) : (
            <>
              {task.description && (
                <p className="text-xs text-muted mb-3">{task.description}</p>
              )}
              <div className="flex items-center gap-2 mb-3">
                <button onClick={() => setEditing(true)}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] border border-subtle hover:border-[var(--ds-border)] rounded transition-colors">
                  <Edit2 size={11} /> Edit
                </button>
                <button onClick={() => onDelete(task.id)}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-red-500 hover:text-red-400 border border-red-900/40 hover:border-red-700/60 rounded transition-colors">
                  <Trash2 size={11} /> Delete
                </button>
              </div>
              <CompletionLog taskId={task.id} log={task.log || []} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Completion log ── */
function CompletionLog({ taskId, log }) {
  const [entries, setEntries] = useState(log || []);
  const [loaded, setLoaded] = useState(log && log.length > 0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setEntries(log || []);
    setLoaded(true);
  }, [log]);

  if (!loaded) {
    return (
      <button onClick={async () => {
        setLoading(true);
        const res = await fetch(`/api/apps/home/maintenance/tasks/${taskId}/log`);
        const data = await res.json();
        setEntries(data.log || []);
        setLoaded(true);
        setLoading(false);
      }} className="text-xs text-indigo-400 hover:text-indigo-300">
        {loading ? "Loading..." : "Show completion history"}
      </button>
    );
  }

  if (entries.length === 0) {
    return <p className="text-xs text-faint italic">No completions logged yet.</p>;
  }

  return (
    <div>
      <p className="text-xs font-semibold text-faint uppercase tracking-wide mb-2">
        Completion History ({entries.length})
      </p>
      <div className="space-y-1">
        {entries.map((e) => (
          <div key={e.id} className="flex items-start gap-2 text-xs">
            <CheckCircle size={12} className="text-green-500 mt-0.5 shrink-0" />
            <div>
              <span className="text-default">{fmtDate(e.completed_at)}</span>
              {e.completed_by && <span className="text-faint"> · {e.completed_by}</span>}
              {e.notes && <span className="text-muted"> — {e.notes}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Main Maintenance Tab ── */
function MaintenanceTab({ userId }) {
  const [tasks, setTasks] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState("All");
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [confirmDone, setConfirmDone] = useState(null);
  const [catObjects, setCatObjects] = useState([]);
  const [showManage, setShowManage] = useState(false);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      else if (filterCat !== "All") params.set("category", filterCat);
      const res = await fetch(`/api/apps/home/maintenance/tasks?${params}`);
      const data = await res.json();
      setTasks(data.tasks || []);
      if (data.categories?.length) {
        setCategories(["All", ...data.categories]);
      } else if (categories.length === 0) {
        setCategories(["All"]);
      }
    } finally {
      setLoading(false);
    }
  }, [search, filterCat]);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);

  useEffect(() => {
    fetch("/api/apps/home/maintenance/categories")
      .then(r => r.json())
      .then(d => setCatObjects(d.categories || []));
  }, []);

  async function handleDelete(taskId) {
    if (!confirm("Delete this task and all its history?")) return;
    await fetch(`/api/apps/home/maintenance/tasks/${taskId}`, { method: "DELETE" });
    setTasks(prev => prev.filter(t => t.id !== taskId));
    if (expandedId === taskId) setExpandedId(null);
  }

  function handleUpdate(updated) {
    setTasks(prev => prev.map(t => t.id === updated.id ? { ...t, ...updated } : t));
  }

  function handleDoneResult(result) {
    const { task } = result;
    if (task) {
      if (!task.active) {
        setTasks(prev => prev.filter(t => t.id !== task.id));
      } else {
        setTasks(prev => prev.map(t => t.id === task.id ? { ...t, ...task } : t));
      }
    }
    setConfirmDone(null);
  }

  const catColorMap = Object.fromEntries(
    catObjects.map(c => [c.name, COLOR_OPTIONS[c.color] || COLOR_OPTIONS.slate])
  );

  // Group tasks by status
  const overdue = tasks.filter(t => taskStatus(t) === "overdue");
  const dueSoon = tasks.filter(t => taskStatus(t) === "due_soon");
  const onSchedule = tasks.filter(t => taskStatus(t) === "ok");
  const noDue = tasks.filter(t => taskStatus(t) === "none");

  function StatusGroup({ label, icon: Icon, color, items }) {
    if (items.length === 0) return null;
    return (
      <div className="mb-3">
        <div className={`flex items-center gap-1.5 text-xs font-semibold mb-1.5 ${color}`}>
          <Icon size={12} /> {label} ({items.length})
        </div>
        <div className="space-y-1.5">
          {items.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              expanded={expandedId === task.id}
              onToggle={() => setExpandedId(prev => prev === task.id ? null : task.id)}
              onComplete={t => setConfirmDone(t)}
              onUpdate={handleUpdate}
              onDelete={handleDelete}
              catColorMap={catColorMap}
              catObjects={catObjects}
            />
          ))}
        </div>
      </div>
    );
  }

  const allCategories = categories.length > 1 ? categories : ["All"];

  return (
    <div className="flex flex-col h-full">
      {/* Search + Add bar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle shrink-0">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            className="w-full surface-panel border border-subtle rounded pl-7 pr-2.5 py-1.5 text-xs text-default placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            placeholder="Search tasks..."
            value={search}
            onChange={e => { setSearch(e.target.value); setFilterCat("All"); }}
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]">
              <X size={12} />
            </button>
          )}
        </div>
        <button
          onClick={() => { setShowAdd(v => !v); setShowManage(false); }}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${showAdd ? "surface-raised text-on-accent" : "bg-indigo-600 hover:bg-indigo-500 text-on-accent"}`}
        >
          {showAdd ? <X size={13} /> : <Plus size={13} />}
          {showAdd ? "Cancel" : "Add Task"}
        </button>
        <button
          onClick={() => { setShowManage(v => !v); setShowAdd(false); }}
          className={`p-1.5 rounded transition-colors ${showManage ? "surface-raised text-indigo-400" : "text-faint hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"}`}
          title="Manage categories"
        >
          <Settings size={14} />
        </button>
      </div>

      {/* Category filter */}
      {!search && allCategories.length > 1 && (
        <div className="flex items-center gap-1 px-3 py-1.5 border-b border-subtle shrink-0 overflow-x-auto">
          {allCategories.map(cat => (
            <button
              key={cat}
              onClick={() => setFilterCat(cat)}
              className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
                filterCat === cat
                  ? "bg-indigo-600 text-on-accent"
                  : "text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 min-h-0">
        {showManage ? (
          <CategoriesManager
            catObjects={catObjects}
            onChanged={(updated) => setCatObjects(updated)}
          />
        ) : (
          <div className="space-y-1">
            {/* Add form */}
            {showAdd && (
              <div className="mb-4">
                <AddTaskForm
                  onSave={(newTask) => {
                    setTasks(prev => [newTask, ...prev]);
                    setShowAdd(false);
                    fetchTasks();
                  }}
                  onCancel={() => setShowAdd(false)}
                  catObjects={catObjects}
                />
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center h-32 text-faint text-sm">Loading...</div>
            ) : tasks.length === 0 ? (
              <PristineEmpty
                appId="home"
                blurb={getAppManifest("home")?.heroes?.maintenance}
                records={tasks}
                loading={loading}
                filterActive={!!search.trim() || filterCat !== "All"}
                fallback={
                  <div className="flex flex-col items-center justify-center h-48 text-faint">
                    <Wrench size={32} className="text-default mb-3" />
                    <p className="text-sm font-medium text-muted">
                      {search ? `No tasks matching "${search}"` : "No maintenance tasks yet"}
                    </p>
                    <p className="text-xs mt-1 text-faint">
                      {!search && 'Click "Add Task" to get started'}
                    </p>
                  </div>
                }
              />
            ) : (
              <>
                <StatusGroup label="Overdue" icon={AlertCircle} color="text-red-400"
                  items={overdue} />
                <StatusGroup label="Due this week" icon={Clock} color="text-amber-400"
                  items={dueSoon} />
                <StatusGroup label="On schedule" icon={CalendarCheck} color="text-green-400"
                  items={onSchedule} />
                <StatusGroup label="No due date" icon={Wrench} color="text-muted"
                  items={noDue} />
              </>
            )}
          </div>
        )}
      </div>

      {/* Done confirmation modal */}
      {confirmDone && (
        <DoneModal
          task={confirmDone}
          onConfirm={handleDoneResult}
          onCancel={() => setConfirmDone(null)}
        />
      )}
    </div>
  );
}

/* ── Color picker (dot palette) ── */
function ColorPicker({ value, onChange }) {
  return (
    <div className="flex items-center gap-1 shrink-0">
      {Object.entries(COLOR_DOTS).map(([key, dotCls]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          className={`w-4 h-4 rounded-full ${dotCls} transition-transform ${
            value === key
              ? "ring-2 ring-white ring-offset-1 ring-offset-slate-900 scale-110"
              : "opacity-60 hover:opacity-100"
          }`}
          title={key}
        />
      ))}
    </div>
  );
}

/* ── Categories Manager ── */
function CategoriesManager({ catObjects, onChanged }) {
  const [cats, setCats] = useState(catObjects);
  const [editId, setEditId] = useState(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("slate");
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState("slate");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/api/apps/home/maintenance/categories")
      .then(r => r.json())
      .then(d => {
        const updated = d.categories || [];
        setCats(updated);
        onChanged(updated);
      });
  }, []);

  async function refresh() {
    const d = await fetch("/api/apps/home/maintenance/categories").then(r => r.json());
    const updated = d.categories || [];
    setCats(updated);
    onChanged(updated);
  }

  async function handleAdd() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const res = await fetch("/api/apps/home/maintenance/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), color: newColor }),
      });
      if (!res.ok) throw new Error(await res.text());
      await refresh();
      setNewName("");
      setNewColor("slate");
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveEdit(catId) {
    if (!editName.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/apps/home/maintenance/categories/${catId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName.trim(), color: editColor }),
      });
      if (!res.ok) throw new Error(await res.text());
      await refresh();
      setEditId(null);
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(catId, catName) {
    if (!confirm(`Delete category "${catName}"? Tasks using it will keep their category value.`)) return;
    await fetch(`/api/apps/home/maintenance/categories/${catId}`, { method: "DELETE" });
    const newCats = cats.filter(c => c.id !== catId);
    setCats(newCats);
    onChanged(newCats);
  }

  const inCls = "surface-panel border border-subtle rounded px-2.5 py-1.5 text-sm text-default focus:outline-none focus:border-indigo-500";

  return (
    <div>
      <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">Manage Categories</p>

      <div className="space-y-1.5 mb-5">
        {cats.map(cat => (
          <div key={cat.id} className="flex items-center gap-2 surface-card border border-subtle rounded-lg px-3 py-2">
            <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${COLOR_DOTS[cat.color] || "surface-raised"}`} />
            {editId === cat.id ? (
              <>
                <input
                  className={`flex-1 min-w-0 ${inCls} py-1 text-sm`}
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") handleSaveEdit(cat.id); if (e.key === "Escape") setEditId(null); }}
                  autoFocus
                />
                <ColorPicker value={editColor} onChange={setEditColor} />
                <button
                  onClick={() => handleSaveEdit(cat.id)}
                  disabled={saving || !editName.trim()}
                  className="px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-on-accent rounded"
                >
                  Save
                </button>
                <button onClick={() => setEditId(null)} className="p-1 text-faint hover:text-[var(--ds-text)]">
                  <X size={13} />
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 text-sm text-default">{cat.name}</span>
                <button
                  onClick={() => { setEditId(cat.id); setEditName(cat.name); setEditColor(cat.color || "slate"); }}
                  className="p-1 text-faint hover:text-[var(--ds-text)] rounded"
                  title="Edit"
                >
                  <Edit2 size={13} />
                </button>
                <button
                  onClick={() => handleDelete(cat.id, cat.name)}
                  className="p-1 text-red-500/60 hover:text-red-400 rounded"
                  title="Delete"
                >
                  <Trash2 size={13} />
                </button>
              </>
            )}
          </div>
        ))}
        {cats.length === 0 && (
          <p className="text-xs text-faint italic px-1">No categories yet.</p>
        )}
      </div>

      {/* Add form */}
      <div className="border-t border-subtle pt-4">
        <p className="text-xs font-medium text-faint mb-2">Add Category</p>
        <div className="flex items-center gap-2">
          <input
            className={`flex-1 min-w-0 ${inCls}`}
            placeholder="Category name..."
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleAdd()}
          />
          <ColorPicker value={newColor} onChange={setNewColor} />
          <button
            onClick={handleAdd}
            disabled={saving || !newName.trim()}
            className="flex items-center gap-1 px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-on-accent rounded whitespace-nowrap"
          >
            <Plus size={12} /> Add
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Appliance warranty helpers ── */
function warrantyStatus(dateStr) {
  if (!dateStr) return "none";
  const diff = daysDiff(dateStr);
  if (diff < 0) return "expired";
  if (diff <= 30) return "soon";
  return "covered";
}

const WARRANTY_STYLES = {
  expired: { badge: "bg-red-500/20 text-red-400",     label: "Warranty expired" },
  soon:    { badge: "bg-amber-500/20 text-amber-400", label: "Expires soon" },
  covered: { badge: "bg-green-500/20 text-green-400", label: "Under warranty" },
  none:    { badge: "surface-raised text-muted",      label: "No warranty" },
};

function WarrantyBadge({ warranty_expires }) {
  const status = warrantyStatus(warranty_expires);
  if (status === "none") return null;
  const s = WARRANTY_STYLES[status];
  const suffix = warranty_expires ? ` · ${fmtDate(warranty_expires)}` : "";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}>
      {s.label}{status !== "expired" ? suffix : ""}
    </span>
  );
}

function fmtPrice(val) {
  if (val === null || val === undefined || val === "") return "";
  const n = Number(val);
  if (Number.isNaN(n)) return "";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ── Add Appliance Form ── */
function AddApplianceForm({ types = [], userId, onSave, onCancel }) {
  const [form, setForm] = useState({
    name: "", appliance_type: "General", brand: "", model: "", serial_number: "",
    location: "", purchase_date: "", purchase_price: "", warranty_expires: "", notes: "",
  });
  const [pendingPhoto, setPendingPhoto] = useState(null);
  const [saving, setSaving] = useState(false);
  const photoRef = useRef();
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        appliance_type: form.appliance_type.trim() || "General",
        brand: form.brand.trim(),
        model: form.model.trim(),
        serial_number: form.serial_number.trim(),
        location: form.location.trim(),
        purchase_date: form.purchase_date || null,
        purchase_price: form.purchase_price !== "" ? parseFloat(form.purchase_price) : null,
        warranty_expires: form.warranty_expires || null,
        notes: form.notes.trim(),
        created_by: userId || "",
      };
      const res = await fetch("/api/apps/home/appliances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      const appliance = await res.json();

      if (pendingPhoto) {
        const fd = new FormData();
        fd.append("file", pendingPhoto);
        fd.append("entity_type", "home_appliance");
        fd.append("entity_id", appliance.id);
        fd.append("uploaded_by", userId || "");
        await fetch("/api/apps/images/upload", { method: "POST", body: fd });
      }

      onSave(appliance);
    } catch (err) {
      alert("Failed to add appliance: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  const inputCls = "w-full surface-panel border border-subtle rounded px-2.5 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={handleSubmit} className="surface-card border border-subtle rounded-lg p-4 space-y-3 mb-2">
      <p className="text-xs font-semibold text-muted uppercase tracking-wide">New Appliance</p>
      <input className={inputCls} placeholder="Appliance name (e.g. Kitchen refrigerator) *" value={form.name}
        onChange={e => set("name", e.target.value)} autoFocus required />
      <div className="grid grid-cols-2 gap-2">
        <input className={inputCls} placeholder="Type (e.g. Refrigerator)" value={form.appliance_type}
          onChange={e => set("appliance_type", e.target.value)} list="appliance-types" />
        <datalist id="appliance-types">
          {types.map(t => <option key={t} value={t} />)}
        </datalist>
        <input className={inputCls} placeholder="Location (e.g. Kitchen)" value={form.location}
          onChange={e => set("location", e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input className={inputCls} placeholder="Brand (e.g. LG)" value={form.brand}
          onChange={e => set("brand", e.target.value)} />
        <input className={inputCls} placeholder="Model" value={form.model}
          onChange={e => set("model", e.target.value)} />
      </div>
      <input className={inputCls} placeholder="Serial number" value={form.serial_number}
        onChange={e => set("serial_number", e.target.value)} />
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-faint mb-1">Purchase date</label>
          <input className={inputCls} type="date" value={form.purchase_date}
            onChange={e => set("purchase_date", e.target.value)} />
        </div>
        <div>
          <label className="block text-xs text-faint mb-1">Purchase price</label>
          <input className={inputCls} type="number" min="0" step="0.01" placeholder="0.00"
            value={form.purchase_price} onChange={e => set("purchase_price", e.target.value)} />
        </div>
      </div>
      <div>
        <label className="block text-xs text-faint mb-1">Warranty expires</label>
        <input className={inputCls} type="date" value={form.warranty_expires}
          onChange={e => set("warranty_expires", e.target.value)} />
      </div>
      <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Notes (optional)"
        value={form.notes} onChange={e => set("notes", e.target.value)} />

      {/* Photo picker */}
      <div className="flex items-center gap-3">
        <label className={`flex items-center gap-2 px-3 py-1.5 text-xs rounded border cursor-pointer transition-colors ${
          pendingPhoto ? "border-indigo-500 bg-indigo-600/20 text-indigo-300" : "border-subtle text-muted hover:border-[var(--ds-border)] hover:text-[var(--ds-text)]"
        }`}>
          <Camera size={13} />
          {pendingPhoto ? pendingPhoto.name : "Attach receipt / photo (optional)"}
          <input ref={photoRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={e => setPendingPhoto(e.target.files[0] || null)} />
        </label>
        {pendingPhoto && (
          <button type="button" onClick={() => { setPendingPhoto(null); if (photoRef.current) photoRef.current.value = ""; }}
            className="text-faint hover:text-red-400">
            <X size={13} />
          </button>
        )}
      </div>

      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button type="submit" disabled={saving || !form.name.trim()}
          className="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded">
          {saving ? "Saving..." : "Add Appliance"}
        </button>
      </div>
    </form>
  );
}

/* ── Appliance Card ── */
function ApplianceCard({ appliance, expanded, onToggle, onUpdate, onDelete, userId, types = [] }) {
  const [images, setImages] = useState([]);
  const [imagesLoaded, setImagesLoaded] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (expanded && !imagesLoaded) {
      fetch(`/api/apps/home/appliances/${appliance.id}`)
        .then(r => r.ok ? r.json() : { images: [] })
        .then(d => { setImages(d.images || []); setImagesLoaded(true); })
        .catch(() => setImagesLoaded(true));
    }
  }, [expanded, appliance.id, imagesLoaded]);

  async function handleEditSave() {
    setSaving(true);
    try {
      const body = {
        ...editForm,
        purchase_price: editForm.purchase_price !== "" && editForm.purchase_price != null
          ? parseFloat(editForm.purchase_price) : null,
        purchase_date: editForm.purchase_date || null,
        warranty_expires: editForm.warranty_expires || null,
      };
      const res = await fetch(`/api/apps/home/appliances/${appliance.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) { onUpdate(await res.json()); setEditMode(false); }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${appliance.name}"?`)) return;
    await fetch(`/api/apps/home/appliances/${appliance.id}`, { method: "DELETE" });
    onDelete(appliance.id);
  }

  function startEdit() {
    setEditForm({
      name: appliance.name,
      appliance_type: appliance.appliance_type || "General",
      brand: appliance.brand || "",
      model: appliance.model || "",
      serial_number: appliance.serial_number || "",
      location: appliance.location || "",
      purchase_date: appliance.purchase_date || "",
      purchase_price: appliance.purchase_price ?? "",
      warranty_expires: appliance.warranty_expires || "",
      notes: appliance.notes || "",
    });
    setEditMode(true);
  }

  const bm = [appliance.brand, appliance.model].filter(Boolean).join(" ");
  const inputCls = "w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none focus:border-indigo-500";

  return (
    <div className="border rounded-lg overflow-hidden transition-all surface-card border-subtle">
      <div className="flex items-start gap-2.5 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className="w-2 h-2 rounded-full shrink-0 mt-1.5 bg-indigo-500" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-default">{appliance.name}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium surface-raised text-default">{appliance.appliance_type || "General"}</span>
            <WarrantyBadge warranty_expires={appliance.warranty_expires} />
            {appliance.location && (
              <span className="flex items-center gap-0.5 text-[10px] text-faint surface-raised px-1.5 py-0.5 rounded">
                <MapPin size={8} /> {appliance.location}
              </span>
            )}
          </div>
          {bm && !expanded && (
            <p className="text-[11px] text-faint mt-0.5 truncate">{bm}</p>
          )}
        </div>
        <ChevronDown size={14} className={`text-faint shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>

      {expanded && (
        <div className="border-t border-subtle px-3 py-3">
          {editMode ? (
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-faint">Name</label>
                <input className={inputCls} value={editForm.name || ""}
                  onChange={e => setEditForm(p => ({ ...p, name: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Type</label>
                  <input className={inputCls} value={editForm.appliance_type || ""} list="appliance-types-edit"
                    onChange={e => setEditForm(p => ({ ...p, appliance_type: e.target.value }))} />
                  <datalist id="appliance-types-edit">
                    {types.map(t => <option key={t} value={t} />)}
                  </datalist>
                </div>
                <div>
                  <label className="text-[10px] text-faint">Location</label>
                  <input className={inputCls} value={editForm.location || ""}
                    onChange={e => setEditForm(p => ({ ...p, location: e.target.value }))} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Brand</label>
                  <input className={inputCls} value={editForm.brand || ""}
                    onChange={e => setEditForm(p => ({ ...p, brand: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] text-faint">Model</label>
                  <input className={inputCls} value={editForm.model || ""}
                    onChange={e => setEditForm(p => ({ ...p, model: e.target.value }))} />
                </div>
              </div>
              <div>
                <label className="text-[10px] text-faint">Serial number</label>
                <input className={inputCls} value={editForm.serial_number || ""}
                  onChange={e => setEditForm(p => ({ ...p, serial_number: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Purchase date</label>
                  <input className={inputCls} type="date" value={editForm.purchase_date || ""}
                    onChange={e => setEditForm(p => ({ ...p, purchase_date: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] text-faint">Purchase price</label>
                  <input className={inputCls} type="number" min="0" step="0.01" value={editForm.purchase_price ?? ""}
                    onChange={e => setEditForm(p => ({ ...p, purchase_price: e.target.value }))} />
                </div>
              </div>
              <div>
                <label className="text-[10px] text-faint">Warranty expires</label>
                <input className={inputCls} type="date" value={editForm.warranty_expires || ""}
                  onChange={e => setEditForm(p => ({ ...p, warranty_expires: e.target.value }))} />
              </div>
              <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Notes"
                value={editForm.notes || ""} onChange={e => setEditForm(p => ({ ...p, notes: e.target.value }))} />
              <div className="flex gap-1">
                <button onClick={handleEditSave} disabled={saving}
                  className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded disabled:opacity-50">
                  {saving ? "Saving..." : "Save"}
                </button>
                <button onClick={() => setEditMode(false)} className="px-3 py-1 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mb-2">
                {bm && <div><span className="text-faint">Brand/Model: </span><span className="text-muted">{bm}</span></div>}
                {appliance.serial_number && <div><span className="text-faint">Serial: </span><span className="text-muted">{appliance.serial_number}</span></div>}
                {appliance.purchase_date && <div><span className="text-faint">Purchased: </span><span className="text-muted">{fmtDate(appliance.purchase_date)}</span></div>}
                {appliance.purchase_price != null && <div><span className="text-faint">Price: </span><span className="text-muted">{fmtPrice(appliance.purchase_price)}</span></div>}
                {appliance.warranty_expires && <div><span className="text-faint">Warranty: </span><span className="text-muted">{fmtDate(appliance.warranty_expires)}</span></div>}
              </div>
              {appliance.notes && <p className="text-xs text-faint italic mb-2">{appliance.notes}</p>}

              {/* Receipt / photos */}
              <p className="text-[10px] text-faint uppercase tracking-wide mt-2">Receipt / photos</p>
              <IssueImageStrip issueId={appliance.id} entityType="home_appliance" images={images} userId={userId} />

              {/* Actions */}
              <div className="flex items-center gap-2 mt-3">
                <button onClick={startEdit}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] border border-subtle rounded">
                  <Edit2 size={11} /> Edit
                </button>
                <button onClick={handleDelete}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-red-500 hover:text-red-400 border border-red-900/40 rounded">
                  <Trash2 size={11} /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Appliances Tab ── */
function AppliancesTab({ userId }) {
  const [appliances, setAppliances] = useState([]);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("All");
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      else if (typeFilter !== "All") params.set("appliance_type", typeFilter);
      const res = await fetch(`/api/apps/home/appliances?${params}`);
      const d = await res.json();
      setAppliances(d.appliances || []);
      if (d.types?.length) setTypes(d.types);
    } finally {
      setLoading(false);
    }
  }, [search, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const allTypes = ["All", ...types];

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle shrink-0">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            className="w-full surface-panel border border-subtle rounded pl-7 pr-2.5 py-1.5 text-xs text-default placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            placeholder="Search appliances..."
            value={search}
            onChange={e => { setSearch(e.target.value); setTypeFilter("All"); }}
          />
          {search && <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]"><X size={12} /></button>}
        </div>
        {!search && allTypes.length > 1 && (
          <select
            className="surface-panel border border-subtle rounded px-2 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500"
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
          >
            {allTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <button
          onClick={() => setShowAdd(v => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${
            showAdd ? "surface-raised text-on-accent" : "bg-indigo-600 hover:bg-indigo-500 text-on-accent"
          }`}
        >
          {showAdd ? <X size={13} /> : <Plus size={13} />}
          {showAdd ? "Cancel" : "Add Appliance"}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0">
        {showAdd && (
          <AddApplianceForm
            types={types}
            userId={userId}
            onSave={(appliance) => { setAppliances(prev => [appliance, ...prev]); setShowAdd(false); setExpandedId(appliance.id); load(); }}
            onCancel={() => setShowAdd(false)}
          />
        )}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-faint text-sm">Loading...</div>
        ) : appliances.length === 0 ? (
          <PristineEmpty
            appId="home"
            blurb={getAppManifest("home")?.heroes?.appliances}
            records={appliances}
            loading={loading}
            filterActive={!!search.trim() || typeFilter !== "All"}
            fallback={
              <div className="flex flex-col items-center justify-center h-48 text-faint">
                <ShoppingCart size={32} className="text-default mb-3" />
                <p className="text-sm font-medium text-muted">
                  {search ? `No appliances matching "${search}"` : "No appliances yet"}
                </p>
                <p className="text-xs mt-1 text-faint">
                  {!search && 'Click "Add Appliance" to get started'}
                </p>
              </div>
            }
          />
        ) : (
          <div className="space-y-2">
            {appliances.map(appliance => (
              <ApplianceCard
                key={appliance.id}
                appliance={appliance}
                expanded={expandedId === appliance.id}
                onToggle={() => setExpandedId(prev => prev === appliance.id ? null : appliance.id)}
                onUpdate={(updated) => setAppliances(prev => prev.map(a => a.id === updated.id ? { ...a, ...updated } : a))}
                onDelete={(id) => { setAppliances(prev => prev.filter(a => a.id !== id)); if (expandedId === id) setExpandedId(null); }}
                userId={userId}
                types={types}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Insurance renewal helpers ── */
function renewalStatus(dateStr) {
  if (!dateStr) return "none";
  const diff = daysDiff(dateStr);
  if (diff < 0) return "overdue";
  if (diff <= 30) return "soon";
  return "ok";
}

const RENEWAL_STYLES = {
  overdue: { badge: "bg-red-500/20 text-red-400",     label: "Renewal overdue" },
  soon:    { badge: "bg-amber-500/20 text-amber-400", label: "Renews soon" },
  ok:      { badge: "bg-green-500/20 text-green-400", label: "Renews" },
  none:    { badge: "surface-raised text-muted",      label: "No renewal date" },
};

function RenewalBadge({ renewal_date }) {
  const status = renewalStatus(renewal_date);
  if (status === "none") return null;
  const s = RENEWAL_STYLES[status];
  const suffix = renewal_date ? ` · ${fmtDate(renewal_date)}` : "";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}>
      {s.label}{status !== "overdue" ? suffix : ""}
    </span>
  );
}

const POLICY_TYPES = ["Home", "Auto", "Life", "Umbrella", "Flood", "Health", "Renters", "Other"];
const PERIOD_MULTIPLIER = { annual: 1, semiannual: 2, quarterly: 4, monthly: 12 };
const PERIOD_LABEL = { annual: "annual", semiannual: "semi-annual", quarterly: "quarterly", monthly: "monthly" };

/* ── Add Policy Form ── */
function AddPolicyForm({ types = [], userId, onSave, onCancel }) {
  const [form, setForm] = useState({
    provider: "", policy_number: "", policy_type: "Home", coverage_amount: "",
    premium: "", premium_period: "annual", deductible: "", renewal_date: "",
    insured_assets: "", notes: "",
  });
  const [pendingPhoto, setPendingPhoto] = useState(null);
  const [saving, setSaving] = useState(false);
  const photoRef = useRef();
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.provider.trim()) return;
    setSaving(true);
    try {
      const body = {
        provider: form.provider.trim(),
        policy_number: form.policy_number.trim(),
        policy_type: form.policy_type.trim() || "Home",
        coverage_amount: form.coverage_amount !== "" ? parseFloat(form.coverage_amount) : null,
        premium: form.premium !== "" ? parseFloat(form.premium) : null,
        premium_period: form.premium_period || "annual",
        deductible: form.deductible !== "" ? parseFloat(form.deductible) : null,
        renewal_date: form.renewal_date || null,
        insured_assets: form.insured_assets.trim(),
        notes: form.notes.trim(),
        created_by: userId || "",
      };
      const res = await fetch("/api/apps/home/insurance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      const policy = await res.json();

      if (pendingPhoto) {
        const fd = new FormData();
        fd.append("file", pendingPhoto);
        fd.append("entity_type", "home_insurance_policy");
        fd.append("entity_id", policy.id);
        fd.append("uploaded_by", userId || "");
        await fetch("/api/apps/images/upload", { method: "POST", body: fd });
      }

      onSave(policy);
    } catch (err) {
      alert("Failed to add policy: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  const inputCls = "w-full surface-panel border border-subtle rounded px-2.5 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={handleSubmit} className="surface-card border border-subtle rounded-lg p-4 space-y-3 mb-2">
      <p className="text-xs font-semibold text-muted uppercase tracking-wide">New Policy</p>
      <input className={inputCls} placeholder="Provider (e.g. State Farm) *" value={form.provider}
        onChange={e => set("provider", e.target.value)} autoFocus required />
      <div className="grid grid-cols-2 gap-2">
        <input className={inputCls} placeholder="Type (e.g. Home)" value={form.policy_type}
          onChange={e => set("policy_type", e.target.value)} list="policy-types" />
        <datalist id="policy-types">
          {[...new Set([...POLICY_TYPES, ...types])].map(t => <option key={t} value={t} />)}
        </datalist>
        <input className={inputCls} placeholder="Policy number" value={form.policy_number}
          onChange={e => set("policy_number", e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-faint mb-1">Coverage amount</label>
          <input className={inputCls} type="number" min="0" step="0.01" placeholder="0.00"
            value={form.coverage_amount} onChange={e => set("coverage_amount", e.target.value)} />
        </div>
        <div>
          <label className="block text-xs text-faint mb-1">Deductible</label>
          <input className={inputCls} type="number" min="0" step="0.01" placeholder="0.00"
            value={form.deductible} onChange={e => set("deductible", e.target.value)} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-faint mb-1">Premium</label>
          <input className={inputCls} type="number" min="0" step="0.01" placeholder="0.00"
            value={form.premium} onChange={e => set("premium", e.target.value)} />
        </div>
        <div>
          <label className="block text-xs text-faint mb-1">Premium period</label>
          <select className={inputCls} value={form.premium_period} onChange={e => set("premium_period", e.target.value)}>
            <option value="annual">Annual</option>
            <option value="semiannual">Semi-annual</option>
            <option value="quarterly">Quarterly</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs text-faint mb-1">Renewal date</label>
        <input className={inputCls} type="date" value={form.renewal_date}
          onChange={e => set("renewal_date", e.target.value)} />
      </div>
      <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Insured assets (what does this cover?)"
        value={form.insured_assets} onChange={e => set("insured_assets", e.target.value)} />
      <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Notes (optional)"
        value={form.notes} onChange={e => set("notes", e.target.value)} />

      {/* Document picker */}
      <div className="flex items-center gap-3">
        <label className={`flex items-center gap-2 px-3 py-1.5 text-xs rounded border cursor-pointer transition-colors ${
          pendingPhoto ? "border-indigo-500 bg-indigo-600/20 text-indigo-300" : "border-subtle text-muted hover:border-[var(--ds-border)] hover:text-[var(--ds-text)]"
        }`}>
          <Camera size={13} />
          {pendingPhoto ? pendingPhoto.name : "Attach policy document (optional)"}
          <input ref={photoRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={e => setPendingPhoto(e.target.files[0] || null)} />
        </label>
        {pendingPhoto && (
          <button type="button" onClick={() => { setPendingPhoto(null); if (photoRef.current) photoRef.current.value = ""; }}
            className="text-faint hover:text-red-400">
            <X size={13} />
          </button>
        )}
      </div>

      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button type="submit" disabled={saving || !form.provider.trim()}
          className="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded">
          {saving ? "Saving..." : "Add Policy"}
        </button>
      </div>
    </form>
  );
}

/* ── Policy Card ── */
function PolicyCard({ policy, expanded, onToggle, onUpdate, onDelete, userId, types = [] }) {
  const [images, setImages] = useState([]);
  const [imagesLoaded, setImagesLoaded] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (expanded && !imagesLoaded) {
      fetch(`/api/apps/home/insurance/${policy.id}`)
        .then(r => r.ok ? r.json() : { images: [] })
        .then(d => { setImages(d.images || []); setImagesLoaded(true); })
        .catch(() => setImagesLoaded(true));
    }
  }, [expanded, policy.id, imagesLoaded]);

  async function handleEditSave() {
    setSaving(true);
    try {
      const body = {
        ...editForm,
        coverage_amount: editForm.coverage_amount !== "" && editForm.coverage_amount != null
          ? parseFloat(editForm.coverage_amount) : null,
        premium: editForm.premium !== "" && editForm.premium != null
          ? parseFloat(editForm.premium) : null,
        deductible: editForm.deductible !== "" && editForm.deductible != null
          ? parseFloat(editForm.deductible) : null,
        renewal_date: editForm.renewal_date || null,
      };
      const res = await fetch(`/api/apps/home/insurance/${policy.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) { onUpdate(await res.json()); setEditMode(false); }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${policy.provider}" policy?`)) return;
    await fetch(`/api/apps/home/insurance/${policy.id}`, { method: "DELETE" });
    onDelete(policy.id);
  }

  function startEdit() {
    setEditForm({
      provider: policy.provider,
      policy_number: policy.policy_number || "",
      policy_type: policy.policy_type || "Home",
      coverage_amount: policy.coverage_amount ?? "",
      premium: policy.premium ?? "",
      premium_period: policy.premium_period || "annual",
      deductible: policy.deductible ?? "",
      renewal_date: policy.renewal_date || "",
      insured_assets: policy.insured_assets || "",
      notes: policy.notes || "",
    });
    setEditMode(true);
  }

  const inputCls = "w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none focus:border-indigo-500";

  return (
    <div className="border rounded-lg overflow-hidden transition-all surface-card border-subtle">
      <div className="flex items-start gap-2.5 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className="w-2 h-2 rounded-full shrink-0 mt-1.5 bg-indigo-500" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-default">{policy.provider}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium surface-raised text-default">{policy.policy_type || "Home"}</span>
            <RenewalBadge renewal_date={policy.renewal_date} />
            {policy.policy_number && (
              <span className="text-[10px] text-faint surface-raised px-1.5 py-0.5 rounded">#{policy.policy_number}</span>
            )}
          </div>
          {policy.coverage_amount != null && !expanded && (
            <p className="text-[11px] text-faint mt-0.5 truncate">{fmtPrice(policy.coverage_amount)} coverage</p>
          )}
        </div>
        <ChevronDown size={14} className={`text-faint shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>

      {expanded && (
        <div className="border-t border-subtle px-3 py-3">
          {editMode ? (
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-faint">Provider</label>
                <input className={inputCls} value={editForm.provider || ""}
                  onChange={e => setEditForm(p => ({ ...p, provider: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Type</label>
                  <input className={inputCls} value={editForm.policy_type || ""} list="policy-types-edit"
                    onChange={e => setEditForm(p => ({ ...p, policy_type: e.target.value }))} />
                  <datalist id="policy-types-edit">
                    {[...new Set([...POLICY_TYPES, ...types])].map(t => <option key={t} value={t} />)}
                  </datalist>
                </div>
                <div>
                  <label className="text-[10px] text-faint">Policy number</label>
                  <input className={inputCls} value={editForm.policy_number || ""}
                    onChange={e => setEditForm(p => ({ ...p, policy_number: e.target.value }))} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Coverage amount</label>
                  <input className={inputCls} type="number" min="0" step="0.01" value={editForm.coverage_amount ?? ""}
                    onChange={e => setEditForm(p => ({ ...p, coverage_amount: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] text-faint">Deductible</label>
                  <input className={inputCls} type="number" min="0" step="0.01" value={editForm.deductible ?? ""}
                    onChange={e => setEditForm(p => ({ ...p, deductible: e.target.value }))} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Premium</label>
                  <input className={inputCls} type="number" min="0" step="0.01" value={editForm.premium ?? ""}
                    onChange={e => setEditForm(p => ({ ...p, premium: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] text-faint">Premium period</label>
                  <select className={inputCls} value={editForm.premium_period || "annual"}
                    onChange={e => setEditForm(p => ({ ...p, premium_period: e.target.value }))}>
                    <option value="annual">Annual</option>
                    <option value="semiannual">Semi-annual</option>
                    <option value="quarterly">Quarterly</option>
                    <option value="monthly">Monthly</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[10px] text-faint">Renewal date</label>
                <input className={inputCls} type="date" value={editForm.renewal_date || ""}
                  onChange={e => setEditForm(p => ({ ...p, renewal_date: e.target.value }))} />
              </div>
              <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Insured assets"
                value={editForm.insured_assets || ""} onChange={e => setEditForm(p => ({ ...p, insured_assets: e.target.value }))} />
              <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Notes"
                value={editForm.notes || ""} onChange={e => setEditForm(p => ({ ...p, notes: e.target.value }))} />
              <div className="flex gap-1">
                <button onClick={handleEditSave} disabled={saving}
                  className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded disabled:opacity-50">
                  {saving ? "Saving..." : "Save"}
                </button>
                <button onClick={() => setEditMode(false)} className="px-3 py-1 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mb-2">
                {policy.coverage_amount != null && <div><span className="text-faint">Coverage: </span><span className="text-muted">{fmtPrice(policy.coverage_amount)}</span></div>}
                {policy.premium != null && <div><span className="text-faint">Premium: </span><span className="text-muted">{fmtPrice(policy.premium)}</span></div>}
                {policy.premium != null && <div><span className="text-faint">Billed: </span><span className="text-muted">{PERIOD_LABEL[policy.premium_period] || policy.premium_period || "annual"}</span></div>}
                {policy.deductible != null && <div><span className="text-faint">Deductible: </span><span className="text-muted">{fmtPrice(policy.deductible)}</span></div>}
                {policy.renewal_date && <div><span className="text-faint">Renews: </span><span className="text-muted">{fmtDate(policy.renewal_date)}</span></div>}
              </div>
              {policy.insured_assets && <p className="text-xs text-muted mb-2"><span className="text-faint">Insured assets: </span>{policy.insured_assets}</p>}
              {policy.notes && <p className="text-xs text-faint italic mb-2">{policy.notes}</p>}

              {/* Policy documents */}
              <p className="text-[10px] text-faint uppercase tracking-wide mt-2">Policy documents</p>
              <IssueImageStrip issueId={policy.id} entityType="home_insurance_policy" images={images} userId={userId} />

              {/* Actions */}
              <div className="flex items-center gap-2 mt-3">
                <button onClick={startEdit}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] border border-subtle rounded">
                  <Edit2 size={11} /> Edit
                </button>
                <button onClick={handleDelete}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-red-500 hover:text-red-400 border border-red-900/40 rounded">
                  <Trash2 size={11} /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Coverage Summary Band ── */
function CoverageSummary({ policies }) {
  const today = new Date(); today.setHours(0, 0, 0, 0);

  let totalCoverage = 0;
  let totalAnnualPremium = 0;
  const byType = {};
  let nextRenewal = null;

  for (const p of policies) {
    const cov = Number(p.coverage_amount) || 0;
    totalCoverage += cov;

    const prem = Number(p.premium) || 0;
    const mult = PERIOD_MULTIPLIER[p.premium_period] ?? 1;
    const annualized = prem * mult;
    if (!Number.isNaN(annualized)) totalAnnualPremium += annualized;

    const t = p.policy_type || "Other";
    byType[t] = (byType[t] || 0) + 1;

    if (p.renewal_date) {
      const d = new Date(p.renewal_date + "T00:00:00");
      d.setHours(0, 0, 0, 0);
      if (!Number.isNaN(d.getTime()) && d >= today) {
        if (nextRenewal === null || d < nextRenewal) nextRenewal = d;
      }
    }
  }

  const nextRenewalStr = nextRenewal
    ? nextRenewal.toISOString().split("T")[0]
    : null;

  const typeEntries = Object.entries(byType).sort((a, b) => b[1] - a[1]);

  return (
    <div className="surface-card border border-subtle rounded-lg p-3 mb-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <p className="text-[10px] text-faint uppercase tracking-wide">Policies</p>
          <p className="text-sm font-semibold text-default">{policies.length}</p>
        </div>
        <div>
          <p className="text-[10px] text-faint uppercase tracking-wide">Total coverage</p>
          <p className="text-sm font-semibold text-default">{fmtPrice(totalCoverage) || "$0.00"}</p>
        </div>
        <div>
          <p className="text-[10px] text-faint uppercase tracking-wide">Total annual premium</p>
          <p className="text-sm font-semibold text-default">{fmtPrice(totalAnnualPremium) || "$0.00"}</p>
        </div>
        <div>
          <p className="text-[10px] text-faint uppercase tracking-wide">Next renewal</p>
          <p className="text-sm font-semibold text-default">{nextRenewalStr ? fmtDate(nextRenewalStr) : "—"}</p>
        </div>
      </div>
      {typeEntries.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap mt-2 pt-2 border-t border-subtle">
          {typeEntries.map(([t, n]) => (
            <span key={t} className="px-1.5 py-0.5 rounded text-[10px] font-medium surface-raised text-default">
              {t} · {n}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Insurance Tab ── */
function InsuranceTab({ userId }) {
  const [policies, setPolicies] = useState([]);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("All");
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      else if (typeFilter !== "All") params.set("policy_type", typeFilter);
      const res = await fetch(`/api/apps/home/insurance?${params}`);
      const d = await res.json();
      setPolicies(d.policies || []);
      if (d.types?.length) setTypes(d.types);
    } finally {
      setLoading(false);
    }
  }, [search, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const allTypes = ["All", ...types];

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle shrink-0">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            className="w-full surface-panel border border-subtle rounded pl-7 pr-2.5 py-1.5 text-xs text-default placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            placeholder="Search policies..."
            value={search}
            onChange={e => { setSearch(e.target.value); setTypeFilter("All"); }}
          />
          {search && <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]"><X size={12} /></button>}
        </div>
        {!search && allTypes.length > 1 && (
          <select
            className="surface-panel border border-subtle rounded px-2 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500"
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
          >
            {allTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <button
          onClick={() => setShowAdd(v => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${
            showAdd ? "surface-raised text-on-accent" : "bg-indigo-600 hover:bg-indigo-500 text-on-accent"
          }`}
        >
          {showAdd ? <X size={13} /> : <Plus size={13} />}
          {showAdd ? "Cancel" : "Add Policy"}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0">
        {showAdd && (
          <AddPolicyForm
            types={types}
            userId={userId}
            onSave={(policy) => { setPolicies(prev => [policy, ...prev]); setShowAdd(false); setExpandedId(policy.id); load(); }}
            onCancel={() => setShowAdd(false)}
          />
        )}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-faint text-sm">Loading...</div>
        ) : policies.length === 0 ? (
          <PristineEmpty
            appId="home"
            blurb={getAppManifest("home")?.heroes?.insurance}
            records={policies}
            loading={loading}
            filterActive={!!search.trim() || typeFilter !== "All"}
            fallback={
              <div className="flex flex-col items-center justify-center h-48 text-faint">
                <Shield size={32} className="text-default mb-3" />
                <p className="text-sm font-medium text-muted">
                  {search ? `No policies matching "${search}"` : "No policies yet"}
                </p>
                <p className="text-xs mt-1 text-faint">
                  {!search && 'Click "Add Policy" to get started'}
                </p>
              </div>
            }
          />
        ) : (
          <>
            <CoverageSummary policies={policies} />
            <div className="space-y-2">
              {policies.map(policy => (
                <PolicyCard
                  key={policy.id}
                  policy={policy}
                  expanded={expandedId === policy.id}
                  onToggle={() => setExpandedId(prev => prev === policy.id ? null : policy.id)}
                  onUpdate={(updated) => setPolicies(prev => prev.map(p => p.id === updated.id ? { ...p, ...updated } : p))}
                  onDelete={(id) => { setPolicies(prev => prev.filter(p => p.id !== id)); if (expandedId === id) setExpandedId(null); }}
                  userId={userId}
                  types={types}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Shared Issue Image Strip ── */
function IssueImageStrip({ issueId, entityType, images: initialImages, userId }) {
  const [images, setImages] = useState(initialImages || []);
  const [uploading, setUploading] = useState(false);
  const [lightbox, setLightbox] = useState(null);
  const inputRef = useRef();

  useEffect(() => { setImages(initialImages || []); }, [initialImages]);

  async function handleFileChange(e) {
    const file = e.target.files[0];
    if (!file || !issueId) return;
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("entity_type", entityType);
    fd.append("entity_id", issueId);
    fd.append("uploaded_by", userId || "");
    try {
      const res = await fetch("/api/apps/images/upload", { method: "POST", body: fd });
      if (res.ok) {
        const img = await res.json();
        setImages(prev => [...prev, img]);
      }
    } catch {}
    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleRemove(imgId) {
    const endpoint = entityType === "home_issue"
      ? `/api/apps/home/issues/${issueId}/images/${imgId}/unlink`
      : entityType === "home_appliance"
      ? `/api/apps/home/appliances/${issueId}/images/${imgId}/unlink`
      : entityType === "home_insurance_policy"
      ? `/api/apps/home/insurance/${issueId}/images/${imgId}/unlink`
      : `/api/apps/auto/issues/${issueId}/images/${imgId}/unlink`;
    await fetch(endpoint, { method: "DELETE" });
    setImages(prev => prev.filter(i => i.id !== imgId));
  }

  function imgSrc(img) {
    if (img.storage_path) return "/" + img.storage_path;
    return `/api/apps/images/${img.id}/file`;
  }

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap mt-2">
        {images.map(img => (
          <div key={img.id} className="relative group">
            <img
              src={imgSrc(img)}
              alt=""
              className="w-16 h-16 object-cover rounded border border-subtle cursor-pointer"
              onClick={() => setLightbox(imgSrc(img))}
            />
            <button
              onClick={() => handleRemove(img.id)}
              className="absolute -top-1 -right-1 w-4 h-4 bg-red-600 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <X size={8} className="text-default" />
            </button>
          </div>
        ))}
        <label className={`flex flex-col items-center justify-center w-16 h-16 rounded border-2 border-dashed transition-colors cursor-pointer ${
          uploading ? "border-subtle opacity-50" : "border-subtle hover:border-indigo-500"
        }`}>
          {uploading ? (
            <span className="text-[9px] text-faint">...</span>
          ) : (
            <Camera size={18} className="text-faint" />
          )}
          <input ref={inputRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={handleFileChange} disabled={uploading} />
        </label>
      </div>
      {lightbox && (
        <div
          className="fixed inset-0 z-50 surface-overlay flex items-center justify-center p-4"
          onClick={() => setLightbox(null)}
        >
          <button
            className="absolute top-4 right-4 text-default/70 hover:text-[var(--ds-text)]"
            onClick={() => setLightbox(null)}
          >
            <X size={28} />
          </button>
          <img
            src={lightbox}
            alt=""
            className="max-w-full max-h-[90dvh] rounded-lg shadow-2xl object-contain"
            onClick={e => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}


/* ── Severity helpers ── */
const HOME_SEVERITY_COLORS = {
  critical: "bg-red-600 text-on-accent",
  major:    "bg-orange-600 text-on-accent",
  moderate: "bg-yellow-600 text-[#000]",
  minor:    "surface-raised text-default",
};

const HOME_STATUS_DOT = {
  open:        "bg-red-500",
  in_progress: "bg-amber-400",
  fixed:       "bg-green-500",
};


/* ── HomeIssuesTab ── */
function HomeIssuesTab({ userId }) {
  const [issues, setIssues] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("open");
  const [filterLoc, setFilterLoc] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/apps/home/issues");
      const d = await res.json();
      setIssues(d.issues || []);
      setLocations(d.all_locations || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = issues.filter(i => {
    if (filterStatus && filterStatus !== "all" && i.status !== filterStatus) return false;
    if (filterLoc && i.location !== filterLoc) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        i.title.toLowerCase().includes(q) ||
        (i.description || "").toLowerCase().includes(q) ||
        (i.location || "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const openCount = issues.filter(i => i.status !== "fixed").length;

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle shrink-0">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            className="w-full surface-panel border border-subtle rounded pl-7 pr-2.5 py-1.5 text-xs text-default placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            placeholder="Search issues..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]"><X size={12} /></button>}
        </div>
        <button
          onClick={() => setShowAdd(v => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${
            showAdd ? "surface-raised text-on-accent" : "bg-indigo-600 hover:bg-indigo-500 text-on-accent"
          }`}
        >
          {showAdd ? <X size={13} /> : <Plus size={13} />}
          {showAdd ? "Cancel" : "Add Issue"}
        </button>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-subtle shrink-0 overflow-x-auto">
        {[["open", "Open"], ["in_progress", "In Progress"], ["fixed", "Fixed"], ["all", "All"]].map(([v, label]) => (
          <button key={v} onClick={() => setFilterStatus(v)}
            className={`px-2.5 py-0.5 text-xs rounded-full whitespace-nowrap transition-colors ${
              filterStatus === v ? "bg-indigo-600 text-on-accent" : "text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"
            }`}>
            {label}{v === "open" && openCount > 0 ? ` (${openCount})` : ""}
          </button>
        ))}
        {locations.length > 0 && <span className="text-default mx-1">|</span>}
        {locations.map(loc => (
          <button key={loc} onClick={() => setFilterLoc(filterLoc === loc ? "" : loc)}
            className={`px-2.5 py-0.5 text-xs rounded-full whitespace-nowrap transition-colors ${
              filterLoc === loc ? "surface-raised text-default" : "text-faint hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"
            }`}>
            {loc}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0">
        {showAdd && (
          <AddHomeIssueForm
            locations={locations}
            userId={userId}
            onSave={(issue) => { setIssues(prev => [issue, ...prev]); setShowAdd(false); setExpandedId(issue.id); }}
            onCancel={() => setShowAdd(false)}
          />
        )}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-faint text-sm">Loading...</div>
        ) : filtered.length === 0 ? (
          <PristineEmpty
            appId="home"
            blurb={getAppManifest("home")?.heroes?.issues}
            records={issues}
            loading={loading}
            filterActive={!!search.trim() || filterStatus !== "open" || !!filterLoc}
            fallback={
              <div className="flex flex-col items-center justify-center h-40 text-faint">
                <AlertTriangle size={32} className="text-default mb-2" />
                <p className="text-sm text-muted">{search ? `No issues matching "${search}"` : "No issues found"}</p>
                {filterStatus === "open" && !search && (
                  <p className="text-xs text-faint mt-1">Click &quot;Add Issue&quot; to log one</p>
                )}
              </div>
            }
          />
        ) : (
          <div className="space-y-2">
            {filtered.map(issue => (
              <HomeIssueCard
                key={issue.id}
                issue={issue}
                expanded={expandedId === issue.id}
                onToggle={() => setExpandedId(prev => prev === issue.id ? null : issue.id)}
                onUpdate={(updated) => setIssues(prev => prev.map(i => i.id === updated.id ? {...i, ...updated} : i))}
                onDelete={(id) => { setIssues(prev => prev.filter(i => i.id !== id)); if (expandedId === id) setExpandedId(null); }}
                userId={userId}
                locations={locations}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


/* ── Add Home Issue Form ── */
function AddHomeIssueForm({ locations, userId, onSave, onCancel }) {
  const [form, setForm] = useState({ title: "", description: "", location: "", sub_location: "", category: "General", severity: "minor" });
  const [pendingPhoto, setPendingPhoto] = useState(null);
  const [saving, setSaving] = useState(false);
  const photoRef = useRef();
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      const res = await fetch("/api/apps/home/issues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, created_by: userId || "" }),
      });
      if (!res.ok) throw new Error(await res.text());
      const issue = await res.json();

      if (pendingPhoto) {
        const fd = new FormData();
        fd.append("file", pendingPhoto);
        fd.append("entity_type", "home_issue");
        fd.append("entity_id", issue.id);
        fd.append("uploaded_by", userId || "");
        await fetch("/api/apps/images/upload", { method: "POST", body: fd });
      }

      onSave(issue);
    } catch (err) {
      alert("Failed: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  const inputCls = "w-full surface-panel border border-subtle rounded px-2.5 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={handleSubmit} className="surface-card border border-subtle rounded-lg p-4 space-y-3 mb-2">
      <p className="text-xs font-semibold text-muted uppercase tracking-wide">New Home Issue</p>
      <input className={inputCls} placeholder="What needs to be fixed? *" value={form.title}
        onChange={e => set("title", e.target.value)} autoFocus required />
      <div className="grid grid-cols-2 gap-2">
        <select className={inputCls} value={form.location} onChange={e => set("location", e.target.value)}>
          <option value="">Room / Area</option>
          {locations.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        <input className={inputCls} placeholder="Sub-location (e.g. Under sink)" value={form.sub_location}
          onChange={e => set("sub_location", e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <select className={inputCls} value={form.severity} onChange={e => set("severity", e.target.value)}>
          <option value="minor">Minor</option>
          <option value="moderate">Moderate</option>
          <option value="major">Major</option>
          <option value="critical">Critical</option>
        </select>
        <input className={inputCls} placeholder="Category (e.g. Plumbing)" value={form.category}
          onChange={e => set("category", e.target.value)} />
      </div>
      <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Description (optional)"
        value={form.description} onChange={e => set("description", e.target.value)} />

      {/* Photo picker */}
      <div className="flex items-center gap-3">
        <label className={`flex items-center gap-2 px-3 py-1.5 text-xs rounded border cursor-pointer transition-colors ${
          pendingPhoto ? "border-indigo-500 bg-indigo-600/20 text-indigo-300" : "border-subtle text-muted hover:border-[var(--ds-border)] hover:text-[var(--ds-text)]"
        }`}>
          <Camera size={13} />
          {pendingPhoto ? pendingPhoto.name : "Attach photo (optional)"}
          <input ref={photoRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={e => setPendingPhoto(e.target.files[0] || null)} />
        </label>
        {pendingPhoto && (
          <button type="button" onClick={() => { setPendingPhoto(null); if (photoRef.current) photoRef.current.value = ""; }}
            className="text-faint hover:text-red-400">
            <X size={13} />
          </button>
        )}
      </div>

      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button type="submit" disabled={saving || !form.title.trim()}
          className="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded">
          {saving ? "Saving..." : "Add Issue"}
        </button>
      </div>
    </form>
  );
}


/* ── Home Issue Card ── */
function HomeIssueCard({ issue, expanded, onToggle, onUpdate, onDelete, userId, locations = [] }) {
  const [images, setImages] = useState([]);
  const [imagesLoaded, setImagesLoaded] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const isFixed = issue.status === "fixed";

  useEffect(() => {
    if (expanded && !imagesLoaded) {
      fetch(`/api/apps/home/issues/${issue.id}`)
        .then(r => r.ok ? r.json() : { images: [] })
        .then(d => { setImages(d.images || []); setImagesLoaded(true); })
        .catch(() => setImagesLoaded(true));
    }
  }, [expanded, issue.id, imagesLoaded]);

  async function handleFix() {
    const today = new Date().toISOString().split("T")[0];
    const res = await fetch(`/api/apps/home/issues/${issue.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "fixed", date_fixed: today }),
    });
    if (res.ok) onUpdate(await res.json());
  }

  async function handleReopen() {
    const res = await fetch(`/api/apps/home/issues/${issue.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "open", date_fixed: null }),
    });
    if (res.ok) onUpdate(await res.json());
  }

  async function handleEditSave() {
    setSaving(true);
    const res = await fetch(`/api/apps/home/issues/${issue.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editForm),
    });
    if (res.ok) { onUpdate(await res.json()); setEditMode(false); }
    setSaving(false);
  }

  async function handleDelete() {
    if (!confirm(`Delete "${issue.title}"?`)) return;
    await fetch(`/api/apps/home/issues/${issue.id}`, { method: "DELETE" });
    onDelete(issue.id);
  }

  function startEdit() {
    setEditForm({
      title: issue.title,
      description: issue.description || "",
      location: issue.location || "",
      sub_location: issue.sub_location || "",
      category: issue.category || "General",
      severity: issue.severity || "minor",
      notes: issue.notes || "",
    });
    setEditMode(true);
  }

  const sevCls = HOME_SEVERITY_COLORS[issue.severity] || HOME_SEVERITY_COLORS.minor;
  const dotCls = HOME_STATUS_DOT[issue.status] || "surface-raised";

  return (
    <div className={`border rounded-lg overflow-hidden transition-all ${
      isFixed ? "surface-card border-subtle" : "surface-card border-subtle"
    }`}>
      <div className="flex items-start gap-2.5 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className={`w-2 h-2 rounded-full shrink-0 mt-1.5 ${dotCls}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-1.5 py-0 rounded text-[10px] font-medium ${sevCls}`}>{issue.severity}</span>
            <span className={`text-sm font-medium ${ isFixed ? "line-through text-faint" : "text-default"}`}>{issue.title}</span>
            {issue.location && (
              <span className="flex items-center gap-0.5 text-[10px] text-faint surface-raised px-1.5 py-0.5 rounded">
                <MapPin size={8} /> {issue.location}{issue.sub_location ? ` › ${issue.sub_location}` : ""}
              </span>
            )}
          </div>
          {issue.description && !expanded && (
            <p className="text-[11px] text-faint mt-0.5 truncate">{issue.description}</p>
          )}
        </div>
        <ChevronDown size={14} className={`text-faint shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>

      {expanded && (
        <div className="border-t border-subtle px-3 py-3">
          {editMode ? (
            <div className="space-y-2">
              {[["title","Title"],["sub_location","Sub-location"],["category","Category"]].map(([k, label]) => (
                <div key={k}>
                  <label className="text-[10px] text-faint">{label}</label>
                  <input className="w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none focus:border-indigo-500"
                    value={editForm[k] || ""} onChange={e => setEditForm(p => ({...p, [k]: e.target.value}))} />
                </div>
              ))}
              <div>
                <label className="text-[10px] text-faint">Location</label>
                <select className="w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none focus:border-indigo-500"
                  value={editForm.location || ""} onChange={e => setEditForm(p => ({...p, location: e.target.value}))}>
                  <option value="">— none —</option>
                  {locations.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-faint">Severity</label>
                <select className="w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none"
                  value={editForm.severity} onChange={e => setEditForm(p => ({...p, severity: e.target.value}))}>
                  {["minor","moderate","major","critical"].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <textarea className="w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none resize-none"
                rows={2} placeholder="Notes" value={editForm.notes}
                onChange={e => setEditForm(p => ({...p, notes: e.target.value}))} />
              <div className="flex gap-1">
                <button onClick={handleEditSave} disabled={saving}
                  className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded disabled:opacity-50">
                  {saving ? "Saving..." : "Save"}
                </button>
                <button onClick={() => setEditMode(false)} className="px-3 py-1 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
              </div>
            </div>
          ) : (
            <>
              {issue.description && <p className="text-xs text-muted mb-2">{issue.description}</p>}
              {issue.notes && <p className="text-xs text-faint italic mb-2">{issue.notes}</p>}
              {isFixed && issue.date_fixed && (
                <p className="text-xs text-green-500 mb-2">Fixed: {issue.date_fixed}</p>
              )}

              {/* Photos */}
              <IssueImageStrip issueId={issue.id} entityType="home_issue" images={images} userId={userId} />

              {/* Actions */}
              <div className="flex items-center gap-2 mt-3">
                {!isFixed && (
                  <button onClick={handleFix}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs bg-green-600/20 hover:bg-green-600/40 text-green-400 border border-green-600/30 rounded">
                    <CheckCircle size={11} /> Mark Fixed
                  </button>
                )}
                {isFixed && (
                  <button onClick={handleReopen}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs surface-raised hover:bg-[var(--ds-raised)] text-default rounded">
                    Reopen
                  </button>
                )}
                <button onClick={startEdit}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] border border-subtle rounded">
                  <Edit2 size={11} /> Edit
                </button>
                <button onClick={handleDelete}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-red-500 hover:text-red-400 border border-red-900/40 rounded">
                  <Trash2 size={11} /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}


/* ── Star rating (interactive + readonly) ── */
function StarRating({ value, onChange, readonly = false }) {
  const [hover, setHover] = useState(0);
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map(n => (
        <Star
          key={n}
          size={14}
          className={`transition-colors ${
            n <= (hover || value || 0)
              ? "fill-amber-400 text-amber-400"
              : "text-faint"
          } ${readonly ? "cursor-default" : "cursor-pointer"}`}
          onClick={() => !readonly && onChange && onChange(n === value ? null : n)}
          onMouseEnter={() => !readonly && setHover(n)}
          onMouseLeave={() => !readonly && setHover(0)}
        />
      ))}
    </div>
  );
}

const CONTRACTOR_TRADES = [
  "Electrician", "Plumber", "Roofer", "Painter", "HVAC", "Landscaper", "Handyman", "General",
];

/* ── Add Contractor Form ── */
function AddContractorForm({ trades = [], userId, onSave, onCancel }) {
  const [form, setForm] = useState({
    name: "", trade: "General", company: "", phone: "", email: "",
    rating: null, last_used: "", jobs_history: "", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        trade: form.trade.trim() || "General",
        company: form.company.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        rating: form.rating || null,
        last_used: form.last_used || null,
        jobs_history: form.jobs_history.trim(),
        notes: form.notes.trim(),
        created_by: userId || "",
      };
      const res = await fetch("/api/apps/home/contractors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      const contractor = await res.json();
      onSave(contractor);
    } catch (err) {
      alert("Failed to add contractor: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  const datalistTrades = [...new Set([...CONTRACTOR_TRADES, ...trades])];
  const inputCls = "w-full surface-panel border border-subtle rounded px-2.5 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={handleSubmit} className="surface-card border border-subtle rounded-lg p-4 space-y-3 mb-2">
      <p className="text-xs font-semibold text-muted uppercase tracking-wide">New Contractor</p>
      <input className={inputCls} placeholder="Name (e.g. Mike Jones) *" value={form.name}
        onChange={e => set("name", e.target.value)} autoFocus required />
      <div className="grid grid-cols-2 gap-2">
        <input className={inputCls} placeholder="Trade (e.g. Electrician)" value={form.trade}
          onChange={e => set("trade", e.target.value)} list="contractor-trades" />
        <datalist id="contractor-trades">
          {datalistTrades.map(t => <option key={t} value={t} />)}
        </datalist>
        <input className={inputCls} placeholder="Company (optional)" value={form.company}
          onChange={e => set("company", e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input className={inputCls} type="tel" placeholder="Phone" value={form.phone}
          onChange={e => set("phone", e.target.value)} />
        <input className={inputCls} type="email" placeholder="Email" value={form.email}
          onChange={e => set("email", e.target.value)} />
      </div>
      <div className="flex items-center gap-3">
        <label className="text-xs text-faint">Rating</label>
        <StarRating value={form.rating} onChange={v => set("rating", v)} />
      </div>
      <div>
        <label className="block text-xs text-faint mb-1">Last used</label>
        <input className={inputCls} type="date" value={form.last_used}
          onChange={e => set("last_used", e.target.value)} />
      </div>
      <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Jobs history (past work done)"
        value={form.jobs_history} onChange={e => set("jobs_history", e.target.value)} />
      <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Notes (optional)"
        value={form.notes} onChange={e => set("notes", e.target.value)} />

      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button type="submit" disabled={saving || !form.name.trim()}
          className="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded">
          {saving ? "Saving..." : "Add Contractor"}
        </button>
      </div>
    </form>
  );
}

/* ── Contractor Card ── */
function ContractorCard({ contractor, expanded, onToggle, onUpdate, onDelete, trades = [] }) {
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  async function handleEditSave() {
    setSaving(true);
    try {
      const body = {
        ...editForm,
        rating: editForm.rating || null,
        last_used: editForm.last_used || null,
      };
      const res = await fetch(`/api/apps/home/contractors/${contractor.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) { onUpdate(await res.json()); setEditMode(false); }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${contractor.name}"?`)) return;
    await fetch(`/api/apps/home/contractors/${contractor.id}`, { method: "DELETE" });
    onDelete(contractor.id);
  }

  function startEdit() {
    setEditForm({
      name: contractor.name,
      trade: contractor.trade || "General",
      company: contractor.company || "",
      phone: contractor.phone || "",
      email: contractor.email || "",
      rating: contractor.rating || null,
      last_used: contractor.last_used || "",
      jobs_history: contractor.jobs_history || "",
      notes: contractor.notes || "",
    });
    setEditMode(true);
  }

  const datalistTrades = [...new Set([...CONTRACTOR_TRADES, ...trades])];
  const inputCls = "w-full surface-panel border border-subtle rounded px-2 py-1 text-xs text-default outline-none focus:border-indigo-500";

  return (
    <div className="border rounded-lg overflow-hidden transition-all surface-card border-subtle">
      <div className="flex items-start gap-2.5 px-3 py-2.5 cursor-pointer" onClick={onToggle}>
        <span className="w-2 h-2 rounded-full shrink-0 mt-1.5 bg-indigo-500" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-default">{contractor.name}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium surface-raised text-default">{contractor.trade || "General"}</span>
            {contractor.rating != null && <StarRating value={contractor.rating} readonly />}
            {contractor.company && (
              <span className="text-[10px] text-faint surface-raised px-1.5 py-0.5 rounded">{contractor.company}</span>
            )}
          </div>
        </div>
        <ChevronDown size={14} className={`text-faint shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>

      {expanded && (
        <div className="border-t border-subtle px-3 py-3">
          {editMode ? (
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-faint">Name</label>
                <input className={inputCls} value={editForm.name || ""}
                  onChange={e => setEditForm(p => ({ ...p, name: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Trade</label>
                  <input className={inputCls} value={editForm.trade || ""} list="contractor-trades-edit"
                    onChange={e => setEditForm(p => ({ ...p, trade: e.target.value }))} />
                  <datalist id="contractor-trades-edit">
                    {datalistTrades.map(t => <option key={t} value={t} />)}
                  </datalist>
                </div>
                <div>
                  <label className="text-[10px] text-faint">Company</label>
                  <input className={inputCls} value={editForm.company || ""}
                    onChange={e => setEditForm(p => ({ ...p, company: e.target.value }))} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-faint">Phone</label>
                  <input className={inputCls} type="tel" value={editForm.phone || ""}
                    onChange={e => setEditForm(p => ({ ...p, phone: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] text-faint">Email</label>
                  <input className={inputCls} type="email" value={editForm.email || ""}
                    onChange={e => setEditForm(p => ({ ...p, email: e.target.value }))} />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="text-[10px] text-faint">Rating</label>
                <StarRating value={editForm.rating} onChange={v => setEditForm(p => ({ ...p, rating: v }))} />
              </div>
              <div>
                <label className="text-[10px] text-faint">Last used</label>
                <input className={inputCls} type="date" value={editForm.last_used || ""}
                  onChange={e => setEditForm(p => ({ ...p, last_used: e.target.value }))} />
              </div>
              <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Jobs history"
                value={editForm.jobs_history || ""} onChange={e => setEditForm(p => ({ ...p, jobs_history: e.target.value }))} />
              <textarea className={`${inputCls} resize-none`} rows={2} placeholder="Notes"
                value={editForm.notes || ""} onChange={e => setEditForm(p => ({ ...p, notes: e.target.value }))} />
              <div className="flex gap-1">
                <button onClick={handleEditSave} disabled={saving}
                  className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded disabled:opacity-50">
                  {saving ? "Saving..." : "Save"}
                </button>
                <button onClick={() => setEditMode(false)} className="px-3 py-1 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mb-2">
                {contractor.phone && <div className="flex items-center gap-1"><Phone size={11} className="text-faint" /><a href={`tel:${contractor.phone}`} className="text-muted hover:text-[var(--ds-text)]" onClick={e => e.stopPropagation()}>{contractor.phone}</a></div>}
                {contractor.email && <div className="flex items-center gap-1"><Mail size={11} className="text-faint" /><a href={`mailto:${contractor.email}`} className="text-muted hover:text-[var(--ds-text)]" onClick={e => e.stopPropagation()}>{contractor.email}</a></div>}
                {contractor.last_used && <div><span className="text-faint">Last used: </span><span className="text-muted">{fmtRelative(contractor.last_used)}</span></div>}
              </div>
              {contractor.jobs_history && <div className="text-xs mb-2"><span className="text-faint">Jobs: </span><span className="text-muted">{contractor.jobs_history}</span></div>}
              {contractor.notes && <p className="text-xs text-faint italic mb-2">{contractor.notes}</p>}

              {/* Actions */}
              <div className="flex items-center gap-2 mt-3">
                <button onClick={startEdit}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] border border-subtle rounded">
                  <Edit2 size={11} /> Edit
                </button>
                <button onClick={handleDelete}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-red-500 hover:text-red-400 border border-red-900/40 rounded">
                  <Trash2 size={11} /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Contractors Tab ── */
function ContractorsTab({ userId }) {
  const [contractors, setContractors] = useState([]);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [tradeFilter, setTradeFilter] = useState("All");
  const [showAdd, setShowAdd] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      else if (tradeFilter !== "All") params.set("trade", tradeFilter);
      const res = await fetch(`/api/apps/home/contractors?${params}`);
      const d = await res.json();
      setContractors(d.contractors || []);
      if (d.trades?.length) setTrades(d.trades);
    } finally {
      setLoading(false);
    }
  }, [search, tradeFilter]);

  useEffect(() => { load(); }, [load]);

  const allTrades = ["All", ...trades];

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-subtle shrink-0">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            className="w-full surface-panel border border-subtle rounded pl-7 pr-2.5 py-1.5 text-xs text-default placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            placeholder="Search contractors..."
            value={search}
            onChange={e => { setSearch(e.target.value); setTradeFilter("All"); }}
          />
          {search && <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]"><X size={12} /></button>}
        </div>
        {!search && allTrades.length > 1 && (
          <select
            className="surface-panel border border-subtle rounded px-2 py-1.5 text-xs text-default focus:outline-none focus:border-indigo-500"
            value={tradeFilter}
            onChange={e => setTradeFilter(e.target.value)}
          >
            {allTrades.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <button
          onClick={() => setShowAdd(v => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors ${
            showAdd ? "surface-raised text-on-accent" : "bg-indigo-600 hover:bg-indigo-500 text-on-accent"
          }`}
        >
          {showAdd ? <X size={13} /> : <Plus size={13} />}
          {showAdd ? "Cancel" : "Add Contractor"}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0">
        {showAdd && (
          <AddContractorForm
            trades={trades}
            userId={userId}
            onSave={(contractor) => { setContractors(prev => [contractor, ...prev]); setShowAdd(false); setExpandedId(contractor.id); load(); }}
            onCancel={() => setShowAdd(false)}
          />
        )}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-faint text-sm">Loading...</div>
        ) : contractors.length === 0 ? (
          <PristineEmpty
            appId="home"
            blurb={getAppManifest("home")?.heroes?.contractors}
            records={contractors}
            loading={loading}
            filterActive={!!search.trim() || tradeFilter !== "All"}
            fallback={
              <div className="flex flex-col items-center justify-center h-48 text-faint">
                <HardHat size={32} className="text-default mb-3" />
                <p className="text-sm font-medium text-muted">
                  {search ? `No contractors matching "${search}"` : "No contractors yet"}
                </p>
                <p className="text-xs mt-1 text-faint">
                  {!search && 'Click "Add Contractor" to get started'}
                </p>
              </div>
            }
          />
        ) : (
          <div className="space-y-2">
            {contractors.map(contractor => (
              <ContractorCard
                key={contractor.id}
                contractor={contractor}
                expanded={expandedId === contractor.id}
                onToggle={() => setExpandedId(prev => prev === contractor.id ? null : contractor.id)}
                onUpdate={(updated) => setContractors(prev => prev.map(c => c.id === updated.id ? { ...c, ...updated } : c))}
                onDelete={(id) => { setContractors(prev => prev.filter(c => c.id !== id)); if (expandedId === id) setExpandedId(null); }}
                trades={trades}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
