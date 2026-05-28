import { useState, useEffect, useRef } from "react";
import {
  ChevronRight, Loader2, Plus, Save, Edit3, X, Check,
  FileText, Clock, Users, Target, CheckCircle2, Tag,
  Search, Link, Paperclip, ExternalLink,
} from "lucide-react";

/* ── Constants ── */

export const STATUS_COLORS = {
  not_started: "bg-slate-600",
  in_progress: "bg-blue-600",
  done: "bg-emerald-600",
  blocked: "bg-red-600",
  deferred: "bg-amber-600",
  cancelled: "bg-gray-600",
};

export const PRIORITIES = ["high", "medium", "low"];
export const PRIORITY_COLORS = { high: "text-red-400", medium: "text-amber-400", low: "text-slate-400" };

const TRELLO_COLORS = {
  green: "bg-green-600", yellow: "bg-yellow-500", orange: "bg-orange-500",
  red: "bg-red-600", purple: "bg-purple-600", blue: "bg-blue-600",
  sky: "bg-sky-500", lime: "bg-lime-500", pink: "bg-pink-500",
  black: "bg-slate-700", null: "bg-slate-600", "": "bg-slate-600",
};

/* ── Reusable interactive components ── */

export function StatusBadge({ status, entityId, patchEntity, STATUSES }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (!patchEntity) {
    return (
      <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium text-white ${STATUS_COLORS[status] || "bg-slate-600"}`}>
        {status?.replace("_", " ")}
      </span>
    );
  }

  return (
    <span ref={ref} className="relative inline-block">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium text-white cursor-pointer hover:ring-1 hover:ring-white/30 ${STATUS_COLORS[status] || "bg-slate-600"}`}
      >
        {status?.replace("_", " ")}
      </button>
      {open && (
        <div className="absolute z-50 top-full left-0 mt-1 py-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl min-w-[140px]">
          {(STATUSES || []).map((s) => (
            <button
              key={s}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                if (s !== status) patchEntity(entityId, { status: s });
              }}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-slate-700 transition-colors flex items-center gap-2 ${s === status ? "text-white font-medium" : "text-slate-400"}`}
            >
              <div className={`w-2 h-2 rounded-full ${STATUS_COLORS[s]}`} />
              {s.replace("_", " ")}
              {s === status && <Check size={10} className="ml-auto" />}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

export function QuickAdd({ placeholder, onSubmit }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!value.trim() || busy) return;
    setBusy(true);
    try {
      await onSubmit(value.trim());
      setValue("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2">
      <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 focus-within:border-indigo-500/50 transition-colors">
        <Plus size={14} className="text-slate-500 shrink-0" />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none"
        />
      </div>
      {value.trim() && (
        <button
          type="submit"
          disabled={busy}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : "Add"}
        </button>
      )}
    </form>
  );
}

export function EditableDoD({ entityId, dod, patchEntity, userId }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(dod || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => { setDraft(dod || ""); setEditing(false); }, [entityId, dod]);

  async function handleSave() {
    setSaving(true);
    try {
      await patchEntity(entityId, { definition_of_done: draft, updated_by: userId });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div>
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
          <CheckCircle2 size={12} />
          Definition of Done
          <button
            onClick={() => setEditing(true)}
            className="ml-auto p-0.5 rounded text-slate-600 hover:text-slate-300 transition-colors"
            title="Edit definition of done"
          >
            <Edit3 size={11} />
          </button>
        </h3>
        {draft ? (
          <div className="px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-sm text-slate-300 whitespace-pre-wrap leading-relaxed font-mono">
            {draft}
          </div>
        ) : (
          <div className="text-xs text-slate-600 italic">
            No definition of done
            <button onClick={() => setEditing(true)} className="ml-2 text-indigo-400 hover:text-indigo-300">
              + add
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
        <CheckCircle2 size={12} />
        Definition of Done
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}
            Save
          </button>
          <button
            onClick={() => { setDraft(dod || ""); setEditing(false); }}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs transition-colors"
          >
            <X size={10} />
          </button>
        </div>
      </h3>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={4}
        className="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-indigo-500/50 text-sm text-slate-200 font-mono leading-relaxed resize-y outline-none focus:border-indigo-500 transition-colors"
        autoFocus
        placeholder="What does 'done' look like for this item?"
      />
    </div>
  );
}

export function EditableNotes({ entityId, notes, saveNotes }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(notes || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => { setDraft(notes || ""); setEditing(false); }, [entityId, notes]);

  async function handleSave() {
    setSaving(true);
    try {
      await saveNotes(entityId, draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div>
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
          <FileText size={12} />
          Notes
          {saveNotes && (
            <button
              onClick={() => setEditing(true)}
              className="ml-auto p-0.5 rounded text-slate-600 hover:text-slate-300 transition-colors"
              title="Edit notes"
            >
              <Edit3 size={11} />
            </button>
          )}
        </h3>
        {draft ? (
          <div className="px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-sm text-slate-300 whitespace-pre-wrap leading-relaxed font-mono">
            {draft}
          </div>
        ) : (
          <div className="text-xs text-slate-600 italic">
            No notes
            {saveNotes && (
              <button onClick={() => setEditing(true)} className="ml-2 text-indigo-400 hover:text-indigo-300">
                + add
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
        <FileText size={12} />
        Notes
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs transition-colors disabled:opacity-50"
          >
            {saving ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}
            Save
          </button>
          <button
            onClick={() => { setDraft(notes || ""); setEditing(false); }}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs transition-colors"
          >
            <X size={10} />
          </button>
        </div>
      </h3>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={8}
        className="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-indigo-500/50 text-sm text-slate-200 font-mono leading-relaxed resize-y outline-none focus:border-indigo-500 transition-colors"
        autoFocus
      />
    </div>
  );
}

export function PriorityBadge({ priority, entityId, patchEntity }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (!patchEntity) {
    return <span className={`text-xs ${PRIORITY_COLORS[priority] || "text-slate-400"}`}>{priority}</span>;
  }

  return (
    <span ref={ref} className="relative inline-block">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className={`text-xs cursor-pointer hover:underline ${PRIORITY_COLORS[priority] || "text-slate-400"}`}
      >
        {priority}
      </button>
      {open && (
        <div className="absolute z-50 top-full left-0 mt-1 py-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl min-w-[100px]">
          {PRIORITIES.map((p) => (
            <button
              key={p}
              onClick={(e) => { e.stopPropagation(); setOpen(false); if (p !== priority) patchEntity(entityId, { priority: p }); }}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-slate-700 transition-colors ${p === priority ? "text-white font-medium" : "text-slate-400"}`}
            >
              <span className={PRIORITY_COLORS[p]}>{p}</span>
              {p === priority && <Check size={10} className="inline ml-2" />}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

export function AssigneeField({ assignees, entityId, patchEntity, fieldName = "assigned_to", singleSelect = false }) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  async function handleOpen(e) {
    e.stopPropagation();
    if (!members) {
      try {
        const res = await fetch("/api/users?include_bots=true");
        const data = await res.json();
        setMembers(data);
      } catch { setMembers([]); }
    }
    setOpen(!open);
  }

  function toggleMember(name) {
    const current = assignees || [];
    let next;
    if (singleSelect) {
      next = current.length === 1 && current[0] === name ? [] : [name];
    } else {
      next = current.includes(name) ? current.filter((a) => a !== name) : [...current, name];
    }
    patchEntity(entityId, { [fieldName]: next.join(",") });
    setOpen(false);
  }

  const display = assignees && assignees.length > 0 ? assignees.join(", ") : "unassigned";

  if (!patchEntity) {
    return <span className="text-slate-300">{display}</span>;
  }

  return (
    <span ref={ref} className="relative inline-block">
      <button onClick={handleOpen} className="text-slate-300 hover:text-white hover:underline cursor-pointer transition-colors">
        {display}
      </button>
      {open && members && (
        <div className="absolute z-50 top-full left-0 mt-1 py-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl min-w-[140px]">
          {members.map((m) => (
            <button
              key={m.name}
              onClick={(e) => { e.stopPropagation(); toggleMember(m.name); }}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-slate-700 transition-colors flex items-center gap-2 ${(assignees || []).includes(m.name) ? "text-white font-medium" : "text-slate-400"}`}
            >
              {m.display_name}
              {(assignees || []).includes(m.name) && <Check size={10} className="ml-auto" />}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

export function DueDateField({ date, entityId, patchEntity, fieldName = "due_date" }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(date || "");

  useEffect(() => { setValue(date || ""); setEditing(false); }, [entityId, date]);

  if (!patchEntity) {
    return <span className="text-slate-300">{date || "—"}</span>;
  }

  if (!editing) {
    return (
      <button onClick={() => setEditing(true)} className="text-slate-300 hover:text-white hover:underline cursor-pointer transition-colors">
        {date || "set date"}
      </button>
    );
  }

  return (
    <span className="flex items-center gap-1">
      <input
        type="date"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-600 text-xs text-slate-200 outline-none focus:border-indigo-500"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter") { patchEntity(entityId, { [fieldName]: value }); setEditing(false); }
          if (e.key === "Escape") { setValue(date || ""); setEditing(false); }
        }}
      />
      <button onClick={() => { patchEntity(entityId, { [fieldName]: value }); setEditing(false); }} className="text-emerald-400 hover:text-emerald-300"><Check size={12} /></button>
      <button onClick={() => { setValue(date || ""); setEditing(false); }} className="text-slate-500 hover:text-slate-300"><X size={12} /></button>
    </span>
  );
}

export function CadenceField({ cadence, entityId, patchEntity }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(cadence || "");

  useEffect(() => { setValue(cadence || ""); setEditing(false); }, [entityId, cadence]);

  if (!patchEntity) {
    return <span className="text-slate-300">{cadence ? `${cadence}m` : "—"}</span>;
  }

  if (!editing) {
    return (
      <button onClick={() => setEditing(true)} className="text-slate-300 hover:text-white hover:underline cursor-pointer transition-colors" title="PM check-in cadence in minutes (empty = standard rotation)">
        {cadence ? `${cadence}m` : "default"}
      </button>
    );
  }

  function save() {
    const num = parseInt(value, 10);
    patchEntity(entityId, { pm_cadence_minutes: num > 0 ? num : 0 });
    setEditing(false);
  }

  return (
    <span className="flex items-center gap-1">
      <input
        type="number"
        min="0"
        step="30"
        placeholder="min"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-16 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-600 text-xs text-slate-200 outline-none focus:border-indigo-500"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") { setValue(cadence || ""); setEditing(false); }
        }}
      />
      <button onClick={save} className="text-emerald-400 hover:text-emerald-300"><Check size={12} /></button>
      <button onClick={() => { setValue(cadence || ""); setEditing(false); }} className="text-slate-500 hover:text-slate-300"><X size={12} /></button>
    </span>
  );
}

export function EditableTitle({ name, entityId, patchEntity }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name || "");

  useEffect(() => { setValue(name || ""); setEditing(false); }, [entityId, name]);

  if (!editing) {
    return (
      <h2
        className="text-lg font-semibold text-white cursor-pointer hover:text-indigo-300 transition-colors"
        onClick={() => patchEntity && setEditing(true)}
        title={patchEntity ? "Click to rename" : undefined}
      >
        {name}
      </h2>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="flex-1 text-lg font-semibold bg-slate-800 border border-indigo-500/50 rounded px-2 py-0.5 text-white outline-none focus:border-indigo-500"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter" && value.trim()) { patchEntity(entityId, { name: value.trim() }); setEditing(false); }
          if (e.key === "Escape") { setValue(name || ""); setEditing(false); }
        }}
      />
      <button onClick={() => { if (value.trim()) { patchEntity(entityId, { name: value.trim() }); setEditing(false); } }} className="text-emerald-400 hover:text-emerald-300"><Check size={16} /></button>
      <button onClick={() => { setValue(name || ""); setEditing(false); }} className="text-slate-500 hover:text-slate-300"><X size={16} /></button>
    </div>
  );
}

export function DeleteButton({ entityId, entityName, onDelete }) {
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <button
        onClick={() => setConfirming(true)}
        className="text-xs text-slate-600 hover:text-red-400 transition-colors"
        title="Delete"
      >
        Delete
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2 text-xs">
      <span className="text-red-400">Delete "{entityName}"?</span>
      <button
        onClick={() => { onDelete(entityId); setConfirming(false); }}
        className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-500 text-white font-medium"
      >
        Yes
      </button>
      <button
        onClick={() => setConfirming(false)}
        className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300"
      >
        No
      </button>
    </span>
  );
}

export function SearchBar({ onSelect }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const ref = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setResults(null); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function handleChange(e) {
    const q = e.target.value;
    setQuery(q);
    clearTimeout(timerRef.current);
    if (!q.trim()) { setResults(null); return; }
    timerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await fetch(`/api/apps/goals/search?q=${encodeURIComponent(q.trim())}`);
        const data = await res.json();
        setResults(data.results || []);
      } catch { setResults([]); }
      setSearching(false);
    }, 300);
  }

  const typeIcon = { goal: "\u{1F3AF}", project: "\u{1F4C1}", task: "\u{2705}" };

  return (
    <div ref={ref} className="relative">
      <input
        type="text"
        value={query}
        onChange={handleChange}
        placeholder="Search..."
        className="w-32 lg:w-44 px-2 py-1 rounded bg-slate-800/60 border border-slate-700/50 text-xs text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500/50 focus:w-48 lg:focus:w-56 transition-all"
      />
      {results && results.length > 0 && (
        <div className="absolute z-50 top-full right-0 mt-1 py-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl min-w-[250px] max-h-64 overflow-y-auto">
          {results.map((r) => (
            <button
              key={r.id}
              onClick={() => { onSelect(r); setQuery(""); setResults(null); }}
              className="w-full text-left px-3 py-2 text-xs hover:bg-slate-700 transition-colors flex items-center gap-2"
            >
              <span>{typeIcon[r.type] || "\u{2022}"}</span>
              <span className="text-slate-200 truncate flex-1">{r.name}</span>
              <span className="text-slate-600">{r.type}</span>
              {r.match === "notes" && <span className="text-slate-600 text-[10px]">(notes)</span>}
            </button>
          ))}
        </div>
      )}
      {results && results.length === 0 && query.trim() && (
        <div className="absolute z-50 top-full right-0 mt-1 py-2 px-3 bg-slate-800 border border-slate-700 rounded-lg shadow-xl text-xs text-slate-500">
          No results
        </div>
      )}
    </div>
  );
}

/* ── Task detail view (shared between GoalsApp and TasksApp) ── */

export function TaskView({ task, onBack, onTaskClick, onProjectClick, statusColor, priorityColor, userId, patchEntity, saveNotes, apiMutate, onRefresh, STATUSES, onDelete, refreshKey, onOpenApp }) {
  async function handleCreateSubtask(name) {
    await apiMutate("/api/apps/goals/tasks", "POST", {
      project_id: task.project_id, name, created_by: userId,
      parent_task_id: task.id,
    });
    onRefresh?.();
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          {(onBack || task.project_id) && (
            <button onClick={() => onBack ? onBack() : onProjectClick?.(task.project_id)} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors" title={onBack ? "Back to tasks" : "Back to project"}>
              <ChevronRight size={18} className="rotate-180" />
            </button>
          )}
          <span className="text-slate-500 text-sm font-semibold shrink-0">TASK:</span>
          <EditableTitle name={task.name} entityId={task.id} patchEntity={patchEntity} />
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-slate-400">
          <StatusBadge status={task.status} entityId={task.id} patchEntity={patchEntity} STATUSES={STATUSES} />
          <PriorityBadge priority={task.priority} entityId={task.id} patchEntity={patchEntity} />
          <span className="text-slate-600">|</span>
          <button onClick={() => { navigator.clipboard.writeText(task.id); }} className="text-slate-500 hover:text-slate-200 cursor-pointer transition-colors" title="Copy ID">{task.id}</button>
          <DeleteButton entityId={task.id} entityName={task.name} onDelete={onDelete} />
        </div>
      </div>

      {/* Metadata grid */}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="flex items-start gap-2">
          <Users size={14} className="text-slate-500 mt-0.5 shrink-0" />
          <div>
            <div className="text-xs text-slate-500">Assigned to</div>
            <AssigneeField assignees={task.assigned_to ? [task.assigned_to] : []} entityId={task.id} patchEntity={patchEntity} singleSelect />
          </div>
        </div>
        <div className="flex items-start gap-2">
          <Clock size={14} className="text-slate-500 mt-0.5 shrink-0" />
          <div>
            <div className="text-xs text-slate-500">Due date</div>
            <DueDateField date={task.due_date} entityId={task.id} patchEntity={patchEntity} />
          </div>
        </div>
        {task.depends_on && task.depends_on.length > 0 && (
          <div className="col-span-2 flex items-start gap-2">
            <Target size={14} className="text-slate-500 mt-0.5 shrink-0" />
            <div>
              <div className="text-xs text-slate-500">Depends on</div>
              <div className="text-slate-300">{task.depends_on.join(", ")}</div>
            </div>
          </div>
        )}
        {/* Project link — visible when accessed from TasksApp */}
        {onBack && task.project_name && (
          <div className="flex items-start gap-2">
            <FileText size={14} className="text-slate-500 mt-0.5 shrink-0" />
            <div>
              <div className="text-xs text-slate-500">Project</div>
              <button
                onClick={() => onOpenApp?.("goals", { projectId: task.project_id })}
                className="text-indigo-400 hover:text-indigo-300 hover:underline transition-colors"
              >
                {task.project_name}
              </button>
            </div>
          </div>
        )}
        {onBack && task.goal_name && (
          <div className="flex items-start gap-2">
            <Target size={14} className="text-slate-500 mt-0.5 shrink-0" />
            <div>
              <div className="text-xs text-slate-500">Goal</div>
              <button
                onClick={() => onOpenApp?.("goals", { goalId: task.goal_id })}
                className="text-indigo-400 hover:text-indigo-300 hover:underline transition-colors"
              >
                {task.goal_name}
              </button>
            </div>
          </div>
        )}
        {task.created_by && (
          <div>
            <div className="text-xs text-slate-500">Created by</div>
            <div className="text-slate-300">{task.created_by}</div>
          </div>
        )}
        {task.created_at && (
          <div>
            <div className="text-xs text-slate-500">Created</div>
            <div className="text-slate-300">{task.created_at.slice(0, 16).replace("T", " ")}</div>
          </div>
        )}
      </div>

      {/* Trello Labels */}
      {task.trello_card_id && task.trello_board && (
        <TrelloLabels
          cardId={task.trello_card_id}
          boardName={task.trello_board}
          initialLabels={task.trello_labels || []}
          onRefresh={onRefresh}
        />
      )}

      {/* Notes */}
      <EditableNotes entityId={task.id} notes={task.notes} saveNotes={saveNotes} />

      {/* Definition of Done */}
      <EditableDoD entityId={task.id} dod={task.definition_of_done} patchEntity={patchEntity} userId={userId} />

      {/* Documents */}
      <LinkedDocs entityId={task.id} userId={userId} refreshKey={refreshKey} onOpenApp={onOpenApp} />

      {/* Artifacts */}
      <LinkedArtifacts entityId={task.id} refreshKey={refreshKey} />

      {/* Subtasks */}
      <div>
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
          Subtasks {task.subtasks && task.subtasks.length > 0 ? `(${task.subtasks.length})` : ""}
        </h3>
        <QuickAdd placeholder="New subtask..." onSubmit={handleCreateSubtask} />
        {task.subtasks && task.subtasks.length > 0 && (
          <div className="space-y-1.5 mt-2">
            {task.subtasks.map((s) => (
              <div
                key={s.id}
                onClick={() => onTaskClick(s.id)}
                className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 transition-colors cursor-pointer"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <StatusBadge status={s.status} entityId={s.id} patchEntity={patchEntity} STATUSES={STATUSES} />
                  <span className="text-sm text-slate-200 text-left">
                    {s.name}
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0 text-xs text-slate-500">
                  {s.assigned_to && <span>{s.assigned_to}</span>}
                  <PriorityBadge priority={s.priority} entityId={s.id} patchEntity={patchEntity} />
                  <ChevronRight size={12} className="text-slate-600" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <HistorySection
        entityId={task.id}
        history={task.history}
        userId={userId}
        patchEntity={patchEntity}
        onRefresh={onRefresh}
      />
    </div>
  );
}

/* ── TrelloLabels ── */

export function TrelloLabels({ cardId, boardName, initialLabels, onRefresh }) {
  const [labels, setLabels] = useState(initialLabels);
  const [showPicker, setShowPicker] = useState(false);
  const [boardLabels, setBoardLabels] = useState(null);
  const [loading, setLoading] = useState(false);
  const pickerRef = useRef(null);

  useEffect(() => { setLabels(initialLabels); }, [initialLabels]);

  // Close picker on outside click
  useEffect(() => {
    if (!showPicker) return;
    function handleClick(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) setShowPicker(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showPicker]);

  async function openPicker() {
    setShowPicker(true);
    if (boardLabels) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/apps/goals/trello/board-labels/${encodeURIComponent(boardName)}`);
      const data = await res.json();
      setBoardLabels(data.labels || []);
    } catch { setBoardLabels([]); }
    setLoading(false);
  }

  async function addLabel(label) {
    try {
      await fetch(`/api/apps/goals/trello/card-labels/${encodeURIComponent(cardId)}/add`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ board_name: boardName, label_id: label.id }),
      });
      setLabels((prev) => [...prev, label]);
    } catch { /* ignore */ }
  }

  async function removeLabel(label) {
    try {
      await fetch(`/api/apps/goals/trello/card-labels/${encodeURIComponent(cardId)}/remove`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ board_name: boardName, label_id: label.id }),
      });
      setLabels((prev) => prev.filter((l) => l.id !== label.id));
    } catch { /* ignore */ }
  }

  const currentIds = new Set(labels.map((l) => l.id));
  const available = (boardLabels || []).filter((l) => !currentIds.has(l.id) && (l.name || l.color));

  return (
    <div>
      <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
        <Tag size={12} />
        Trello Labels
      </h3>
      <div className="flex flex-wrap items-center gap-1.5 relative">
        {labels.map((l) => (
          <span
            key={l.id}
            className={`group inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs text-white ${TRELLO_COLORS[l.color] || "bg-slate-600"}`}
          >
            {l.name || l.color || "?"}
            <button
              onClick={() => removeLabel(l)}
              className="opacity-0 group-hover:opacity-100 transition-opacity"
              title="Remove label"
            >
              <X size={10} />
            </button>
          </span>
        ))}
        <button
          onClick={openPicker}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs text-slate-500 border border-slate-700 hover:text-slate-300 hover:border-slate-500 transition-colors"
        >
          <Plus size={10} /> Label
        </button>
        {showPicker && (
          <div ref={pickerRef} className="absolute top-full left-0 mt-1 z-20 w-64 bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-2 max-h-60 overflow-y-auto">
            {loading && <div className="text-xs text-slate-500 p-2">Loading...</div>}
            {!loading && available.length === 0 && <div className="text-xs text-slate-500 p-2">No more labels available</div>}
            {!loading && available.map((l) => (
              <button
                key={l.id}
                onClick={() => { addLabel(l); setShowPicker(false); }}
                className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-xs text-left hover:bg-slate-700 transition-colors"
              >
                <span className={`w-3 h-3 rounded-sm shrink-0 ${TRELLO_COLORS[l.color] || "bg-slate-600"}`} />
                <span className="text-slate-300">{l.name || `(${l.color})`}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── LinkedDocs ── */

export function LinkedDocs({ entityId, userId, refreshKey, onOpenApp }) {
  const [docs, setDocs] = useState(null);
  const [mode, setMode] = useState(null); // null | "create" | "link"
  const [newTitle, setNewTitle] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const searchTimer = useRef(null);
  const dropdownRef = useRef(null);

  const linkedIds = new Set((docs || []).map((d) => d.id));

  useEffect(() => {
    if (!entityId) return;
    reloadDocs();
  }, [entityId, refreshKey]);

  async function reloadDocs() {
    try {
      const r = await fetch(`/api/apps/documents/for-entity/${entityId}`);
      const data = await r.json();
      setDocs(data.documents || []);
    } catch {
      setDocs([]);
    }
  }

  // Debounced search
  useEffect(() => {
    if (mode !== "link") return;
    if (!searchQuery.trim()) { setSearchResults([]); return; }
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await fetch(`/api/apps/documents/search?q=${encodeURIComponent(searchQuery.trim())}`);
        const data = await r.json();
        setSearchResults((data.results || []).filter((d) => !linkedIds.has(d.id)));
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(searchTimer.current);
  }, [searchQuery, mode]);

  // Also load recent docs when link mode opens (so user sees options before typing)
  useEffect(() => {
    if (mode !== "link") return;
    (async () => {
      try {
        const r = await fetch("/api/apps/documents");
        const data = await r.json();
        setSearchResults((data.documents || []).filter((d) => !linkedIds.has(d.id)).slice(0, 8));
      } catch {}
    })();
  }, [mode]);

  // Close dropdown on outside click
  useEffect(() => {
    if (mode !== "link") return;
    const handler = (e) => { if (dropdownRef.current && !dropdownRef.current.contains(e.target)) resetMode(); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [mode]);

  function resetMode() {
    setMode(null);
    setNewTitle("");
    setSearchQuery("");
    setSearchResults([]);
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    try {
      const res = await fetch("/api/apps/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle.trim(), created_by: userId, related_entity_id: entityId }),
      });
      if (!res.ok) return;
      const doc = await res.json();
      onOpenApp?.("document", { docId: doc.id, title: doc.title || newTitle.trim() });
      resetMode();
      await reloadDocs();
    } catch {}
  }

  async function handleLink(docId) {
    try {
      await fetch(`/api/apps/documents/${docId}/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: entityId, created_by: userId }),
      });
      resetMode();
      await reloadDocs();
    } catch {}
  }

  async function handleUnlink(docId) {
    try {
      await fetch(`/api/apps/documents/${docId}/unlink`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: entityId }),
      });
      await reloadDocs();
    } catch {}
  }

  if (docs === null) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider">
          <FileText size={12} />
          Documents {docs.length > 0 ? `(${docs.length})` : ""}
        </h3>
        {!mode && (
          <div className="flex items-center gap-2">
            <button onClick={() => setMode("link")} className="text-xs text-slate-600 hover:text-slate-300 flex items-center gap-0.5">
              <Link size={10} /> Link existing
            </button>
            <button onClick={() => setMode("create")} className="text-xs text-slate-600 hover:text-slate-300 flex items-center gap-0.5">
              <Plus size={10} /> New doc
            </button>
          </div>
        )}
      </div>

      {/* Create new doc */}
      {mode === "create" && (
        <form onSubmit={handleCreate} className="flex items-center gap-2 mb-2">
          <input
            autoFocus
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") resetMode(); }}
            placeholder="Document title..."
            className="flex-1 bg-slate-800 text-sm text-slate-200 px-2 py-1 rounded border border-slate-700 outline-none"
          />
          <button type="submit" className="px-2 py-1 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-500">Create</button>
          <button type="button" onClick={resetMode} className="text-slate-500 hover:text-white"><X size={12} /></button>
        </form>
      )}

      {/* Link existing doc — searchable picker */}
      {mode === "link" && (
        <div ref={dropdownRef} className="relative mb-2">
          <div className="flex items-center gap-2 bg-slate-800 rounded border border-slate-700 px-2 py-1">
            <Search size={12} className="text-slate-500 shrink-0" />
            <input
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Escape") resetMode(); }}
              placeholder="Search documents by title..."
              className="flex-1 bg-transparent text-sm text-slate-200 outline-none"
            />
            {searching && <Loader2 size={12} className="animate-spin text-slate-500" />}
            <button type="button" onClick={resetMode} className="text-slate-500 hover:text-white"><X size={12} /></button>
          </div>
          {searchResults.length > 0 && (
            <div className="absolute z-20 left-0 right-0 mt-1 max-h-48 overflow-y-auto bg-slate-800 border border-slate-700 rounded shadow-lg">
              {searchResults.map((d) => (
                <button
                  key={d.id}
                  onClick={() => handleLink(d.id)}
                  className="w-full text-left px-3 py-1.5 hover:bg-slate-700 transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText size={12} className="text-slate-500 shrink-0" />
                    <span className="text-sm text-slate-200 truncate">{d.title}</span>
                  </div>
                  <span className="text-xs text-slate-600 shrink-0">{d.word_count || 0}w</span>
                </button>
              ))}
            </div>
          )}
          {searchQuery.trim() && !searching && searchResults.length === 0 && (
            <div className="absolute z-20 left-0 right-0 mt-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded text-xs text-slate-500">
              No matching documents
            </div>
          )}
        </div>
      )}

      {/* Linked doc list */}
      {docs.length > 0 ? (
        <div className="space-y-1">
          {docs.map((d) => (
            <div
              key={d.id}
              onClick={() => onOpenApp?.("document", { docId: d.id, title: d.title || d.id })}
              className="group flex items-center justify-between px-3 py-1.5 rounded bg-slate-800/50 border border-slate-700/50 text-sm cursor-pointer hover:bg-slate-700/50 transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileText size={12} className="text-indigo-400/70 shrink-0" />
                <span className="text-slate-300 truncate">{d.title}</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-600 shrink-0">
                <span>{d.word_count || 0}w</span>
                {d.updated_at && <span>{d.updated_at.slice(0, 10)}</span>}
                <button
                  onClick={(e) => { e.stopPropagation(); handleUnlink(d.id); }}
                  className="opacity-0 group-hover:opacity-100 text-slate-600 hover:text-red-400 transition-opacity"
                  title="Unlink document"
                >
                  <X size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : !mode ? (
        <p className="text-xs text-slate-600">No linked documents</p>
      ) : null}
    </div>
  );
}

/* ── HistorySection ── */

export function HistorySection({ entityId, history, userId, patchEntity, onRefresh }) {
  const [noteText, setNoteText] = useState("");
  const [adding, setAdding] = useState(false);

  async function handleAddNote(e) {
    e.preventDefault();
    if (!noteText.trim()) return;
    setAdding(true);
    try {
      await patchEntity(entityId, { note: noteText.trim(), updated_by: userId });
      setNoteText("");
      onRefresh?.();
    } catch {} finally { setAdding(false); }
  }

  const entries = (history || []).slice().reverse();

  return (
    <div>
      <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
        <Clock size={12} />
        History
      </h3>
      <form onSubmit={handleAddNote} className="flex gap-2 mb-2">
        <input
          type="text"
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          placeholder="Add a note or directive..."
          className="flex-1 px-2.5 py-1.5 rounded bg-slate-800/70 border border-slate-700/50 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-600 transition-colors"
        />
        <button
          type="submit"
          disabled={adding || !noteText.trim()}
          className="px-3 py-1.5 text-xs font-medium rounded bg-cyan-800/50 hover:bg-cyan-700/50 text-cyan-300 disabled:opacity-30 transition-colors"
        >
          {adding ? "..." : "Add"}
        </button>
      </form>
      {entries.length > 0 ? (
        <div className="space-y-0.5 max-h-48 overflow-y-auto">
          {entries.map((h, i) => (
            <div key={i} className="flex gap-2 text-xs text-slate-500 py-1 border-b border-slate-800/50 last:border-0">
              <span className="text-slate-600 shrink-0 w-32">
                {(h.timestamp || h.date || "").slice(0, 16).replace("T", " ")}
              </span>
              <span className="text-cyan-700 shrink-0 w-16 truncate">{h.by || ""}</span>
              <span className="text-slate-400">{h.note || h.action || h.change || h.text || JSON.stringify(h)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-600">No history yet</p>
      )}
    </div>
  );
}

/* ── LinkedArtifacts ── */

export function LinkedArtifacts({ entityId, refreshKey }) {
  const [artifacts, setArtifacts] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [expandedContent, setExpandedContent] = useState("");
  const [loadingContent, setLoadingContent] = useState(false);

  useEffect(() => {
    if (!entityId) return;
    loadArtifacts();
  }, [entityId, refreshKey]);

  async function loadArtifacts() {
    try {
      const r = await fetch(`/api/artifacts/for-entity/${entityId}`);
      const data = await r.json();
      setArtifacts(data.artifacts || []);
    } catch {
      setArtifacts([]);
    }
  }

  async function toggleExpand(artifactId) {
    if (expandedId === artifactId) {
      setExpandedId(null);
      setExpandedContent("");
      return;
    }
    setExpandedId(artifactId);
    setLoadingContent(true);
    try {
      const r = await fetch(`/api/artifacts/${artifactId}`);
      const data = await r.json();
      setExpandedContent(data.content || "(no text content)");
    } catch {
      setExpandedContent("(failed to load content)");
    } finally {
      setLoadingContent(false);
    }
  }

  function humanSize(bytes) {
    if (!bytes) return "0 B";
    for (const unit of ["B", "KB", "MB", "GB"]) {
      if (bytes < 1024) return `${Math.round(bytes)} ${unit}`;
      bytes /= 1024;
    }
    return `${bytes.toFixed(1)} TB`;
  }

  if (artifacts === null || artifacts.length === 0) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-slate-500 uppercase tracking-wider">
          <Paperclip size={12} />
          Artifacts ({artifacts.length})
        </h3>
      </div>
      <div className="space-y-1">
        {artifacts.map((a) => (
          <div key={a.id}>
            <button
              onClick={() => toggleExpand(a.id)}
              className="w-full text-left group flex items-center justify-between px-3 py-1.5 rounded bg-slate-800/50 border border-slate-700/50 text-sm cursor-pointer hover:bg-slate-700/50 transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0">
                <Paperclip size={12} className="text-amber-400/70 shrink-0" />
                <span className="text-slate-300 truncate">{a.name}</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-600 shrink-0">
                <span>{humanSize(a.size_bytes)}</span>
                {a.created_at && <span>{a.created_at.slice(0, 10)}</span>}
                <ChevronRight size={12} className={`transition-transform ${expandedId === a.id ? "rotate-90" : ""}`} />
              </div>
            </button>
            {expandedId === a.id && (
              <div className="mt-1 mx-1 rounded bg-slate-900/80 border border-slate-700/50 overflow-hidden">
                {loadingContent ? (
                  <div className="flex items-center gap-2 px-3 py-3 text-xs text-slate-500">
                    <Loader2 size={12} className="animate-spin" /> Loading...
                  </div>
                ) : (
                  <pre className="px-3 py-2 text-[11px] text-slate-300 whitespace-pre-wrap max-h-80 overflow-y-auto leading-relaxed font-mono">
                    {expandedContent}
                  </pre>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
