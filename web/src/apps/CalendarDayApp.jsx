import React, { useState, useEffect } from "react";
import {
  CalendarDays, Clock, CheckCircle2, Loader2, AlertTriangle,
  CalendarClock, Bell, BellRing, CheckSquare, Car, Target, FolderKanban, ListTodo,
} from "lucide-react";

const API_BASE = "";

// Schedule category colors
const SCHEDULE_CATEGORY_COLORS = {
  chore: "bg-amber-600",
  maintenance: "bg-sky-600",
  school: "bg-indigo-600",
  auto: "bg-cyan-600",
  medical: "bg-rose-600",
  general: "bg-slate-600",
};

const SCHEDULE_CATEGORY_LABELS = {
  chore: "Chore",
  maintenance: "Maintenance",
  school: "School",
  auto: "Auto",
  medical: "Medical",
  general: "General",
};

const SOURCE_TYPE_COLORS = {
  schedule: "bg-slate-600",
  goal: "bg-amber-600",
  project: "bg-blue-600",
  reminder: "bg-violet-600",
  task: "bg-emerald-600",
  auto_service: "bg-orange-600",
  nag: "bg-pink-600",
  todo: "bg-amber-600",
};

const SOURCE_TYPE_LABELS = {
  schedule: "Schedule",
  goal: "Goal",
  project: "Project",
  reminder: "Reminder",
  task: "Task",
  auto_service: "Auto Service",
  nag: "Nag",
  todo: "To-Do",
};

const SOURCE_TYPE_ICONS = {
  schedule: CalendarClock,
  goal: Target,
  project: FolderKanban,
  reminder: Bell,
  task: CheckSquare,
  auto_service: Car,
  nag: BellRing,
  todo: ListTodo,
};

function getBadgeColor(ev) {
  if (ev.source_type === "schedule") {
    return SCHEDULE_CATEGORY_COLORS[ev.category] || SCHEDULE_CATEGORY_COLORS.general;
  }
  return SOURCE_TYPE_COLORS[ev.source_type] || SOURCE_TYPE_COLORS.schedule;
}

function getBadgeLabel(ev) {
  if (ev.source_type === "schedule") {
    return SCHEDULE_CATEGORY_LABELS[ev.category] || ev.category;
  }
  return SOURCE_TYPE_LABELS[ev.source_type] || ev.source_type;
}

export default function CalendarDayApp({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const dateStr = context.date || new Date().toISOString().slice(0, 10);
  const [events, setEvents] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const d = new Date(dateStr + "T12:00:00");
    const title = d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    onTitle?.(title);
  }, [dateStr]);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ from_date: dateStr, to_date: dateStr });
        if (userId) params.set("assigned_to", userId);
        const res = await fetch(`${API_BASE}/api/apps/calendar/events?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setEvents(data.events || []);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [dateStr, userId]);

  if (loading && !events) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={20} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }

  const d = new Date(dateStr + "T12:00:00");
  const dayLabel = d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });

  return (
    <div className="h-full w-full flex flex-col text-slate-200">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700/50 shrink-0">
        <div className="flex items-center gap-2">
          <CalendarDays size={18} className="text-cyan-400" />
          <h2 className="text-sm font-semibold">{dayLabel}</h2>
        </div>
      </div>

      {error && (
        <div className="px-4 py-1.5 bg-red-900/30 border-b border-red-700/40 text-red-300 text-xs">
          {error}
        </div>
      )}

      {/* Events list */}
      <div className="flex-1 overflow-y-auto p-4">
        {events && events.length === 0 && (
          <div className="text-center text-slate-500 py-12 text-sm">
            Nothing scheduled for this day.
          </div>
        )}

        {events && events.length > 0 && (
          <div className="space-y-2">
            {events.map((ev, i) => {
              const Icon = SOURCE_TYPE_ICONS[ev.source_type] || CalendarClock;
              return (
                <button
                  key={i}
                  onClick={() => {
                    if (ev.source_type === "schedule") onOpenApp?.("schedules", { scheduleId: ev.source_id });
                    else if (ev.source_type === "goal") onOpenApp?.("goals", { goalId: ev.source_id });
                    else if (ev.source_type === "project") onOpenApp?.("goals", { projectId: ev.source_id });
                    else if (ev.source_type === "reminder") onOpenApp?.("reminders", { tab: "reminders" });
                    else if (ev.source_type === "nag") onOpenApp?.("reminders", { tab: "nags" });
                    else if (ev.source_type === "task") onOpenApp?.("goals", { taskId: ev.source_id });
                    else if (ev.source_type === "auto_service") onOpenApp?.("auto");
                    else if (ev.source_type === "todo") onOpenApp?.("todo");
                  }}
                  className="w-full text-left flex items-start gap-3 px-4 py-3 rounded-lg bg-slate-800/60 border border-slate-700/50 hover:bg-slate-800 hover:border-slate-600 transition-colors group"
                >
                  <div className="shrink-0 mt-0.5">
                    {ev.overdue ? (
                      <AlertTriangle size={16} className="text-red-400" />
                    ) : (
                      <Icon size={16} className="text-slate-500 group-hover:text-slate-300" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-slate-200 font-medium">{ev.title}</div>
                    <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
                      <span className={`px-1.5 py-0 rounded text-[10px] ${getBadgeColor(ev)} text-white`}>
                        {getBadgeLabel(ev)}
                      </span>
                      {ev.source_type !== "schedule" && (
                        <span className="text-slate-600 text-[10px]">{SOURCE_TYPE_LABELS[ev.source_type]}</span>
                      )}
                      {ev.time_of_day && (
                        <span className="flex items-center gap-0.5">
                          <Clock size={10} />
                          {ev.time_of_day}
                        </span>
                      )}
                      {ev.assigned_to && <span>{ev.assigned_to}</span>}
                      {ev.overdue && <span className="text-red-400 font-medium">Overdue</span>}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
