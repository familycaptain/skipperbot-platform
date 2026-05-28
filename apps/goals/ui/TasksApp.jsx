import { useState, useEffect, useCallback } from "react";
import { ChevronRight, Loader2, RefreshCw, ExternalLink, CheckSquare, Filter } from "lucide-react";
import {
  StatusBadge, PriorityBadge, SearchBar, TaskView,
} from "./GoalShared";

/**
 * Tasks app — flat, due-date-sorted list of all tasks across projects/goals.
 *
 * Props:
 *   appId      – runtime instance ID
 *   userId     – current user's canonical name
 *   context    – { taskId? } for deep-linking
 *   onTitle    – callback(newTitle) to update tab label
 *   onOpenApp  – callback(appType, context) to open another app
 *   refreshKey – increments when chat mutates goal data
 */

const API_BASE = "";
const STATUSES = ["not_started", "in_progress", "done", "blocked", "deferred", "cancelled"];
const HIDDEN_STATUSES = new Set(["done", "cancelled"]);

export default function TasksApp({ appId, userId, context = {}, onTitle, onContextChange, refreshKey, onOpenApp }) {
  const [view, setView] = useState("list"); // "list" | "detail"
  const [tasks, setTasks] = useState(null);
  const [taskDetail, setTaskDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showCompleted, setShowCompleted] = useState(false);

  async function apiFetch(endpoint) {
    const res = await fetch(`${API_BASE}${endpoint}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function apiMutate(endpoint, method, body) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function patchEntity(entityId, fields) {
    try {
      const resp = await apiMutate(`/api/apps/goals/entities/${entityId}`, "PATCH", {
        updated_by: userId,
        ...fields,
      });
      if (resp?.error) { setError(resp.error); return; }
      // Re-fetch current view
      if (view === "detail" && taskDetail) await loadTask(taskDetail.id);
      else await loadTasks();
    } catch (err) {
      console.error("patchEntity failed:", err);
      setError(err.message || "Update failed");
    }
  }

  async function saveNotes(entityId, content) {
    await apiMutate(`/api/apps/goals/entities/${entityId}/notes`, "PUT", {
      content,
      updated_by: userId,
    });
  }

  // Load task list
  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/goals/my-tasks/${encodeURIComponent(userId)}`);
      // Sort by due date (nulls last), then by priority
      const sorted = (data.tasks || []).sort((a, b) => {
        if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date);
        if (a.due_date) return -1;
        if (b.due_date) return 1;
        const prio = { high: 0, medium: 1, low: 2 };
        return (prio[a.priority] ?? 1) - (prio[b.priority] ?? 1);
      });
      setTasks(sorted);
      setView("list");
      onTitle?.("Tasks");
      onContextChange?.({ app: "tasks", view: "list" });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  // Load task detail
  async function loadTask(taskId) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/goals/tasks/${encodeURIComponent(taskId)}`);
      setTaskDetail(data);
      setView("detail");
      onTitle?.(data.name || "Task");
      onContextChange?.({
        app: "tasks", view: "detail",
        entityId: data.id, entityName: data.name, entityType: "task",
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(entityId) {
    try {
      await fetch(`${API_BASE}/api/apps/goals/entities/${entityId}?updated_by=${encodeURIComponent(userId)}`, { method: "DELETE" });
      await loadTasks();
    } catch (e) {
      setError(e.message);
    }
  }

  function handleSearchSelect(result) {
    if (result.type === "task") loadTask(result.id);
    else if (result.type === "project") onOpenApp?.("goals", { projectId: result.id });
    else if (result.type === "goal") onOpenApp?.("goals", { goalId: result.id });
  }

  // Load on mount (unless deep-linking)
  useEffect(() => {
    if (!context.taskId) loadTasks();
  }, [userId]);

  // Deep-link
  useEffect(() => {
    if (context.taskId) loadTask(context.taskId);
  }, [context.taskId]);

  // Auto-refresh
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (view === "detail" && taskDetail) loadTask(taskDetail.id);
    else loadTasks();
  }, [refreshKey]);

  // Filter tasks
  const visibleTasks = showCompleted
    ? tasks
    : (tasks || []).filter((t) => !HIDDEN_STATUSES.has(t.status));

  // Determine if a due date is overdue
  function isOverdue(dateStr) {
    if (!dateStr) return false;
    return dateStr < new Date().toISOString().slice(0, 10);
  }

  // Loading state
  if (loading && !tasks && !taskDetail) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={20} className="animate-spin mr-2" />
        Loading...
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1 text-sm text-slate-300 min-w-0 overflow-hidden">
          <button
            onClick={loadTasks}
            className="hover:text-white transition-colors shrink-0"
          >
            Tasks
          </button>
          {view === "detail" && taskDetail && (
            <>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <span className="truncate max-w-[300px]">{taskDetail.name}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <SearchBar onSelect={handleSearchSelect} />
          <button
            onClick={() => setShowCompleted(!showCompleted)}
            className={`p-1 rounded transition-colors ${showCompleted ? "text-indigo-400 bg-slate-700" : "text-slate-500 hover:text-white hover:bg-slate-700"}`}
            title={showCompleted ? "Hide completed" : "Show completed"}
          >
            <Filter size={14} />
          </button>
          <button
            onClick={() => {
              if (view === "detail" && taskDetail) loadTask(taskDetail.id);
              else loadTasks();
            }}
            disabled={loading}
            className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Error bar */}
      {error && (
        <div className="px-3 py-1.5 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {view === "list" && tasks && (
          <TaskListView
            tasks={visibleTasks}
            onTaskClick={loadTask}
            patchEntity={patchEntity}
            isOverdue={isOverdue}
            onOpenApp={onOpenApp}
          />
        )}
        {view === "detail" && taskDetail && (
          <TaskView
            task={taskDetail}
            onBack={loadTasks}
            onTaskClick={loadTask}
            onProjectClick={(pid) => onOpenApp?.("goals", { projectId: pid })}
            userId={userId}
            patchEntity={patchEntity}
            saveNotes={saveNotes}
            apiMutate={apiMutate}
            onRefresh={() => loadTask(taskDetail.id)}
            STATUSES={STATUSES}
            onDelete={handleDelete}
            refreshKey={refreshKey}
            onOpenApp={onOpenApp}
          />
        )}
      </div>
    </div>
  );
}

/* ── Flat task list ── */

function TaskListView({ tasks, onTaskClick, patchEntity, isOverdue, onOpenApp }) {
  if (!tasks || tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500">
        <CheckSquare size={32} className="text-slate-600 mb-2" />
        <p className="text-sm">No tasks</p>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <p className="text-xs text-slate-500 mb-2">{tasks.length} task{tasks.length !== 1 ? "s" : ""}</p>
      {tasks.map((t) => (
        <div
          key={t.id}
          onClick={() => onTaskClick(t.id)}
          className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2 min-w-0">
            <StatusBadge status={t.status} entityId={t.id} patchEntity={patchEntity} STATUSES={STATUSES} />
            <div className="min-w-0">
              <span className="text-sm text-slate-200 text-left block">
                {t.name}
              </span>
              <div className="text-[10px] text-slate-600 flex items-center gap-1">
                {t.goal_name && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onOpenApp?.("goals", { goalId: t.goal_id }); }}
                    className="hover:text-slate-400 transition-colors"
                  >
                    {t.goal_name}
                  </button>
                )}
                {t.goal_name && t.project_name && <span>/</span>}
                {t.project_name && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onOpenApp?.("goals", { projectId: t.project_id }); }}
                    className="hover:text-slate-400 transition-colors"
                  >
                    {t.project_name}
                  </button>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0 text-xs text-slate-500">
            {t.trello_linked && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-700/30" title="Trello-linked">
                <ExternalLink size={9} />
              </span>
            )}
            {t.due_date && (
              <span className={isOverdue(t.due_date) ? "text-red-400 font-medium" : ""}>
                {t.due_date}
              </span>
            )}
            <PriorityBadge priority={t.priority} entityId={t.id} patchEntity={patchEntity} />
            <ChevronRight size={12} className="text-slate-600" />
          </div>
        </div>
      ))}
    </div>
  );
}
