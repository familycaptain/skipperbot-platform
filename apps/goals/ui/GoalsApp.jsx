import { useState, useEffect, useCallback, useRef } from "react";
import { Target, ChevronRight, ChevronUp, ChevronDown, Loader2, RefreshCw, FileText, Users, Plus, ExternalLink } from "lucide-react";
import {
  STATUS_COLORS, PRIORITIES, PRIORITY_COLORS,
  StatusBadge, QuickAdd, EditableDoD, EditableNotes, PriorityBadge,
  AssigneeField, DueDateField, CadenceField, EditableTitle, DeleteButton,
  SearchBar, TaskView, TrelloLabels, LinkedDocs, HistorySection, LinkedArtifacts,
} from "./GoalShared";

/**
 * Goals app — browse goals, projects, and tasks.
 *
 * Props:
 *   appId   – runtime instance ID
 *   userId  – current user's canonical name
 *   context – { goalId?, projectId? } for deep-linking
 *   onTitle – callback(newTitle) to update tab label
 */

const API_BASE = "";

export default function GoalsApp({ appId, userId, context = {}, onTitle, onContextChange, refreshKey, onOpenApp }) {
  const [view, setView] = useState("summary"); // "summary" | "goal" | "project" | "task" | "mytasks"
  const [goals, setGoals] = useState(null);
  const [goalDetail, setGoalDetail] = useState(null);
  const [projectDetail, setProjectDetail] = useState(null);
  const [taskDetail, setTaskDetail] = useState(null);
  const [myTasks, setMyTasks] = useState(null);
  const [allUsers, setAllUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);

  // Scroll content to top on every view/entity change
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [view, goalDetail?.id, projectDetail?.id, taskDetail?.id]);

  // Load goals summary on mount (skip if deep-link context present)
  useEffect(() => {
    if (!context.taskId && !context.projectId && !context.goalId) {
      loadSummary();
    }
  }, [userId]);

  // Deep-link from context
  useEffect(() => {
    if (context.taskId) {
      loadTask(context.taskId);
    } else if (context.projectId) {
      loadProject(context.projectId);
    } else if (context.goalId) {
      loadGoal(context.goalId);
    }
  }, [context.goalId, context.projectId, context.taskId]);

  // Auto-refresh when chat mutates goal data (refreshKey increments)
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (view === "mytasks") loadMyTasks();
    else if (view === "task" && taskDetail) loadTask(taskDetail.id);
    else if (view === "project" && projectDetail) loadProject(projectDetail.id);
    else if (view === "goal" && goalDetail) loadGoal(goalDetail.id);
    else loadSummary();
  }, [refreshKey]);

  const STATUSES = ["not_started", "in_progress", "done", "blocked", "deferred", "cancelled"];

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
      if (view === "task" && taskDetail) await loadTask(taskDetail.id);
      else if (view === "project" && projectDetail) await loadProject(projectDetail.id);
      else if (view === "goal" && goalDetail) await loadGoal(goalDetail.id);
      else await loadSummary();
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

  async function loadMyTasks() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/goals/my-tasks/${encodeURIComponent(userId)}`);
      setMyTasks(data.tasks);
      setView("mytasks");
      onTitle?.("My Tasks");
      onContextChange?.({ app: "goals", view: "mytasks" });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(entityId) {
    try {
      await fetch(`${API_BASE}/api/apps/goals/entities/${entityId}?updated_by=${encodeURIComponent(userId)}`, { method: "DELETE" });
      // Navigate back
      if (view === "task" && taskDetail) {
        if (taskDetail.project_id) loadProject(taskDetail.project_id);
        else loadSummary();
      } else if (view === "project" && projectDetail) {
        if (projectDetail.goal_id) loadGoal(projectDetail.goal_id);
        else loadSummary();
      } else {
        loadSummary();
      }
    } catch (e) {
      setError(e.message);
    }
  }

  function handleSearchSelect(result) {
    if (result.type === "goal") loadGoal(result.id);
    else if (result.type === "project") loadProject(result.id);
    else if (result.type === "task") loadTask(result.id);
  }

  async function loadSummary() {
    setLoading(true);
    setError(null);
    try {
      const [goalsData, usersData] = await Promise.all([
        apiFetch(`/api/apps/goals/summary`),
        apiFetch(`/api/users?include_bots=true`),
      ]);
      setGoals(goalsData.goals);
      setAllUsers(usersData);
      setView("summary");
      onTitle?.("Goals");
      onContextChange?.({ app: "goals", view: "summary" });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadGoal(goalId) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/goals/${encodeURIComponent(goalId)}`);
      setGoalDetail(data);
      setView("goal");
      onTitle?.(data.name || "Goal");
      onContextChange?.({
        app: "goals", view: "goal",
        entityId: data.id, entityName: data.name, entityType: "goal",
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadProject(projectId) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/goals/projects/${encodeURIComponent(projectId)}`);
      setProjectDetail(data);
      setView("project");
      onTitle?.(data.name || "Project");
      onContextChange?.({
        app: "goals", view: "project",
        entityId: data.id, entityName: data.name, entityType: "project",
        parentId: data.goal_id, parentName: data.goal_name,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  // Status badge colors
  const statusColor = {
    not_started: "bg-slate-600",
    in_progress: "bg-blue-600",
    done: "bg-emerald-600",
    blocked: "bg-red-600",
    deferred: "bg-amber-600",
    cancelled: "bg-gray-600",
  };

  const priorityColor = {
    high: "text-red-400",
    medium: "text-amber-400",
    low: "text-slate-400",
  };

  async function loadTask(taskId) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/goals/tasks/${encodeURIComponent(taskId)}`);
      setTaskDetail(data);
      setView("task");
      onTitle?.(data.name || "Task");
      onContextChange?.({
        app: "goals", view: "task",
        entityId: data.id, entityName: data.name, entityType: "task",
        parentId: data.project_id, parentName: data.project_name,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (loading && !goals && !goalDetail && !projectDetail && !taskDetail) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={20} className="animate-spin mr-2" />
        Loading...
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full min-w-0">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1 text-sm text-slate-300 min-w-0 overflow-hidden">
          <button
            onClick={loadSummary}
            className="hover:text-white transition-colors shrink-0"
          >
            Goals
          </button>
          {view === "mytasks" && (
            <>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <span className="text-slate-200 shrink-0">My Tasks</span>
            </>
          )}
          {view === "goal" && goalDetail && (
            <>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <span className="truncate max-w-[200px]">{goalDetail.name}</span>
            </>
          )}
          {view === "project" && projectDetail && (
            <>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <button
                onClick={() => projectDetail.goal_id && loadGoal(projectDetail.goal_id)}
                className="hover:text-white transition-colors truncate max-w-[120px]"
              >
                {projectDetail.goal_name || "Goal"}
              </button>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <span className="truncate max-w-[200px]">{projectDetail.name}</span>
            </>
          )}
          {view === "task" && taskDetail && (
            <>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <button
                onClick={() => taskDetail.goal_id && loadGoal(taskDetail.goal_id)}
                className="hover:text-white transition-colors truncate max-w-[100px]"
              >
                {taskDetail.goal_name || "Goal"}
              </button>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <button
                onClick={() => taskDetail.project_id && loadProject(taskDetail.project_id)}
                className="hover:text-white transition-colors truncate max-w-[100px]"
              >
                {taskDetail.project_name || "Project"}
              </button>
              <ChevronRight size={14} className="text-slate-600 shrink-0" />
              <span className="truncate max-w-[200px]">{taskDetail.name}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <SearchBar onSelect={handleSearchSelect} />
          <button
            onClick={loadMyTasks}
            className={`p-1 rounded transition-colors ${view === "mytasks" ? "text-indigo-400 bg-slate-700" : "text-slate-500 hover:text-white hover:bg-slate-700"}`}
            title="My Tasks"
          >
            <Users size={14} />
          </button>
          <button
            onClick={() => {
              if (view === "mytasks") loadMyTasks();
              else if (view === "task" && taskDetail) loadTask(taskDetail.id);
              else if (view === "project" && projectDetail) loadProject(projectDetail.id);
              else if (view === "goal" && goalDetail) loadGoal(goalDetail.id);
              else loadSummary();
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
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        {view === "summary" && goals && (
          <SummaryView goals={goals} allUsers={allUsers} onGoalClick={loadGoal} statusColor={statusColor}
            userId={userId} apiMutate={apiMutate} onRefresh={loadSummary} />
        )}
        {view === "mytasks" && myTasks && (
          <MyTasksView tasks={myTasks} onTaskClick={loadTask} statusColor={statusColor} priorityColor={priorityColor}
            patchEntity={patchEntity} STATUSES={STATUSES} />
        )}
        {view === "goal" && goalDetail && (
          <GoalView goal={goalDetail} onProjectClick={loadProject} onSummary={loadSummary} statusColor={statusColor} priorityColor={priorityColor}
            userId={userId} patchEntity={patchEntity} saveNotes={saveNotes} apiMutate={apiMutate}
            onRefresh={() => loadGoal(goalDetail.id)} STATUSES={STATUSES} onDelete={handleDelete} refreshKey={refreshKey} onOpenApp={onOpenApp} />
        )}
        {view === "project" && projectDetail && (
          <ProjectView project={projectDetail} onTaskClick={loadTask} onGoalClick={loadGoal} statusColor={statusColor} priorityColor={priorityColor}
            userId={userId} patchEntity={patchEntity} saveNotes={saveNotes} apiMutate={apiMutate}
            onRefresh={() => loadProject(projectDetail.id)} STATUSES={STATUSES} onDelete={handleDelete} refreshKey={refreshKey} onOpenApp={onOpenApp} />
        )}
        {view === "task" && taskDetail && (
          <TaskView task={taskDetail} onTaskClick={loadTask} onProjectClick={loadProject} statusColor={statusColor} priorityColor={priorityColor}
            userId={userId} patchEntity={patchEntity} saveNotes={saveNotes} apiMutate={apiMutate}
            onRefresh={() => loadTask(taskDetail.id)} STATUSES={STATUSES} onDelete={handleDelete} refreshKey={refreshKey} onOpenApp={onOpenApp} />
        )}
      </div>
    </div>
  );
}

/* ── Sub-views ── */

function GoalCard({ goal, onGoalClick, statusColor }) {
  return (
    <button
      key={goal.id}
      onClick={() => onGoalClick(goal.id)}
      className="w-full text-left px-4 py-3 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 transition-colors"
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-200">{goal.name}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full text-white ${statusColor[goal.status] || "bg-slate-600"}`}>
          {goal.status?.replace("_", " ")}
        </span>
      </div>
      {goal.progress !== undefined && (
        <div className="mt-2 flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full transition-all"
              style={{ width: `${Math.round(goal.progress * 100)}%` }}
            />
          </div>
          <span className="text-xs text-slate-400">{Math.round(goal.progress * 100)}%</span>
        </div>
      )}
    </button>
  );
}

function SummaryView({ goals, allUsers, onGoalClick, statusColor, userId, apiMutate, onRefresh }) {
  async function handleCreateGoal(name) {
    await apiMutate("/api/apps/goals", "POST", { name, created_by: userId });
    onRefresh?.();
  }

  // Build user sort map: name → sort_order
  const userSortMap = {};
  const userDisplayMap = {};
  for (const u of (allUsers || [])) {
    userSortMap[u.name] = u.sort_order ?? 99;
    userDisplayMap[u.name] = u.display_name || u.name;
  }

  // Group goals by primary owner (first owner, or "unassigned")
  const myGoals = [];
  const otherGroups = {}; // owner → goals[]
  for (const g of (goals || [])) {
    const owners = g.owners || [];
    if (owners.includes(userId)) {
      myGoals.push(g);
    } else {
      const primary = owners[0] || "_unassigned";
      if (!otherGroups[primary]) otherGroups[primary] = [];
      otherGroups[primary].push(g);
    }
  }

  // Sort other groups by user sort_order
  const sortedOwners = Object.keys(otherGroups).sort((a, b) => {
    return (userSortMap[a] ?? 99) - (userSortMap[b] ?? 99);
  });

  if (!goals || goals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500">
        <Target size={32} className="text-slate-600 mb-2" />
        <p className="text-sm">No goals yet</p>
        <div className="mt-4 w-full max-w-md">
          <QuickAdd placeholder="New goal name..." onSubmit={handleCreateGoal} />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* My Goals */}
      <div>
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">My Goals</h2>
        <QuickAdd placeholder="New goal..." onSubmit={handleCreateGoal} />
        <div className="space-y-2 mt-2">
          {myGoals.length > 0 ? myGoals.map(g => (
            <GoalCard key={g.id} goal={g} onGoalClick={onGoalClick} statusColor={statusColor} />
          )) : (
            <p className="text-xs text-slate-600 italic px-2">No goals assigned to you</p>
          )}
        </div>
      </div>

      {/* Other users' goals */}
      {sortedOwners.map(owner => (
        <div key={owner}>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            {owner === "_unassigned" ? "Unassigned" : (userDisplayMap[owner] || owner)}
          </h2>
          <div className="space-y-2">
            {otherGroups[owner].map(g => (
              <GoalCard key={g.id} goal={g} onGoalClick={onGoalClick} statusColor={statusColor} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function GoalView({ goal, onProjectClick, onSummary, statusColor, priorityColor, userId, patchEntity, saveNotes, apiMutate, onRefresh, STATUSES, onDelete, refreshKey, onOpenApp }) {
  async function handleCreateProject(name) {
    await apiMutate("/api/apps/goals/projects", "POST", {
      goal_id: goal.id, name, created_by: userId,
    });
    onRefresh?.();
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <button onClick={() => onSummary?.()} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors" title="Back to goals">
            <ChevronRight size={18} className="rotate-180" />
          </button>
          <span className="text-slate-500 text-sm font-semibold shrink-0">GOAL:</span>
          <EditableTitle name={goal.name} entityId={goal.id} patchEntity={patchEntity} />
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-slate-400">
          <StatusBadge status={goal.status} entityId={goal.id} patchEntity={patchEntity} STATUSES={STATUSES} />
          <span className="text-slate-600">|</span>
          <button onClick={() => { navigator.clipboard.writeText(goal.id); }} className="text-slate-500 hover:text-slate-200 cursor-pointer transition-colors" title="Copy ID">{goal.id}</button>
          <span>Owners: <AssigneeField assignees={goal.owners} entityId={goal.id} patchEntity={patchEntity} fieldName="owners" /></span>
          <span>Collaborators: <AssigneeField assignees={goal.collaborators || []} entityId={goal.id} patchEntity={patchEntity} fieldName="collaborators" /></span>
          <span className="flex items-center gap-1">Target: <DueDateField date={goal.target_date} entityId={goal.id} patchEntity={patchEntity} fieldName="target_date" /></span>
          {goal.created_by && <span>Created by: {goal.created_by}</span>}
          <DeleteButton entityId={goal.id} entityName={goal.name} onDelete={onDelete} />
        </div>
      </div>

      <EditableNotes entityId={goal.id} notes={goal.notes} saveNotes={saveNotes} />

      <EditableDoD entityId={goal.id} dod={goal.definition_of_done} patchEntity={patchEntity} userId={userId} />

      <LinkedDocs entityId={goal.id} userId={userId} refreshKey={refreshKey} onOpenApp={onOpenApp} />

      <LinkedArtifacts entityId={goal.id} refreshKey={refreshKey} />

      <div className="space-y-2">
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">Projects</h3>
        <QuickAdd placeholder="New project..." onSubmit={handleCreateProject} />
        {goal.projects && goal.projects.length > 0 ? (
          goal.projects.map((p) => (
            <button
              key={p.id}
              onClick={() => onProjectClick(p.id)}
              className="w-full text-left px-4 py-3 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-200">{p.name}</span>
                  <span className={`text-xs ${priorityColor[p.priority] || "text-slate-400"}`}>
                    {p.priority}
                  </span>
                  {p.trello_board && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-700/30 flex items-center gap-0.5">
                      <ExternalLink size={8} className="opacity-60" />
                      {p.trello_board}
                    </span>
                  )}
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full text-white ${statusColor[p.status] || "bg-slate-600"}`}>
                  {p.status?.replace("_", " ")}
                </span>
              </div>
              {p.due_date && (
                <div className="mt-1 text-xs text-slate-500">Due: {p.due_date}</div>
              )}
              {p.task_summary && (
                <div className="mt-1 text-xs text-slate-500">{p.task_summary}</div>
              )}
            </button>
          ))
        ) : (
          <p className="text-sm text-slate-500">No projects yet — add one above</p>
        )}
      </div>
    </div>
  );
}

function ProjectView({ project, onTaskClick, onGoalClick, statusColor, priorityColor, userId, patchEntity, saveNotes, apiMutate, onRefresh, STATUSES, onDelete, refreshKey, onOpenApp }) {
  const [highlightId, setHighlightId] = useState(null);

  useEffect(() => {
    if (!highlightId) return;
    const timer = setTimeout(() => {
      const el = document.querySelector(`[data-task-id="${highlightId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        el.classList.add("task-flash");
        setTimeout(() => el.classList.remove("task-flash"), 1500);
      }
      setHighlightId(null);
    }, 100);
    return () => clearTimeout(timer);
  }, [highlightId, project.tasks]);

  const groupedTasks = {};
  const statusOrder = ["in_progress", "not_started", "blocked", "deferred", "done", "cancelled"];

  (project.tasks || []).forEach((t) => {
    const s = t.status || "not_started";
    if (!groupedTasks[s]) groupedTasks[s] = [];
    groupedTasks[s].push(t);
  });

  async function handleCreateTask(name) {
    const res = await apiMutate("/api/apps/goals/tasks", "POST", {
      project_id: project.id, name, created_by: userId,
    });
    await onRefresh?.();
    if (res?.id) setHighlightId(res.id);
  }

  async function handleReorder(taskId, direction) {
    try {
      await apiMutate("/api/apps/goals/tasks/reorder", "POST", {
        task_id: taskId, direction, updated_by: userId,
      });
      onRefresh?.();
    } catch {}
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          {project.goal_id && (
            <button onClick={() => onGoalClick?.(project.goal_id)} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors" title="Back to goal">
              <ChevronRight size={18} className="rotate-180" />
            </button>
          )}
          <span className="text-slate-500 text-sm font-semibold shrink-0">PROJECT:</span>
          <EditableTitle name={project.name} entityId={project.id} patchEntity={patchEntity} />
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-slate-400">
          <StatusBadge status={project.status} entityId={project.id} patchEntity={patchEntity} STATUSES={STATUSES} />
          <PriorityBadge priority={project.priority} entityId={project.id} patchEntity={patchEntity} />
          <span className="text-slate-600">|</span>
          <button onClick={() => { navigator.clipboard.writeText(project.id); }} className="text-slate-500 hover:text-slate-200 cursor-pointer transition-colors" title="Copy ID">{project.id}</button>
          {project.trello_board && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-700/30 flex items-center gap-0.5">
              <ExternalLink size={8} className="opacity-60" />
              {project.trello_board}
            </span>
          )}
          <span>Owners: <AssigneeField assignees={project.owners} entityId={project.id} patchEntity={patchEntity} fieldName="owners" /></span>
          <span className="flex items-center gap-1">Due: <DueDateField date={project.due_date} entityId={project.id} patchEntity={patchEntity} /></span>
          <span className="flex items-center gap-1" title="PM check-in cadence">PM cadence: <CadenceField cadence={project.pm_cadence_minutes} entityId={project.id} patchEntity={patchEntity} /></span>
          {project.created_by && <span>Created by: {project.created_by}</span>}
          <DeleteButton entityId={project.id} entityName={project.name} onDelete={onDelete} />
        </div>
      </div>

      <EditableNotes entityId={project.id} notes={project.notes} saveNotes={saveNotes} />

      <EditableDoD entityId={project.id} dod={project.definition_of_done} patchEntity={patchEntity} userId={userId} />

      <LinkedDocs entityId={project.id} userId={userId} refreshKey={refreshKey} onOpenApp={onOpenApp} />

      <LinkedArtifacts entityId={project.id} refreshKey={refreshKey} />

      <HistorySection
        entityId={project.id}
        history={project.history}
        userId={userId}
        patchEntity={patchEntity}
        onRefresh={onRefresh}
      />

      <div>
        <QuickAdd placeholder="New task..." onSubmit={handleCreateTask} />
      </div>

      {statusOrder.map((status) => {
        const tasks = groupedTasks[status];
        if (!tasks || tasks.length === 0) return null;
        return (
          <div key={status}>
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
              {status.replace("_", " ")} ({tasks.length})
            </h3>
            <div className="space-y-1.5">
              {tasks.map((t, i) => (
                <div
                  key={t.id}
                  data-task-id={t.id}
                  onClick={() => onTaskClick(t.id)}
                  className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 transition-colors group cursor-pointer"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {tasks.length > 1 && (
                      <div className="flex flex-col -my-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleReorder(t.id, "up"); }}
                          disabled={i === 0}
                          className="p-0.5 text-slate-600 hover:text-white disabled:opacity-20 disabled:hover:text-slate-600 transition-colors"
                          title="Move up"
                        >
                          <ChevronUp size={12} />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleReorder(t.id, "down"); }}
                          disabled={i === tasks.length - 1}
                          className="p-0.5 text-slate-600 hover:text-white disabled:opacity-20 disabled:hover:text-slate-600 transition-colors"
                          title="Move down"
                        >
                          <ChevronDown size={12} />
                        </button>
                      </div>
                    )}
                    <StatusBadge status={t.status} entityId={t.id} patchEntity={patchEntity} STATUSES={STATUSES} />
                    <span className="text-sm text-slate-200 text-left">
                      {t.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 text-xs text-slate-500">
                    {t.trello_linked && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-700/30" title="Trello-linked">
                        <ExternalLink size={9} />
                      </span>
                    )}
                    {t.assigned_to && <span>{t.assigned_to}</span>}
                    {t.due_date && <span>{t.due_date}</span>}
                    <PriorityBadge priority={t.priority} entityId={t.id} patchEntity={patchEntity} />
                    <ChevronRight size={12} className="text-slate-600" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {(!project.tasks || project.tasks.length === 0) && (
        <p className="text-sm text-slate-500">No tasks yet — add one above</p>
      )}
    </div>
  );
}

function MyTasksView({ tasks, onTaskClick, statusColor, priorityColor, patchEntity, STATUSES }) {
  if (!tasks || tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-500">
        <Users size={32} className="text-slate-600 mb-2" />
        <p className="text-sm">No tasks assigned to you</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">{tasks.length} task{tasks.length !== 1 ? "s" : ""} assigned to you</p>
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
              <div className="text-[10px] text-slate-600">
                {t.goal_name && <span>{t.goal_name}</span>}
                {t.goal_name && t.project_name && <span> / </span>}
                {t.project_name && <span>{t.project_name}</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0 text-xs text-slate-500">
            {t.trello_linked && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-700/30" title="Trello-linked">
                <ExternalLink size={9} />
              </span>
            )}
            {t.due_date && <span>{t.due_date}</span>}
            <PriorityBadge priority={t.priority} entityId={t.id} patchEntity={patchEntity} />
            <ChevronRight size={12} className="text-slate-600" />
          </div>
        </div>
      ))}
    </div>
  );
}
