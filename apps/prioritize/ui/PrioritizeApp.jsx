import { useState, useEffect, useCallback } from "react";
import {
  Star, ChevronUp, ChevronDown, ChevronsUp, ChevronsDown,
  X, ArrowUpFromLine, Loader2, Target, Bell, BellRing,
  Car, AlertTriangle, FolderKanban, CheckSquare, BellOff, Users,
  CalendarClock, ListTodo, Wrench, HeartPulse, Activity, FlaskConical,
} from "lucide-react";

const API = window.__API_BASE ?? "";

const SOURCE_LABELS = {
  goal: "Goal",
  project: "Project",
  task: "Task",
  reminder: "Reminder",
  nag: "Nag",
  auto_issue: "Auto Issue",
  schedule: "Schedule",
  todo: "To-Do",
  home_task: "Home",
  med_refill: "Refill",
  med_treatment: "Treatment",
  med_followup: "Follow-up",
  med_lab_missing: "Lab Results",
};

const SOURCE_ICONS = {
  goal: Target,
  project: FolderKanban,
  task: CheckSquare,
  reminder: Bell,
  nag: BellRing,
  auto_issue: Car,
  schedule: CalendarClock,
  todo: ListTodo,
  home_task: Wrench,
  med_refill: HeartPulse,
  med_treatment: Activity,
  med_followup: CalendarClock,
  med_lab_missing: FlaskConical,
};

const SOURCE_COLORS = {
  goal: "text-amber-400",
  project: "text-blue-400",
  task: "text-emerald-400",
  reminder: "text-violet-400",
  nag: "text-pink-400",
  auto_issue: "text-orange-400",
  schedule: "text-cyan-400",
  todo: "text-amber-400",
  home_task: "text-lime-400",
  med_refill: "text-rose-400",
  med_treatment: "text-teal-400",
  med_followup: "text-sky-400",
  med_lab_missing: "text-purple-400",
};

const SEVERITY_COLORS = {
  critical: "bg-red-600",
  major: "bg-orange-500",
  moderate: "bg-yellow-500",
  minor: "bg-slate-500",
};

const PRIORITY_COLORS = {
  critical: "text-red-400",
  high: "text-orange-400",
  medium: "text-yellow-400",
  low: "text-slate-400",
};

const FLAT_BACKLOG_GROUPS = [
  { key: "todo", label: "To-Do", icon: ListTodo },
  { key: "schedules", label: "Schedules", icon: CalendarClock },
  { key: "reminders", label: "Reminders", icon: Bell },
  { key: "nags", label: "Nags", icon: BellRing },
  { key: "auto_issues", label: "Auto Issues", icon: Car },
  { key: "home_tasks", label: "Home Maintenance", icon: Wrench },
  { key: "med_refills", label: "Medication Refills", icon: HeartPulse },
  { key: "med_treatments", label: "Treatments", icon: Activity },
  { key: "med_followups", label: "Follow-ups", icon: CalendarClock },
  { key: "med_lab_missing", label: "Lab Results Needed", icon: FlaskConical },
];

