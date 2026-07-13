import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Plus, RefreshCw, ChevronRight, ArrowLeft, Save, CheckCircle2, X,
  Loader2, CalendarClock, Pause, Play, Trash2, Clock, AlertTriangle,
  Bot, FileText,
} from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

const API_BASE = "";

const CATEGORY_COLORS = {
  chore: "bg-amber-600",
  maintenance: "bg-[var(--ds-accent)]",
  school: "bg-indigo-600",
  auto: "bg-[var(--ds-accent)]",
  medical: "bg-rose-600",
  general: "surface-raised",
};

const CATEGORY_LABELS = {
  chore: "Chore",
  maintenance: "Maintenance",
  school: "School",
  auto: "Auto",
  medical: "Medical",
  general: "General",
};

const ALL_CATEGORIES = ["chore", "maintenance", "school", "auto", "medical", "general"];

const RECURRENCE_TYPES = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "yearly", label: "Yearly" },
  { value: "interval", label: "Every N days" },
];

const WEEKDAYS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
];

export default function SchedulesApp({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const [view, setView] = useState("list");
  const [schedules, setSchedules] = useState(null);
  const [detail, setDetail] = useState(null);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [users, setUsers] = useState([]);

  async function apiFetch(url) {
    const res = await fetch(`${API_BASE}${url}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function apiMutate(url, method, body) {
    const res = await fetch(`${API_BASE}${url}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  useEffect(() => {
    fetch("/api/users").then(r => r.json()).then(setUsers).catch(() => {});
  }, []);

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let url = "/api/apps/schedules";
      const params = [];
      if (filter !== "all" && filter !== "overdue") params.push(`category=${filter}`);
      if (userId) params.push(`assigned_to=${encodeURIComponent(userId)}`);
      if (params.length) url += "?" + params.join("&");
      const data = await apiFetch(url);
      setSchedules(data.schedules || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [filter, userId]);

  useEffect(() => { loadSchedules(); }, [loadSchedules]);

  async function loadDetail(id) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/schedules/${id}`);
      if (data.error) { setError(data.error); return; }
      setDetail(data);
      setView("detail");
      onTitle?.(data.title || "Schedule");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function goList() {
    setView("list");
    setDetail(null);
    onTitle?.("Schedules");
    loadSchedules();
  }

  if (loading && !schedules && !detail) {
    return (
      <div className="flex items-center justify-center h-full text-muted">
        <Loader2 size={20} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col text-default">
      {error && (
        <div className="px-4 py-2 bg-red-900/40 border-b border-red-700/40 text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-2 hover:text-[var(--ds-text)]"><X size={14} /></button>
        </div>
      )}

      {view === "list" && (
        <ListView
          schedules={schedules || []}
          filter={filter}
          setFilter={setFilter}
          onScheduleClick={loadDetail}
          onNewClick={() => setView("new")}
          onRefresh={loadSchedules}
          loading={loading}
          userId={userId}
          apiMutate={apiMutate}
          setError={setError}
          onComplete={() => loadSchedules()}
        />
      )}

      {view === "new" && (
        <NewScheduleForm
          userId={userId}
          users={users}
          apiMutate={apiMutate}
          onCreated={(sch) => loadDetail(sch.id)}
          onCancel={goList}
          setError={setError}
        />
      )}

      {view === "detail" && detail && (
        <DetailView
          schedule={detail}
          userId={userId}
          users={users}
          apiMutate={apiMutate}
          onBack={goList}
          onRefresh={() => loadDetail(detail.id)}
          setError={setError}
          onOpenApp={onOpenApp}
        />
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  List View                                                                */
/* ═══════════════════════════════════════════════════════════════════════════ */

function isOverdue(schedule) {
  if (!schedule.next_due) return false;
  return new Date(schedule.next_due) < new Date();
}

function isDueSoon(schedule) {
  if (!schedule.next_due) return false;
  const due = new Date(schedule.next_due);
  const now = new Date();
  const diff = (due - now) / (1000 * 60 * 60 * 24);
  return diff >= 0 && diff <= 2;
}

function formatDue(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  const now = new Date();
  const diff = Math.floor((d - now) / (1000 * 60 * 60 * 24));
  if (diff < -1) return `${Math.abs(diff)} days overdue`;
  if (diff === -1) return "Yesterday";
  if (diff === 0) {
    const hours = Math.floor((d - now) / (1000 * 60 * 60));
    if (hours < 0) return "Overdue today";
    if (hours === 0) return "Due now";
    return `${hours}h`;
  }
  if (diff === 1) return "Tomorrow";
  if (diff <= 7) return `${diff} days`;
  return d.toLocaleDateString();
}

function ListView({ schedules, filter, setFilter, onScheduleClick, onNewClick, onRefresh, loading, userId, apiMutate, setError, onComplete }) {
  async function quickComplete(scheduleId) {
    try {
      await apiMutate(`/api/apps/schedules/${scheduleId}/complete`, "POST", {
        completed_by: userId,
      });
      onComplete();
    } catch (e) {
      setError?.(e.message);
    }
  }

  const overdue = schedules.filter(isOverdue);
  const dueSoon = schedules.filter(s => isDueSoon(s) && !isOverdue(s));
  const filtered = filter === "overdue"
    ? overdue
    : filter === "all"
      ? schedules
      : schedules.filter(s => s.category === filter);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-subtle">
        <button
          onClick={onNewClick}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--ds-accent)] hover:bg-[var(--ds-accent)] text-on-accent text-sm font-medium transition-colors"
        >
          <Plus size={14} /> New Schedule
        </button>
        <div className="flex-1" />
        <div className="flex items-center gap-1 flex-wrap">
          {[
            { key: "all", label: "All" },
            ...(overdue.length > 0 ? [{ key: "overdue", label: `Overdue (${overdue.length})` }] : []),
            ...ALL_CATEGORIES.map(c => ({ key: c, label: CATEGORY_LABELS[c] })),
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`text-[11px] px-2 py-0.5 rounded-full transition-colors ${
                filter === tab.key
                  ? tab.key === "overdue" ? "bg-red-600 text-on-accent" : "bg-[var(--ds-accent)] text-on-accent"
                  : "surface-card text-muted hover:text-[var(--ds-text)]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <button onClick={onRefresh} className="p-1 rounded hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] transition-colors" title="Refresh">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Overdue banner */}
      {overdue.length > 0 && filter !== "overdue" && (
        <button
          onClick={() => setFilter("overdue")}
          className="px-4 py-2 bg-red-900/30 border-b border-red-700/40 text-red-300 text-xs flex items-center gap-2 hover:bg-red-900/40 transition-colors"
        >
          <AlertTriangle size={14} />
          <span>{overdue.length} overdue schedule{overdue.length > 1 ? "s" : ""}</span>
        </button>
      )}

      {/* Schedule list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <PristineEmpty
            appId="schedules"
            blurb={getAppManifest("schedules")?.blurb}
            records={schedules}
            loading={loading}
            filterActive={filter !== "all"}
            fallback={
              <div className="text-center text-faint py-12 text-sm">
                No schedules in this category.
              </div>
            }
          />
        ) : (
          filtered.map((sch) => {
            const overdueFl = isOverdue(sch);
            const dueSoonFl = isDueSoon(sch) && !overdueFl;
            return (
              <div
                key={sch.id}
                className={`flex items-center border-b border-subtle hover:bg-[var(--ds-card)] transition-colors ${
                  overdueFl ? "bg-red-900/10" : ""
                }`}
              >
                <button
                  onClick={() => onScheduleClick(sch.id)}
                  className="flex-1 text-left px-4 py-3 flex items-start gap-3 min-w-0"
                >
                  <CalendarClock size={18} className={`shrink-0 mt-0.5 ${overdueFl ? "text-red-400" : dueSoonFl ? "text-amber-400" : "text-faint"}`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-default line-clamp-1">{sch.title}</div>
                    <div className="text-xs text-faint mt-0.5 flex items-center gap-2">
                      <span className={`px-1.5 py-0 rounded text-[10px] ${CATEGORY_COLORS[sch.category] || "surface-raised"} text-default`}>
                        {CATEGORY_LABELS[sch.category] || sch.category}
                      </span>
                      {sch.linked_entity_type === "job" && sch.linked_entity_id === "agentic" && (
                        <span className="inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[10px] bg-[var(--ds-accent)]/15 text-[var(--ds-accent)]">
                          <Bot size={9} /> auto
                        </span>
                      )}
                      {sch.assigned_to && <span>{sch.assigned_to}</span>}
                      <span>&middot;</span>
                      <span className={overdueFl ? "text-red-400 font-medium" : dueSoonFl ? "text-amber-400" : ""}>
                        {formatDue(sch.next_due)}
                      </span>
                    </div>
                  </div>
                </button>
                <button
                  onClick={() => quickComplete(sch.id)}
                  className="shrink-0 mr-3 p-1.5 rounded-lg hover:bg-emerald-600/20 text-faint hover:text-emerald-400 transition-colors"
                  title="Mark Done"
                >
                  <CheckCircle2 size={18} />
                </button>
                <ChevronRight size={14} className="text-faint shrink-0 mr-3" />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  New Schedule Form                                                        */
/* ═══════════════════════════════════════════════════════════════════════════ */

function NewScheduleForm({ userId, users, apiMutate, onCreated, onCancel, setError }) {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("general");
  const [assignedTo, setAssignedTo] = useState(userId);
  const [recurrenceType, setRecurrenceType] = useState("weekly");
  const [weekDays, setWeekDays] = useState(["sat"]);
  const [monthDay, setMonthDay] = useState(1);
  const [intervalDays, setIntervalDays] = useState(30);
  const [dailyEvery, setDailyEvery] = useState(1);
  const [yearlyMonth, setYearlyMonth] = useState(new Date().getMonth() + 1);
  const [yearlyDay, setYearlyDay] = useState(1);
  const [timeOfDay, setTimeOfDay] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  function buildRule() {
    switch (recurrenceType) {
      case "daily": return { every: dailyEvery };
      case "weekly": return { days: weekDays };
      case "monthly": return { day: monthDay };
      case "yearly": return { month: yearlyMonth, day: yearlyDay };
      case "interval": return { days: intervalDays };
      default: return {};
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      const data = await apiMutate("/api/apps/schedules", "POST", {
        title: title.trim(),
        created_by: userId,
        category,
        assigned_to: assignedTo,
        description: description.trim(),
        recurrence_type: recurrenceType,
        recurrence_rule: buildRule(),
        time_of_day: timeOfDay || null,
      });
      if (data.error) { setError(data.error); return; }
      onCreated(data.schedule);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-subtle">
        <button onClick={onCancel} className="p-1 rounded hover:bg-[var(--ds-raised)] text-muted"><ArrowLeft size={16} /></button>
        <h2 className="text-sm font-semibold text-default">New Schedule</h2>
      </div>
      <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Title */}
        <div>
          <label className="block text-xs text-muted mb-1">Title</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Mow the lawn, Change HVAC filter..."
            className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default placeholder-slate-500"
            autoFocus
          />
        </div>

        {/* Category + Assigned to */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted mb-1">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default">
              {ALL_CATEGORIES.map(c => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Assigned to</label>
            <select value={assignedTo} onChange={(e) => setAssignedTo(e.target.value)}
              className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default">
              {users.map(u => <option key={u.name} value={u.name}>{u.display_name || u.name}</option>)}
            </select>
          </div>
        </div>

        {/* Recurrence */}
        <div>
          <label className="block text-xs text-muted mb-1">Repeats</label>
          <select value={recurrenceType} onChange={(e) => setRecurrenceType(e.target.value)}
            className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default mb-2">
            {RECURRENCE_TYPES.map(rt => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
          </select>

          {/* Type-specific rule builder */}
          {recurrenceType === "daily" && (
            <div className="flex items-center gap-2 text-sm text-default">
              <span>Every</span>
              <input type="number" min={1} max={365} value={dailyEvery} onChange={(e) => setDailyEvery(Number(e.target.value))}
                className="w-16 surface-card border border-subtle rounded px-2 py-1 text-sm text-default" />
              <span>day{dailyEvery > 1 ? "s" : ""}</span>
            </div>
          )}

          {recurrenceType === "weekly" && (
            <div className="flex gap-1 flex-wrap">
              {WEEKDAYS.map(wd => (
                <button
                  key={wd.key}
                  type="button"
                  onClick={() => setWeekDays(prev =>
                    prev.includes(wd.key) ? prev.filter(d => d !== wd.key) : [...prev, wd.key]
                  )}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    weekDays.includes(wd.key)
                      ? "bg-[var(--ds-accent)] text-on-accent"
                      : "surface-card text-muted hover:text-[var(--ds-text)] border border-subtle"
                  }`}
                >
                  {wd.label}
                </button>
              ))}
            </div>
          )}

          {recurrenceType === "monthly" && (
            <div className="flex items-center gap-2 text-sm text-default">
              <span>Day</span>
              <input type="number" min={1} max={31} value={monthDay} onChange={(e) => setMonthDay(Number(e.target.value))}
                className="w-16 surface-card border border-subtle rounded px-2 py-1 text-sm text-default" />
              <span>of every month</span>
            </div>
          )}

          {recurrenceType === "yearly" && (
            <div className="flex items-center gap-2 text-sm text-default">
              <span>Every</span>
              <select value={yearlyMonth} onChange={(e) => setYearlyMonth(Number(e.target.value))}
                className="surface-card border border-subtle rounded px-2 py-1 text-sm text-default">
                {["January","February","March","April","May","June","July","August","September","October","November","December"].map((m, i) => (
                  <option key={i+1} value={i+1}>{m}</option>
                ))}
              </select>
              <input type="number" min={1} max={31} value={yearlyDay} onChange={(e) => setYearlyDay(Number(e.target.value))}
                className="w-16 surface-card border border-subtle rounded px-2 py-1 text-sm text-default" />
            </div>
          )}

          {recurrenceType === "interval" && (
            <div className="flex items-center gap-2 text-sm text-default">
              <span>Every</span>
              <input type="number" min={1} max={999} value={intervalDays} onChange={(e) => setIntervalDays(Number(e.target.value))}
                className="w-20 surface-card border border-subtle rounded px-2 py-1 text-sm text-default" />
              <span>days from last completion</span>
            </div>
          )}
        </div>

        {/* Time of day */}
        <div>
          <label className="block text-xs text-muted mb-1">Time of day (optional)</label>
          <input
            type="time"
            value={timeOfDay}
            onChange={(e) => setTimeOfDay(e.target.value)}
            className="surface-card border border-subtle rounded px-3 py-2 text-sm text-default"
          />
        </div>

        {/* Description */}
        <div>
          <label className="block text-xs text-muted mb-1">Description (optional)</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default placeholder-slate-500 resize-none"
            placeholder="Additional details..."
          />
        </div>

        {/* Submit */}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={!title.trim() || saving}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--ds-accent)] hover:bg-[var(--ds-accent)] disabled:opacity-50 text-on-accent text-sm font-medium transition-colors"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Create Schedule
          </button>
          <button type="button" onClick={onCancel} className="px-4 py-2 rounded-lg surface-raised hover:bg-[var(--ds-raised)] text-default text-sm transition-colors">
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  Detail View                                                              */
/* ═══════════════════════════════════════════════════════════════════════════ */

function DetailView({ schedule, userId, users, apiMutate, onBack, onRefresh, setError, onOpenApp }) {
  const [title, setTitle] = useState(schedule.title);
  const [description, setDescription] = useState(schedule.description || "");
  const [category, setCategory] = useState(schedule.category);
  const [assignedTo, setAssignedTo] = useState(schedule.assigned_to || "");
  const [active, setActive] = useState(schedule.active);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [completing, setCompleting] = useState(false);

  useEffect(() => {
    setTitle(schedule.title);
    setDescription(schedule.description || "");
    setCategory(schedule.category);
    setAssignedTo(schedule.assigned_to || "");
    setActive(schedule.active);
    setDirty(false);
  }, [schedule]);

  async function handleSave() {
    setSaving(true);
    try {
      const body = {};
      if (title !== schedule.title) body.title = title;
      if (description !== (schedule.description || "")) body.description = description;
      if (category !== schedule.category) body.category = category;
      if (assignedTo !== (schedule.assigned_to || "")) body.assigned_to = assignedTo;
      if (active !== schedule.active) body.active = active;

      if (Object.keys(body).length === 0) { setDirty(false); setSaving(false); return; }

      const data = await apiMutate(`/api/apps/schedules/${schedule.id}`, "PATCH", body);
      if (data.error) { setError(data.error); return; }
      setDirty(false);
      onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleComplete() {
    setCompleting(true);
    try {
      const data = await apiMutate(`/api/apps/schedules/${schedule.id}/complete`, "POST", {
        completed_by: userId,
      });
      if (data.error) { setError(data.error); return; }
      onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setCompleting(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${schedule.title}"?`)) return;
    try {
      await apiMutate(`/api/apps/schedules/${schedule.id}`, "DELETE", {});
      onBack();
    } catch (e) {
      setError(e.message);
    }
  }

  const overdueFl = isOverdue(schedule);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-subtle">
        <button onClick={onBack} className="p-1 rounded hover:bg-[var(--ds-raised)] text-muted"><ArrowLeft size={16} /></button>
        <div className="flex-1" />
        {dirty && (
          <button onClick={handleSave} disabled={saving}
            className="flex items-center gap-1 px-3 py-1 rounded-lg bg-[var(--ds-accent)] hover:bg-[var(--ds-accent)] disabled:opacity-50 text-on-accent text-xs font-medium">
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save
          </button>
        )}
        <button onClick={handleComplete} disabled={completing}
          className="flex items-center gap-1 px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-on-accent text-xs font-medium">
          {completing ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />} Mark Done
        </button>
        <button onClick={() => { setActive(!active); setDirty(true); }}
          className={`flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-medium ${
            active ? "surface-raised hover:bg-[var(--ds-raised)] text-default" : "bg-amber-700 hover:bg-amber-600 text-on-accent"
          }`}>
          {active ? <><Pause size={12} /> Pause</> : <><Play size={12} /> Resume</>}
        </button>
        <button onClick={handleDelete}
          className="p-1 rounded hover:bg-red-900/40 text-faint hover:text-red-400">
          <Trash2 size={14} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Header */}
        <div>
          <input
            value={title}
            onChange={(e) => { setTitle(e.target.value); setDirty(true); }}
            className="w-full bg-transparent text-lg font-semibold text-default border-b border-transparent hover:border-[var(--ds-border)] focus:border-subtle focus:outline-none pb-1 transition-colors"
          />
          <div className="flex items-center gap-3 mt-2 text-xs text-faint">
            <span className={`px-1.5 py-0.5 rounded text-[10px] ${CATEGORY_COLORS[category]} text-default`}>
              {CATEGORY_LABELS[category]}
            </span>
            {!active && <span className="px-1.5 py-0.5 rounded bg-amber-700/40 text-amber-300 text-[10px]">Paused</span>}
            <span>Assigned to {assignedTo}</span>
            <span>&middot;</span>
            <span>{schedule.recurrence_summary || ""}</span>
          </div>
        </div>

        {/* Autonomous (agentic) task — surface its prompt + a jump to the editor */}
        {schedule.linked_entity_type === "job" && schedule.linked_entity_id === "agentic" && (() => {
          const jc = schedule.job_config || {};
          const cats = jc.tool_categories || [];
          return (
            <div className="rounded-lg border border-[var(--ds-accent)]/40 bg-[var(--ds-accent)]/5 p-3 space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-default">
                <Bot size={15} className="text-[var(--ds-accent)]" /> Autonomous task
              </div>
              <div className="text-xs text-faint">
                Skipper runs a saved prompt on this schedule.{" "}
                {jc.needs_attention
                  ? "The result is shared with the family each run."
                  : "It runs silently in the background."}
              </div>
              <div className="text-xs text-muted">
                Starting tools: {cats.length ? cats.join(", ") : "core only (requests more as needed)"}
              </div>
              {jc.prompt_doc_id && (
                <button
                  onClick={() => onOpenApp?.("document", { docId: jc.prompt_doc_id, title: schedule.title })}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--ds-accent)] hover:opacity-90 text-on-accent text-xs font-medium transition-opacity"
                >
                  <FileText size={13} /> View / edit prompt
                </button>
              )}
            </div>
          );
        })()}

        {/* Due status */}
        <div className={`rounded-lg border p-3 ${
          overdueFl ? "bg-red-900/20 border-red-700/40" : "surface-card border-subtle"
        }`}>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-muted">Next due</div>
              <div className={`text-sm font-medium ${overdueFl ? "text-red-400" : "text-default"}`}>
                {schedule.next_due ? new Date(schedule.next_due).toLocaleString() : "—"}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted">Completed</div>
              <div className="text-sm text-default">{schedule.completed_count} time{schedule.completed_count !== 1 ? "s" : ""}</div>
            </div>
            {schedule.last_completed && (
              <div className="text-right">
                <div className="text-xs text-muted">Last done</div>
                <div className="text-sm text-default">{new Date(schedule.last_completed).toLocaleDateString()}</div>
              </div>
            )}
          </div>
        </div>

        {/* Editable fields */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted mb-1">Category</label>
            <select value={category} onChange={(e) => { setCategory(e.target.value); setDirty(true); }}
              className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default">
              {ALL_CATEGORIES.map(c => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Assigned to</label>
            <select value={assignedTo} onChange={(e) => { setAssignedTo(e.target.value); setDirty(true); }}
              className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default">
              {users.map(u => <option key={u.name} value={u.name}>{u.display_name || u.name}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs text-muted mb-1">Description</label>
          <textarea
            value={description}
            onChange={(e) => { setDescription(e.target.value); setDirty(true); }}
            rows={3}
            className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default resize-none"
          />
        </div>

        {/* Completion history */}
        {schedule.completions && schedule.completions.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">Completion History</h3>
            <div className="space-y-1">
              {schedule.completions.map((c) => (
                <div key={c.id} className="flex items-center gap-3 text-xs text-muted py-1 border-b border-subtle">
                  <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />
                  <span className="text-default">{new Date(c.completed_at).toLocaleString()}</span>
                  {c.completed_by && <span>by {c.completed_by}</span>}
                  {c.notes && <span className="text-faint truncate">{c.notes}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Meta */}
        <div className="text-xs text-faint pt-2 border-t border-subtle">
          <span>ID: {schedule.id}</span>
          <span className="mx-2">&middot;</span>
          <span>Created by {schedule.created_by} on {new Date(schedule.created_at).toLocaleDateString()}</span>
        </div>
      </div>
    </div>
  );
}
