import React, { useState, useEffect, useCallback } from "react";
import {
  ChevronLeft, ChevronRight, RefreshCw, Loader2, CalendarDays, MoreHorizontal,
} from "lucide-react";

const API_BASE = "";

// Schedule category colors (used when source_type === "schedule")
const SCHEDULE_CATEGORY_COLORS = {
  chore: "bg-amber-600/70 border-amber-500/40",
  maintenance: "bg-sky-600/70 border-sky-500/40",
  school: "bg-indigo-600/70 border-indigo-500/40",
  auto: "bg-cyan-600/70 border-cyan-500/40",
  medical: "bg-rose-600/70 border-rose-500/40",
  general: "bg-slate-600/70 border-slate-500/40",
};

// Source-type colors for non-schedule events
const SOURCE_TYPE_COLORS = {
  schedule: "bg-slate-600/70 border-slate-500/40",
  goal: "bg-amber-600/70 border-amber-500/40",
  project: "bg-blue-600/70 border-blue-500/40",
  reminder: "bg-violet-600/70 border-violet-500/40",
  task: "bg-emerald-600/70 border-emerald-500/40",
  auto_service: "bg-orange-600/70 border-orange-500/40",
  nag: "bg-pink-600/70 border-pink-500/40",
  todo: "bg-amber-600/70 border-amber-500/40",
};

const SOURCE_TYPE_DOT = {
  schedule: "bg-slate-400",
  goal: "bg-amber-500",
  project: "bg-blue-500",
  reminder: "bg-violet-500",
  task: "bg-emerald-500",
  auto_service: "bg-orange-500",
  nag: "bg-pink-500",
  todo: "bg-amber-500",
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

// Schedule categories for legend (shown as sub-colors of schedules)
const SCHEDULE_CATEGORY_DOT = {
  chore: "bg-amber-500",
  maintenance: "bg-sky-500",
  school: "bg-indigo-500",
  auto: "bg-cyan-500",
  medical: "bg-rose-500",
};

function getEventColor(ev) {
  if (ev.source_type === "schedule") {
    return SCHEDULE_CATEGORY_COLORS[ev.category] || SCHEDULE_CATEGORY_COLORS.general;
  }
  return SOURCE_TYPE_COLORS[ev.source_type] || SOURCE_TYPE_COLORS.schedule;
}

const WEEKDAY_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function getMonthDays(year, month) {
  const first = new Date(year, month, 1);
  const startDay = first.getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevMonthDays = new Date(year, month, 0).getDate();

  const cells = [];
  // Previous month padding
  for (let i = startDay - 1; i >= 0; i--) {
    const d = prevMonthDays - i;
    const m = month === 0 ? 11 : month - 1;
    const y = month === 0 ? year - 1 : year;
    cells.push({ day: d, month: m, year: y, outside: true });
  }
  // Current month
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ day: d, month, year, outside: false });
  }
  // Next month padding to fill 6 rows (42 cells) or complete current row
  const rows = Math.ceil(cells.length / 7);
  const totalCells = rows * 7;
  let nextDay = 1;
  while (cells.length < totalCells) {
    const m = month === 11 ? 0 : month + 1;
    const y = month === 11 ? year + 1 : year;
    cells.push({ day: nextDay++, month: m, year: y, outside: true });
  }
  return cells;
}