export default function PrioritizeApp({ userId, onOpenApp, isActive, refreshKey, onFocusChanged }) {
  const [tab, setTab] = useState("mine"); // "mine" | "family"
  const [slots, setSlots] = useState([]);
  const [backlog, setBacklog] = useState({});
  const [nagEnabled, setNagEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [familyData, setFamilyData] = useState([]);
  const [familyLoading, setFamilyLoading] = useState(false);

  const loadData = useCallback(async () => {
    if (!userId) return;
    try {
      const [focusRes, backlogRes] = await Promise.all([
        fetch(`${API}/api/apps/prioritize/focus?user_id=${userId}`),
        fetch(`${API}/api/apps/prioritize/backlog?user_id=${userId}`),
      ]);
      if (focusRes.ok) {
        const fd = await focusRes.json();
        setSlots(fd.slots || []);
        setNagEnabled(fd.focus_nag_enabled ?? true);
      }
      if (backlogRes.ok) {
        setBacklog(await backlogRes.json());
      }
    } catch {}
    setLoading(false);
  }, [userId]);

  const loadFamily = useCallback(async () => {
    setFamilyLoading(true);
    try {
      const res = await fetch(`${API}/api/apps/prioritize/family`);
      if (res.ok) {
        const d = await res.json();
        setFamilyData(d.family || []);
      }
    } catch {}
    setFamilyLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => {
    if (isActive) { loadData(); if (tab === "family") loadFamily(); }
  }, [isActive, loadData, loadFamily, tab]);
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadData();
    if (tab === "family") loadFamily();
  }, [refreshKey, loadData, loadFamily, tab]);
  useEffect(() => {
    if (tab === "family" && familyData.length === 0) loadFamily();
  }, [tab, familyData.length, loadFamily]);

  async function handlePromote(source_type, source_id) {
    setActing(true);
    try {
      await fetch(`${API}/api/apps/prioritize/focus`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, source_type, source_id }),
      });
      await loadData();
      onFocusChanged?.();
    } catch {}
    setActing(false);
  }

  async function handleClearSlot(slot_number) {
    setActing(true);
    try {
      await fetch(`${API}/api/apps/prioritize/focus/${slot_number}?user_id=${userId}`, {
        method: "DELETE",
      });
      await loadData();
      onFocusChanged?.();
    } catch {}
    setActing(false);
  }

  async function handleReorder(direction, slotIndex) {
    if (slots.length < 2) return;
    const ids = slots.map(s => s.source_id);
    const swapWith = direction === "up" ? slotIndex - 1 : slotIndex + 1;
    if (swapWith < 0 || swapWith >= ids.length) return;
    [ids[slotIndex], ids[swapWith]] = [ids[swapWith], ids[slotIndex]];
    setActing(true);
    try {
      await fetch(`${API}/api/apps/prioritize/focus/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, ordered_source_ids: ids }),
      });
      await loadData();
      onFocusChanged?.();
    } catch {}
    setActing(false);
  }

  async function handleMoveToTop(slotIndex) {
    if (slotIndex === 0) return;
    const ids = slots.map(s => s.source_id);
    const [moved] = ids.splice(slotIndex, 1);
    ids.unshift(moved);
    setActing(true);
    try {
      await fetch(`${API}/api/apps/prioritize/focus/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, ordered_source_ids: ids }),
      });
      await loadData();
      onFocusChanged?.();
    } catch {}
    setActing(false);
  }

  async function handleMoveToBottom(slotIndex) {
    if (slotIndex === slots.length - 1) return;
    const ids = slots.map(s => s.source_id);
    const [moved] = ids.splice(slotIndex, 1);
    ids.push(moved);
    setActing(true);
    try {
      await fetch(`${API}/api/apps/prioritize/focus/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, ordered_source_ids: ids }),
      });
      await loadData();
      onFocusChanged?.();
    } catch {}
    setActing(false);
  }

  async function handleToggleNag() {
    const next = !nagEnabled;
    setNagEnabled(next);
    try {
      await fetch(`${API}/api/apps/prioritize/nag-toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, enabled: next }),
      });
    } catch {}
  }

  function openSource(source_type, source_id, item) {
    if (source_type === "goal") {
      onOpenApp?.("goals", { goalId: source_id });
    } else if (source_type === "project") {
      onOpenApp?.("goals", { projectId: source_id });
    } else if (source_type === "task") {
      onOpenApp?.("goals", { taskId: source_id });
    } else if (source_type === "nag") {
      onOpenApp?.("reminders", { tab: "nags" });
    } else if (source_type === "reminder") {
      onOpenApp?.("reminders", { tab: "reminders" });
    } else if (source_type === "auto_issue") {
      const vid = item?.vehicle_id || "";
      if (vid) onOpenApp?.("auto-vehicle", { autoVehicleId: vid });
      else onOpenApp?.("auto");
    } else if (source_type === "schedule") {
      onOpenApp?.("schedules", { scheduleId: source_id });
    } else if (source_type === "todo") {
      onOpenApp?.("todo");
    } else if (source_type === "home_task") {
      onOpenApp?.("home", { tab: "maintenance" });
    } else if (["med_refill", "med_treatment", "med_followup", "med_lab_missing"].includes(source_type)) {
      onOpenApp?.("medical");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={18} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }

  // Count total backlog items including nested goals tree
  const goalsTree = backlog.goals_tree || [];
  let goalsCount = 0;
  for (const g of goalsTree) {
    goalsCount++; // goal itself
    for (const p of (g.projects || [])) {
      goalsCount++; // project
      goalsCount += (p.tasks || []).length;
    }
  }
  const flatCount = FLAT_BACKLOG_GROUPS.reduce((sum, { key }) => sum + (backlog[key]?.length || 0), 0);
  const totalBacklog = goalsCount + flatCount;

  // Set of source IDs currently in focus (for dimming in backlog)
  const focusedIds = new Set(slots.map(s => s.source_id));

  return (
    <div className="flex flex-col h-full w-full overflow-y-auto">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setTab("mine")}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              tab === "mine" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
            }`}
          >Mine</button>
          <button
            onClick={() => setTab("family")}
            className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded transition-colors ${
              tab === "family" ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
            }`}
          ><Users size={11} /> Family</button>
        </div>
        {tab === "mine" && (
          <button
            onClick={handleToggleNag}
            className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
              nagEnabled
                ? "text-violet-400 hover:bg-violet-900/30"
                : "text-slate-500 hover:bg-slate-700"
            }`}
            title={nagEnabled ? "Daily focus nag is ON — click to pause" : "Daily focus nag is OFF — click to enable"}
          >
            {nagEnabled ? <BellRing size={12} /> : <BellOff size={12} />}
            {nagEnabled ? "Nag on" : "Nag off"}
          </button>
        )}
      </div>

      {tab === "family" ? (
        <FamilyView data={familyData} loading={familyLoading} onOpenApp={onOpenApp} />
      ) : (
      <div className="p-3 space-y-4">
        {/* Focus Section */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Star size={14} className="text-amber-400" />
            <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Focus</span>
            <span className="text-xs text-slate-500">{slots.length}/3</span>
          </div>

          {slots.length === 0 ? (
            <div className="text-sm text-slate-500 italic px-2 py-4 text-center border border-dashed border-slate-700 rounded-lg">
              No focus items yet. Promote something from the backlog below.
            </div>
          ) : (
            <div className="space-y-1.5">
              {slots.map((slot, idx) => (
                <FocusCard
                  key={slot.id}
                  slot={slot}
                  index={idx}
                  total={slots.length}
                  onClear={() => handleClearSlot(slot.slot_number)}
                  onMoveUp={() => handleReorder("up", idx)}
                  onMoveDown={() => handleReorder("down", idx)}
                  onMoveToTop={() => handleMoveToTop(idx)}
                  onMoveToBottom={() => handleMoveToBottom(idx)}
                  onOpen={() => openSource(slot.source_type, slot.source_id, slot.item)}
                  disabled={acting}
                />
              ))}
            </div>
          )}
        </div>

        {/* Backlog Section */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Backlog</span>
            <span className="text-xs text-slate-500">{totalBacklog} items</span>
          </div>

          {totalBacklog === 0 ? (
            <div className="text-sm text-slate-500 italic px-2 py-4 text-center">
              Nothing in your backlog. All clear!
            </div>
          ) : (
            <div className="space-y-3">
              {/* Goals hierarchy */}
              {goalsTree.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1 px-1">
                    <Target size={12} className="text-slate-500" />
                    <span className="text-xs font-medium text-slate-400">Goals</span>
                    <span className="text-[10px] text-slate-600">({goalsCount})</span>
                  </div>
                  <div className="space-y-0.5">
                    {goalsTree.map(goal => (
                      <GoalsTreeNode
                        key={goal.source_id}
                        goal={goal}
                        onPromote={handlePromote}
                        onOpen={openSource}
                        disabled={acting}
                        slotsFull={slots.length >= 3}
                        focusedIds={focusedIds}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Flat groups: Reminders, Nags, Auto Issues */}
              {FLAT_BACKLOG_GROUPS.map(({ key, label, icon: Icon }) => {
                const items = backlog[key];
                if (!items || items.length === 0) return null;
                return (
                  <div key={key}>
                    <div className="flex items-center gap-1.5 mb-1 px-1">
                      <Icon size={12} className="text-slate-500" />
                      <span className="text-xs font-medium text-slate-400">{label}</span>
                      <span className="text-[10px] text-slate-600">({items.length})</span>
                    </div>
                    <div className="space-y-0.5">
                      {items.map(item => (
                        <BacklogItem
                          key={item.source_id}
                          item={item}
                          onPromote={() => handlePromote(item.source_type, item.source_id)}
                          onOpen={() => openSource(item.source_type, item.source_id, item)}
                          disabled={acting || item.in_focus}
                          slotsFull={slots.length >= 3}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}


function FamilyView({ data, loading, onOpenApp }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-400">
        <Loader2 size={18} className="animate-spin mr-2" /> Loading family...
      </div>
    );
  }

  function openSource(source_type, source_id, item) {
    if (source_type === "goal") onOpenApp?.("goals", { goalId: source_id });
    else if (source_type === "project") onOpenApp?.("goals", { projectId: source_id });
    else if (source_type === "task") onOpenApp?.("goals", { taskId: source_id });
    else if (source_type === "nag") onOpenApp?.("reminders", { tab: "nags" });
    else if (source_type === "reminder") onOpenApp?.("reminders", { tab: "reminders" });
    else if (source_type === "auto_issue") {
      const vid = item?.vehicle_id || "";
      if (vid) onOpenApp?.("auto-vehicle", { autoVehicleId: vid });
      else onOpenApp?.("auto");
    } else if (source_type === "schedule") {
      onOpenApp?.("schedules", { scheduleId: source_id });
    }
  }

  return (
    <div className="p-3 space-y-4">
      {data.map(member => (
        <div key={member.user_id}>
          <div className="flex items-center gap-2 mb-1.5">
            <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-[10px] font-bold text-white uppercase">
              {member.display_name?.[0] || "?"}
            </div>
            <span className="text-sm font-medium text-white">{member.display_name}</span>
            <span className="text-[10px] text-slate-500">{member.slots.length}/3</span>
            {member.focus_nag_enabled ? (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-900/30 text-violet-400">nag on</span>
            ) : (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-600">nag off</span>
            )}
          </div>
          {member.slots.length === 0 ? (
            <div className="text-xs text-slate-600 italic ml-8 mb-2">No focus items set</div>
          ) : (
            <div className="space-y-1 ml-2 mb-2">
              {member.slots.map((slot, idx) => {
                const item = slot.item || {};
                const Icon = SOURCE_ICONS[slot.source_type] || Target;
                const color = SOURCE_COLORS[slot.source_type] || "text-slate-400";
                const label = SOURCE_LABELS[slot.source_type] || slot.source_type;
                return (
                  <div
                    key={slot.id}
                    className="flex items-center gap-2 bg-slate-800/40 rounded-lg px-2.5 py-1.5 cursor-pointer hover:bg-slate-800/60 transition-colors"
                    onClick={() => openSource(slot.source_type, slot.source_id, item)}
                  >
                    <span className="text-sm font-bold text-amber-500/50 w-4 text-center shrink-0">
                      {idx + 1}
                    </span>
                    <Icon size={11} className={color} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-300 truncate">{item.title || slot.source_id}</div>
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] shrink-0">
                      <span className={color}>{label}</span>
                      {item.detail && <span className="text-slate-500">{item.detail}</span>}
                      {item.priority && (
                        <span className={PRIORITY_COLORS[item.priority] || "text-slate-500"}>
                          {item.priority}
                        </span>
                      )}
                      {item.severity && (
                        <span className={`px-1 py-0 rounded text-white ${SEVERITY_COLORS[item.severity] || ""}`}>
                          {item.severity}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}


function GoalsTreeNode({ goal, onPromote, onOpen, disabled, slotsFull, focusedIds }) {
  const projects = goal.projects || [];
  return (
    <div>
      {/* Goal level — indent 0 */}
      <BacklogItem
        item={{ ...goal, in_focus: focusedIds.has(goal.source_id) }}
        onPromote={() => onPromote(goal.source_type, goal.source_id)}
        onOpen={() => onOpen(goal.source_type, goal.source_id, goal)}
        disabled={disabled || focusedIds.has(goal.source_id)}
        slotsFull={slotsFull}
        indent={0}
      />
      {projects.map(proj => (
        <div key={proj.source_id}>
          {/* Project level — indent 1 */}
          <BacklogItem
            item={{ ...proj, in_focus: focusedIds.has(proj.source_id) }}
            onPromote={() => onPromote(proj.source_type, proj.source_id)}
            onOpen={() => onOpen(proj.source_type, proj.source_id, proj)}
            disabled={disabled || focusedIds.has(proj.source_id)}
            slotsFull={slotsFull}
            indent={1}
          />
          {(proj.tasks || []).map(task => (
            /* Task level — indent 2 */
            <BacklogItem
              key={task.source_id}
              item={{ ...task, in_focus: focusedIds.has(task.source_id) }}
              onPromote={() => onPromote(task.source_type, task.source_id)}
              onOpen={() => onOpen(task.source_type, task.source_id, task)}
              disabled={disabled || focusedIds.has(task.source_id)}
              slotsFull={slotsFull}
              indent={2}
            />
          ))}
        </div>
      ))}
    </div>
  );
}


function FocusCard({ slot, index, total, onClear, onMoveUp, onMoveDown, onMoveToTop, onMoveToBottom, onOpen, disabled }) {
  const item = slot.item || {};
  const Icon = SOURCE_ICONS[slot.source_type] || Target;
  const color = SOURCE_COLORS[slot.source_type] || "text-slate-400";
  const label = SOURCE_LABELS[slot.source_type] || slot.source_type;

  return (
    <div className="flex items-center gap-2 bg-slate-800/60 border border-amber-900/30 rounded-lg px-2.5 py-2 group">
      {/* Reorder arrows */}
      <div className="flex flex-col shrink-0">
        <button
          onClick={onMoveToTop}
          disabled={disabled || index === 0}
          className="p-0 text-slate-600 hover:text-amber-400 disabled:opacity-20 disabled:cursor-default transition-colors"
          title="Move to top"
        >
          <ChevronsUp size={11} />
        </button>
        <button
          onClick={onMoveUp}
          disabled={disabled || index === 0}
          className="p-0 text-slate-600 hover:text-amber-400 disabled:opacity-20 disabled:cursor-default transition-colors"
          title="Move up"
        >
          <ChevronUp size={11} />
        </button>
        <button
          onClick={onMoveDown}
          disabled={disabled || index === total - 1}
          className="p-0 text-slate-600 hover:text-amber-400 disabled:opacity-20 disabled:cursor-default transition-colors"
          title="Move down"
        >
          <ChevronDown size={11} />
        </button>
        <button
          onClick={onMoveToBottom}
          disabled={disabled || index === total - 1}
          className="p-0 text-slate-600 hover:text-amber-400 disabled:opacity-20 disabled:cursor-default transition-colors"
          title="Move to bottom"
        >
          <ChevronsDown size={11} />
        </button>
      </div>

      {/* Slot number */}
      <span className="text-lg font-bold text-amber-500/60 w-6 text-center shrink-0">
        {index + 1}
      </span>

      {/* Content */}
      <div
        className="flex-1 min-w-0 cursor-pointer"
        onClick={onOpen}
      >
        <div className="text-sm font-medium text-white truncate hover:text-amber-300 transition-colors">
          {item.title || slot.source_id}
        </div>
        <div className="flex items-center gap-2 mt-0.5 text-xs">
          <span className={`flex items-center gap-0.5 ${color}`}>
            <Icon size={10} /> {label}
          </span>
          {item.detail && <span className="text-slate-500">{item.detail}</span>}
          {item.priority && (
            <span className={PRIORITY_COLORS[item.priority] || "text-slate-400"}>
              {item.priority}
            </span>
          )}
          {item.severity && (
            <span className={`px-1 py-0 rounded text-[10px] text-white ${SEVERITY_COLORS[item.severity] || ""}`}>
              {item.severity}
            </span>
          )}
          {item.due_date && <span className="text-slate-500">due {item.due_date}</span>}
        </div>
      </div>

      {/* Clear button */}
      <button
        onClick={onClear}
        disabled={disabled}
        className="shrink-0 p-1 text-slate-600 hover:text-red-400 transition-colors disabled:opacity-30"
        title="Remove from focus"
      >
        <X size={14} />
      </button>
    </div>
  );
}


function BacklogItem({ item, onPromote, onOpen, disabled, slotsFull, indent = 0 }) {
  const color = SOURCE_COLORS[item.source_type] || "text-slate-400";
  const Icon = SOURCE_ICONS[item.source_type] || Target;
  const indentPx = indent * 20;

  return (
    <div
      className={`flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-800/40 transition-colors group ${
        item.in_focus ? "opacity-40" : ""
      }`}
      style={{ paddingLeft: `${8 + indentPx}px` }}
    >
      {/* Promote button */}
      <button
        onClick={onPromote}
        disabled={disabled || (slotsFull && !item.in_focus)}
        className="shrink-0 p-0.5 text-slate-600 hover:text-amber-400 disabled:opacity-20 disabled:cursor-default transition-colors"
        title={item.in_focus ? "Already in focus" : slotsFull ? "All focus slots full" : "Promote to focus"}
      >
        <ArrowUpFromLine size={12} />
      </button>

      {/* Content */}
      <Icon size={11} className={`shrink-0 ${color}`} />
      <div className="flex-1 min-w-0 cursor-pointer" onClick={onOpen}>
        <span className="text-sm text-slate-300 hover:text-white transition-colors truncate block">
          {item.title}
        </span>
      </div>

      {/* Metadata */}
      <div className="flex items-center gap-1.5 shrink-0 text-[10px]">
        {item.priority && (
          <span className={PRIORITY_COLORS[item.priority] || "text-slate-500"}>
            {item.priority}
          </span>
        )}
        {item.severity && (
          <span className={`px-1 py-0 rounded text-white ${SEVERITY_COLORS[item.severity] || ""}`}>
            {item.severity}
          </span>
        )}
        {item.due_date && <span className="text-slate-500">{item.due_date}</span>}
        {item.detail && !item.due_date && (
          <span className={`${color} truncate max-w-[120px]`}>{item.detail}</span>
        )}
        {item.in_focus && (
          <span className="px-1 py-0 bg-amber-900/30 text-amber-400 rounded text-[9px]">focused</span>
        )}
      </div>
    </div>
  );
}
