import { useState, useEffect, useCallback, useRef } from "react";
import {
  Wrench, ShoppingCart, Shield, MapPin, HardHat, Settings,
  CheckCircle, Plus, ChevronDown, ChevronUp, X, Search,
  Clock, AlertCircle, CalendarCheck, RotateCcw, Trash2, Edit2,
  AlertTriangle, Camera, Image as ImageIcon,
} from "lucide-react";

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
          <AppliancesTab />
        )}
        {activeTab === "insurance" && (
          <InsuranceTab />
        )}
        {activeTab === "contractors" && (
          <ContractorsTab />
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
              <div className="flex flex-col items-center justify-center h-48 text-faint">
                <Wrench size={32} className="text-default mb-3" />
                <p className="text-sm font-medium text-muted">
                  {search ? `No tasks matching "${search}"` : "No maintenance tasks yet"}
                </p>
                <p className="text-xs mt-1 text-faint">
                  {!search && 'Click "Add Task" to get started'}
                </p>
              </div>
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

function AppliancesTab() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-faint">
      <ShoppingCart size={36} className="text-faint mb-3" />
      <p className="text-sm font-medium text-muted">Appliances</p>
      <p className="text-xs mt-1">Purchase history — coming soon</p>
    </div>
  );
}

function InsuranceTab() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-faint">
      <Shield size={36} className="text-faint mb-3" />
      <p className="text-sm font-medium text-muted">Insurance</p>
      <p className="text-xs mt-1">Valuations, coverage &amp; asset list — coming soon</p>
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
          <div className="flex flex-col items-center justify-center h-40 text-faint">
            <AlertTriangle size={32} className="text-default mb-2" />
            <p className="text-sm text-muted">{search ? `No issues matching "${search}"` : "No issues found"}</p>
            {filterStatus === "open" && !search && (
              <p className="text-xs text-faint mt-1">Click &quot;Add Issue&quot; to log one</p>
            )}
          </div>
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


function ContractorsTab() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-faint">
      <HardHat size={36} className="text-faint mb-3" />
      <p className="text-sm font-medium text-muted">Contractors</p>
      <p className="text-xs mt-1">Electricians, plumbers, roofers, painters &amp; more — coming soon</p>
    </div>
  );
}