function dateKey(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function isToday(year, month, day) {
  const now = new Date();
  return now.getFullYear() === year && now.getMonth() === month && now.getDate() === day;
}

export default function CalendarApp({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    onTitle?.(`${MONTH_NAMES[month]} ${year}`);
  }, [month, year]);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const first = dateKey(year, month, 1);
      const lastDay = new Date(year, month + 1, 0).getDate();
      const last = dateKey(year, month, lastDay);
      const params = new URLSearchParams({ from_date: first, to_date: last });
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
  }, [year, month, userId]);

  useEffect(() => { loadEvents(); }, [loadEvents]);

  function prevMonth() {
    if (month === 0) { setMonth(11); setYear(y => y - 1); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 11) { setMonth(0); setYear(y => y + 1); }
    else setMonth(m => m + 1);
  }
  function goToday() {
    setYear(now.getFullYear());
    setMonth(now.getMonth());
  }

  // Group events by date key
  const eventsByDate = {};
  events.forEach((ev) => {
    if (!eventsByDate[ev.date]) eventsByDate[ev.date] = [];
    eventsByDate[ev.date].push(ev);
  });

  const cells = getMonthDays(year, month);
  const rows = [];
  for (let i = 0; i < cells.length; i += 7) {
    rows.push(cells.slice(i, i + 7));
  }

  function openDay(year, month, day) {
    const dt = dateKey(year, month, day);
    const d = new Date(year, month, day);
    const title = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    onOpenApp?.("calendar-day", { date: dt, title: `📅 ${title}` });
  }

  function openEvent(ev) {
    if (ev.source_type === "schedule") onOpenApp?.("schedules", { scheduleId: ev.source_id });
    else if (ev.source_type === "goal") onOpenApp?.("goals", { goalId: ev.source_id });
    else if (ev.source_type === "project") onOpenApp?.("goals", { projectId: ev.source_id });
    else if (ev.source_type === "reminder" || ev.source_type === "nag") onOpenApp?.("reminders", { tab: ev.source_type === "nag" ? "nags" : "reminders" });
    else if (ev.source_type === "task") onOpenApp?.("goals", { taskId: ev.source_id });
    else if (ev.source_type === "auto_service") onOpenApp?.("auto");
    else if (ev.source_type === "todo") onOpenApp?.("todo");
  }

  return (
    <div className="h-full w-full flex flex-col text-slate-200">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-700/50 shrink-0">
        <button onClick={prevMonth} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors">
          <ChevronLeft size={16} />
        </button>
        <button onClick={goToday} className="px-2 py-0.5 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors">
          Today
        </button>
        <button onClick={nextMonth} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors">
          <ChevronRight size={16} />
        </button>
        <h2 className="text-sm font-semibold text-slate-200 ml-2">
          {MONTH_NAMES[month]} {year}
        </h2>
        <div className="flex-1" />
        {/* Source type legend */}
        <div className="hidden md:flex items-center gap-2 text-[10px] text-slate-400">
          {Object.entries(SOURCE_TYPE_DOT).map(([st, cls]) => (
            <span key={st} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${cls}`} />
              {SOURCE_TYPE_LABELS[st] || st}
            </span>
          ))}
        </div>
        <button onClick={loadEvents} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors" title="Refresh">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="px-4 py-1.5 bg-red-900/30 border-b border-red-700/40 text-red-300 text-xs">
          {error}
        </div>
      )}

      {/* Calendar grid */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Weekday headers */}
        <div className="grid grid-cols-7 border-b border-slate-700/50 shrink-0">
          {WEEKDAY_HEADERS.map((d) => (
            <div key={d} className="text-center text-[10px] font-medium text-slate-500 uppercase tracking-wider py-1.5">
              {d}
            </div>
          ))}
        </div>

        {/* Rows */}
        <div className="flex-1 grid" style={{ gridTemplateRows: `repeat(${rows.length}, 1fr)` }}>
          {rows.map((row, ri) => (
            <div key={ri} className="grid grid-cols-7 border-b border-slate-800/50">
              {row.map((cell, ci) => {
                const key = dateKey(cell.year, cell.month, cell.day);
                const dayEvents = eventsByDate[key] || [];
                const today = isToday(cell.year, cell.month, cell.day);
                const MAX_VISIBLE = 3;
                const visible = dayEvents.slice(0, MAX_VISIBLE);
                const overflow = dayEvents.length - MAX_VISIBLE;

                return (
                  <div
                    key={ci}
                    className={`border-r border-slate-800/40 last:border-r-0 flex flex-col min-h-0 overflow-hidden ${
                      cell.outside ? "bg-slate-900/30" : "bg-slate-900/60"
                    } ${today ? "ring-1 ring-inset ring-cyan-500/50" : ""}`}
                  >
                    {/* Day number */}
                    <div className="flex items-center justify-between px-1 pt-0.5 shrink-0">
                      <button
                        onClick={() => openDay(cell.year, cell.month, cell.day)}
                        className={`text-[11px] w-5 h-5 flex items-center justify-center rounded-full transition-colors ${
                          today
                            ? "bg-cyan-600 text-white font-bold"
                            : cell.outside
                              ? "text-slate-600 hover:text-slate-400"
                              : "text-slate-400 hover:text-white hover:bg-slate-700"
                        }`}
                        title="View day"
                      >
                        {cell.day}
                      </button>
                      {dayEvents.length > MAX_VISIBLE && (
                        <button
                          onClick={() => openDay(cell.year, cell.month, cell.day)}
                          className="text-[9px] text-slate-500 hover:text-slate-300 transition-colors"
                          title={`${dayEvents.length} events — click to see all`}
                        >
                          <MoreHorizontal size={12} />
                        </button>
                      )}
                    </div>

                    {/* Events */}
                    <div className="flex-1 flex flex-col gap-px px-0.5 pb-0.5 overflow-hidden min-h-0">
                      {visible.map((ev, ei) => (
                        <button
                          key={ei}
                          onClick={() => openEvent(ev)}
                          className={`text-[10px] leading-tight px-1 py-px rounded truncate text-left text-white/90 hover:brightness-125 transition-all border ${
                            getEventColor(ev)
                          } ${ev.overdue ? "ring-1 ring-red-500/60" : ""}`}
                          title={`${ev.title}${ev.time_of_day ? ` at ${ev.time_of_day}` : ""} (${SOURCE_TYPE_LABELS[ev.source_type] || ev.source_type}${ev.source_type === "schedule" ? " — " + ev.category : ""})`}
                        >
                          {ev.time_of_day && (
                            <span className="text-white/60 mr-0.5">{ev.time_of_day.slice(0, 5)}</span>
                          )}
                          {ev.title}
                        </button>
                      ))}
                      {overflow > 0 && (
                        <button
                          onClick={() => openDay(cell.year, cell.month, cell.day)}
                          className="text-[9px] text-slate-500 hover:text-slate-300 px-1 transition-colors text-left"
                        >
                          +{overflow} more
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
