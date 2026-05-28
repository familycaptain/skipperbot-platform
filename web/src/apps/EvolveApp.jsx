import { useState, useEffect, useCallback, useRef } from "react";
import { Sparkles, ChevronLeft, ChevronRight, Loader2, RefreshCw, X, Send, Filter, BarChart3, Plus, CheckCircle2, Clock, XCircle, ArrowRight, MessageSquare, ChevronDown, Activity, Zap, AlertTriangle, ChevronUp, Play, List, Layers, Hash, Pin } from "lucide-react";

const API = "/api/apps/evolve";

const STATUS_COLORS = {
  new: "bg-blue-600",
  reviewed: "bg-indigo-600",
  approved: "bg-emerald-600",
  redirected: "bg-amber-600",
  deferred: "bg-slate-500",
  rejected: "bg-red-700",
  dismissed: "bg-slate-600",
  in_progress: "bg-cyan-600",
  completed: "bg-emerald-700",
};

const TYPE_LABELS = {
  finding: { emoji: "🔍", label: "Finding" },
  proposal: { emoji: "💡", label: "Proposal" },
  question: { emoji: "❓", label: "Question" },
  goal: { emoji: "🎯", label: "Goal" },
  work_item: { emoji: "🔧", label: "Work Item" },
  status_update: { emoji: "📋", label: "Status" },
};

const IMPACT_COLORS = { high: "text-red-400", medium: "text-amber-400", low: "text-slate-400" };

export default function EvolveApp({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const [view, setView] = useState("feed"); // "feed" | "detail" | "dashboard"
  const [items, setItems] = useState(null);
  const [detail, setDetail] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [filterType, setFilterType] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);

  async function apiFetch(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function apiMutate(url, method, body) {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  const loadItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set("status", filterStatus);
      if (filterType) params.set("type", filterType);
      if (showCompleted) params.set("include_completed", "true");
      const qs = params.toString();
      const data = await apiFetch(`${API}/items${qs ? "?" + qs : ""}`);
      setItems(data.items || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterType, showCompleted]);

  const loadStats = useCallback(async () => {
    try {
      const data = await apiFetch(`${API}/stats`);
      setStats(data);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => { loadItems(); loadStats(); }, [loadItems, loadStats]);

  useEffect(() => {
    if (context.itemId) loadDetail(context.itemId);
  }, [context.itemId]);

  async function loadDetail(itemId) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`${API}/items/${itemId}`);
      setDetail(data);
      setView("detail");
      onTitle?.(data.title || "Evolution Item");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function goFeed() {
    setView("feed");
    setDetail(null);
    onTitle?.("Evolve");
    loadItems();
    loadStats();
  }

  if (loading && !items && !detail) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={20} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col text-slate-200">
      {error && (
        <div className="px-4 py-2 bg-red-900/40 border-b border-red-700/40 text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-2 hover:text-white"><X size={14} /></button>
        </div>
      )}

      {view === "feed" && (
        <FeedView
          items={items || []}
          stats={stats}
          filterStatus={filterStatus}
          setFilterStatus={setFilterStatus}
          filterType={filterType}
          setFilterType={setFilterType}
          showCompleted={showCompleted}
          setShowCompleted={setShowCompleted}
          onItemClick={loadDetail}
          onRefresh={() => { loadItems(); loadStats(); }}
          onDashboard={() => setView("dashboard")}
          loading={loading}
        />
      )}

      {view === "detail" && detail && (
        <DetailView
          item={detail}
          userId={userId}
          apiMutate={apiMutate}
          onBack={goFeed}
          onRefresh={() => loadDetail(detail.id)}
          setError={setError}
          onItemClick={loadDetail}
        />
      )}

      {view === "dashboard" && (
        <DashboardView
          stats={stats}
          onBack={goFeed}
          onRefresh={loadStats}
        />
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  Feed View                                                                 */
/* ═══════════════════════════════════════════════════════════════════════════ */

function FeedView({ items, stats, filterStatus, setFilterStatus, filterType, setFilterType, showCompleted, setShowCompleted, onItemClick, onRefresh, onDashboard, loading }) {
  const [showFilters, setShowFilters] = useState(false);
  const [feedMode, setFeedMode] = useState("hierarchy"); // "hierarchy" | "flat"

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-amber-400" />
          <span className="font-semibold text-sm">Evolution Feed</span>
          {stats && (
            <span className="text-xs text-slate-500 ml-1">
              {stats.active || 0} active
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* View mode toggle */}
          <div className="flex items-center bg-slate-800 rounded p-0.5 mr-1">
            <button
              onClick={() => setFeedMode("hierarchy")}
              className={`p-1 rounded transition-colors ${feedMode === "hierarchy" ? "bg-slate-700 text-slate-200" : "text-slate-500 hover:text-slate-300"}`}
              title="Goal hierarchy view"
            >
              <Layers size={13} />
            </button>
            <button
              onClick={() => setFeedMode("flat")}
              className={`p-1 rounded transition-colors ${feedMode === "flat" ? "bg-slate-700 text-slate-200" : "text-slate-500 hover:text-slate-300"}`}
              title="Flat stack-ranked view"
            >
              <List size={13} />
            </button>
          </div>
          <button onClick={() => setShowFilters(!showFilters)} className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200" title="Filters">
            <Filter size={14} />
          </button>
          <button onClick={onDashboard} className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200" title="Dashboard">
            <BarChart3 size={14} />
          </button>
          <button onClick={onRefresh} className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200" title="Refresh">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="px-4 py-2 border-b border-slate-800/40 bg-slate-900/40 flex flex-wrap items-center gap-2 text-xs">
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300">
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="approved">Approved</option>
            <option value="in_progress">In Progress</option>
            <option value="redirected">Redirected</option>
            <option value="deferred">Deferred</option>
            <option value="reviewed">Reviewed</option>
          </select>
          <select value={filterType} onChange={e => setFilterType(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300">
            <option value="">All types</option>
            <option value="finding">Finding</option>
            <option value="proposal">Proposal</option>
            <option value="question">Question</option>
            <option value="goal">Goal</option>
            <option value="work_item">Work Item</option>
          </select>
          <label className="flex items-center gap-1 text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showCompleted} onChange={e => setShowCompleted(e.target.checked)}
              className="rounded border-slate-600" />
            Show completed
          </label>
        </div>
      )}

      {/* Stats bar */}
      {stats && stats.active > 0 && (
        <div className="px-4 py-2 border-b border-slate-800/30 flex items-center gap-3 text-[11px] text-slate-500">
          <span className="text-blue-400">{stats.new || 0} new</span>
          <span className="text-emerald-400">{stats.approved || 0} approved</span>
          <span className="text-cyan-400">{stats.in_progress || 0} in progress</span>
          <span className="text-emerald-600">{stats.completed || 0} done</span>
          <span className="text-slate-500">{stats.deferred || 0} deferred</span>
        </div>
      )}

      {/* Scrollable content: cycle monitor + items */}
      <div className="flex-1 overflow-y-auto">
        {/* Cycle Monitor — live progress for running/recent cycles */}
        <CycleMonitor />

        {/* Items */}
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
            <Sparkles size={32} className="text-slate-600" />
            <p className="text-sm">No evolution items yet</p>
            <p className="text-xs text-slate-600">Skipper will create items during Evolve cycles</p>
          </div>
        ) : feedMode === "hierarchy" ? (
          <HierarchicalFeed items={items} onItemClick={onItemClick} />
        ) : (
          <FlatRankedFeed items={items} onItemClick={onItemClick} />
        )}
      </div>
    </div>
  );
}

function ItemRow({ item, onClick }) {
  const typeInfo = TYPE_LABELS[item.type] || TYPE_LABELS.finding;
  const impactClass = IMPACT_COLORS[item.impact] || "";

  return (
    <button
      onClick={onClick}
      className="w-full text-left px-4 py-3 border-b border-slate-800/40 hover:bg-slate-800/30 transition-colors flex items-start gap-3"
    >
      <span className="text-base shrink-0 mt-0.5">{typeInfo.emoji}</span>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-slate-200 line-clamp-2">{item.title}</div>
        <div className="flex items-center gap-2 mt-1 text-[11px]">
          <span className={`px-1.5 py-0.5 rounded text-white ${STATUS_COLORS[item.status] || "bg-slate-600"}`}>
            {item.status.replace("_", " ")}
          </span>
          {item.impact && (
            <span className={impactClass}>{item.impact} impact</span>
          )}
          {item.category && (
            <span className="text-slate-500">{item.category}</span>
          )}
          <span className="text-slate-600">{new Date(item.created_at).toLocaleDateString()}</span>
        </div>
      </div>
      <ChevronRight size={14} className="text-slate-600 shrink-0 mt-1" />
    </button>
  );
}

function PriorityBadge({ rank, pin }) {
  if (!rank && !pin) return null;
  return (
    <div className="flex items-center gap-1 shrink-0">
      {rank && (
        <span className="flex items-center gap-0.5 text-[10px] font-bold text-amber-400 bg-amber-900/30 border border-amber-800/40 rounded px-1.5 py-0.5">
          <Hash size={9} />{rank}
        </span>
      )}
      {pin && (
        <span className="flex items-center gap-0.5 text-[9px] text-purple-300 bg-purple-900/30 border border-purple-800/40 rounded px-1 py-0.5">
          <Pin size={8} />{pin}
        </span>
      )}
    </div>
  );
}

function HierarchicalFeed({ items, onItemClick }) {
  const goals = items
    .filter(it => it.type === "goal")
    .sort((a, b) => (a.priority ?? 999) - (b.priority ?? 999));

  const nonGoals = items.filter(it => it.type !== "goal");

  // Group proposals by parent_id
  const byParent = {};
  const orphans = [];
  for (const it of nonGoals) {
    if (it.parent_id) {
      (byParent[it.parent_id] = byParent[it.parent_id] || []).push(it);
    } else {
      orphans.push(it);
    }
  }
  // Sort children by proposal priority
  for (const k of Object.keys(byParent)) {
    byParent[k].sort((a, b) => (a.priority ?? 999) - (b.priority ?? 999));
  }
  orphans.sort((a, b) => (a.priority ?? 999) - (b.priority ?? 999));

  return (
    <div>
      {goals.map(goal => {
        const children = byParent[goal.id] || [];
        return (
          <div key={goal.id} className="border-b border-slate-800/40">
            {/* Goal header */}
            <button
              onClick={() => onItemClick(goal.id)}
              className="w-full text-left px-4 py-3 hover:bg-slate-800/30 transition-colors flex items-start gap-3 bg-slate-900/40"
            >
              <PriorityBadge rank={goal.priority} pin={goal.priority_pin} />
              <span className="text-base shrink-0 mt-0.5">🎯</span>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-slate-100 font-medium line-clamp-2">{goal.title}</div>
                <div className="flex items-center gap-2 mt-1 text-[11px]">
                  <span className={`px-1.5 py-0.5 rounded text-white ${STATUS_COLORS[goal.status] || "bg-slate-600"}`}>
                    {goal.status.replace("_", " ")}
                  </span>
                  {goal.impact && <span className={IMPACT_COLORS[goal.impact] || ""}>{goal.impact} impact</span>}
                  {goal.category && <span className="text-slate-500">{goal.category}</span>}
                  {children.length > 0 && (
                    <span className="text-slate-500">{children.length} proposal{children.length !== 1 ? "s" : ""}</span>
                  )}
                </div>
              </div>
              <ChevronRight size={14} className="text-slate-600 shrink-0 mt-1" />
            </button>

            {/* Child proposals */}
            {children.map(child => {
              const typeInfo = TYPE_LABELS[child.type] || TYPE_LABELS.finding;
              return (
                <button
                  key={child.id}
                  onClick={() => onItemClick(child.id)}
                  className="w-full text-left pl-10 pr-4 py-2.5 border-t border-slate-800/20 hover:bg-slate-800/20 transition-colors flex items-start gap-2"
                >
                  <PriorityBadge rank={child.priority} pin={child.priority_pin} />
                  <span className="text-sm shrink-0">{typeInfo.emoji}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-slate-300 line-clamp-2">{child.title}</div>
                    <div className="flex items-center gap-2 mt-0.5 text-[10px]">
                      <span className={`px-1 py-0.5 rounded text-white ${STATUS_COLORS[child.status] || "bg-slate-600"}`}>
                        {child.status.replace("_", " ")}
                      </span>
                      {child.impact && <span className={IMPACT_COLORS[child.impact] || ""}>{child.impact}</span>}
                      {child.effort && <span className="text-slate-600">{child.effort} effort</span>}
                    </div>
                  </div>
                  <ChevronRight size={12} className="text-slate-700 shrink-0 mt-0.5" />
                </button>
              );
            })}
          </div>
        );
      })}

      {/* Orphan proposals (no parent goal) */}
      {orphans.length > 0 && (
        <div className="border-b border-slate-800/40">
          <div className="px-4 py-2 text-[11px] text-slate-500 font-medium uppercase tracking-wider bg-slate-900/30">
            Unlinked Items
          </div>
          {orphans.map(item => (
            <ItemRow key={item.id} item={item} onClick={() => onItemClick(item.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function FlatRankedFeed({ items, onItemClick }) {
  // Build goal lookup for tags
  const goalMap = {};
  for (const it of items) {
    if (it.type === "goal") goalMap[it.id] = it;
  }

  // Only proposals/findings/work_items — sorted by priority
  const proposals = items
    .filter(it => it.type !== "goal")
    .sort((a, b) => (a.priority ?? 999) - (b.priority ?? 999));

  return (
    <div>
      {proposals.map(item => {
        const typeInfo = TYPE_LABELS[item.type] || TYPE_LABELS.finding;
        const parentGoal = item.parent_id ? goalMap[item.parent_id] : null;

        return (
          <button
            key={item.id}
            onClick={() => onItemClick(item.id)}
            className="w-full text-left px-4 py-3 border-b border-slate-800/40 hover:bg-slate-800/30 transition-colors flex items-start gap-3"
          >
            <PriorityBadge rank={item.priority} pin={item.priority_pin} />
            <span className="text-base shrink-0 mt-0.5">{typeInfo.emoji}</span>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-slate-200 line-clamp-2">{item.title}</div>
              <div className="flex items-center gap-2 mt-1 text-[11px] flex-wrap">
                <span className={`px-1.5 py-0.5 rounded text-white ${STATUS_COLORS[item.status] || "bg-slate-600"}`}>
                  {item.status.replace("_", " ")}
                </span>
                {item.impact && <span className={IMPACT_COLORS[item.impact] || ""}>{item.impact} impact</span>}
                {item.effort && <span className="text-slate-600">{item.effort} effort</span>}
                {item.category && <span className="text-slate-500">{item.category}</span>}
                {parentGoal && (
                  <span className="text-[10px] text-blue-400 bg-blue-900/20 border border-blue-800/30 rounded px-1.5 py-0.5 truncate max-w-[200px]">
                    🎯 {parentGoal.title}
                    {parentGoal.priority && <span className="text-blue-500 ml-1">#{parentGoal.priority}</span>}
                  </span>
                )}
              </div>
            </div>
            <ChevronRight size={14} className="text-slate-600 shrink-0 mt-1" />
          </button>
        );
      })}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  Detail View                                                               */
/* ═══════════════════════════════════════════════════════════════════════════ */

function DetailView({ item, userId, apiMutate, onBack, onRefresh, setError, onItemClick }) {
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [replyMode, setReplyMode] = useState("discuss"); // "discuss" | "note"
  const [showActions, setShowActions] = useState(false);
  const [showPromote, setShowPromote] = useState(false);
  const [promoteGoals, setPromoteGoals] = useState(null);
  const [promoting, setPromoting] = useState(false);
  const threadEndRef = useRef(null);

  const typeInfo = TYPE_LABELS[item.type] || TYPE_LABELS.finding;

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [item.thread]);

  async function sendReply() {
    if (!reply.trim()) return;
    setSending(true);
    try {
      if (replyMode === "discuss") {
        const res = await fetch(`${API}/items/${item.id}/discuss`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: reply.trim(), author: userId || "alice" }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } else {
        await apiMutate(`${API}/items/${item.id}/thread`, "POST", {
          author: userId || "alice",
          body: reply.trim(),
        });
      }
      setReply("");
      onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }

  async function setStatus(status) {
    try {
      await apiMutate(`${API}/items/${item.id}/status/${status}`, "POST");
      setShowActions(false);
      onRefresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function setPin(pin) {
    try {
      await apiMutate(`${API}/items/${item.id}/pin/${pin}`, "PUT");
      setShowActions(false);
      onRefresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handlePromote(targetGoalId) {
    setPromoting(true);
    try {
      const body = targetGoalId ? { target_goal_id: targetGoalId } : {};
      const res = await fetch(`${API}/items/${item.id}/promote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.needs_goal) {
        setPromoteGoals(data.goals || []);
        return;
      }
      setShowPromote(false);
      setPromoteGoals(null);
      onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setPromoting(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendReply();
    }
  }

  const isPromoted = item.meta?.promoted_to;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800/60">
        <button onClick={onBack} className="p-1 rounded hover:bg-slate-800 text-slate-400">
          <ChevronLeft size={16} />
        </button>
        <span className="text-base">{typeInfo.emoji}</span>
        <span className="font-semibold text-sm flex-1 truncate">{item.title}</span>
        <button onClick={onRefresh} className="p-1 rounded hover:bg-slate-800 text-slate-400">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Metadata */}
      <div className="px-4 py-2 border-b border-slate-800/30 flex flex-wrap items-center gap-2 text-[11px]">
        <PriorityBadge rank={item.priority} pin={item.priority_pin} />
        <span className={`px-2 py-0.5 rounded text-white ${STATUS_COLORS[item.status] || "bg-slate-600"}`}>
          {item.status.replace("_", " ")}
        </span>
        <span className="text-slate-500">{typeInfo.label}</span>
        {item.impact && (
          <span className={IMPACT_COLORS[item.impact] || ""}>{item.impact} impact</span>
        )}
        {item.effort && (
          <span className="text-slate-500">{item.effort} effort</span>
        )}
        {item.category && (
          <span className="text-slate-500 border border-slate-700 rounded px-1.5 py-0.5">{item.category}</span>
        )}
        <span className="text-slate-600 ml-auto">{item.created_by || "skipper"} · {new Date(item.created_at).toLocaleDateString()}</span>
      </div>

      {/* Actions bar */}
      <div className="px-4 py-2 border-b border-slate-800/30 flex flex-wrap items-center gap-1">
        <button onClick={() => setShowActions(!showActions)}
          className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center gap-1">
          Actions <ChevronDown size={12} />
        </button>
        {!isPromoted && (
          <button onClick={() => { setShowPromote(!showPromote); if (!showPromote) handlePromote(); }}
            className="text-xs px-2 py-1 rounded bg-violet-800/60 hover:bg-violet-700/60 text-violet-300 flex items-center gap-1">
            <ArrowRight size={12} /> Promote
          </button>
        )}
        {isPromoted && (
          <span className="text-xs px-2 py-1 rounded bg-emerald-900/40 text-emerald-400 border border-emerald-800/40">
            Promoted → {item.meta.promoted_to}
          </span>
        )}
        {showActions && (
          <div className="flex flex-wrap items-center gap-1 mt-1 w-full">
            {item.status !== "approved" && (
              <button onClick={() => setStatus("approved")}
                className="text-xs px-2 py-1 rounded bg-emerald-800/60 hover:bg-emerald-700/60 text-emerald-300 flex items-center gap-1">
                <CheckCircle2 size={12} /> Approve
              </button>
            )}
            {item.status !== "in_progress" && item.status === "approved" && (
              <button onClick={() => setStatus("in_progress")}
                className="text-xs px-2 py-1 rounded bg-cyan-800/60 hover:bg-cyan-700/60 text-cyan-300 flex items-center gap-1">
                <ArrowRight size={12} /> Start
              </button>
            )}
            {item.status !== "deferred" && (
              <button onClick={() => setStatus("deferred")}
                className="text-xs px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-600/60 text-slate-300 flex items-center gap-1">
                <Clock size={12} /> Defer
              </button>
            )}
            {item.status !== "rejected" && (
              <button onClick={() => setStatus("rejected")}
                className="text-xs px-2 py-1 rounded bg-red-800/60 hover:bg-red-700/60 text-red-300 flex items-center gap-1">
                <XCircle size={12} /> Reject
              </button>
            )}
            {item.status === "in_progress" && (
              <button onClick={() => setStatus("completed")}
                className="text-xs px-2 py-1 rounded bg-emerald-800/60 hover:bg-emerald-700/60 text-emerald-300 flex items-center gap-1">
                <CheckCircle2 size={12} /> Complete
              </button>
            )}
            <span className="text-[10px] text-slate-600 mx-1">|</span>
            <span className="text-[10px] text-slate-500">Pin:</span>
            {["top", "high", "low", "bottom", "lock"].map(p => (
              <button key={p} onClick={() => setPin(p)}
                className={`text-[10px] px-1.5 py-0.5 rounded border ${
                  item.priority_pin === p
                    ? "bg-purple-800/60 border-purple-600 text-purple-200"
                    : "bg-slate-800/60 border-slate-700 text-slate-400 hover:text-slate-200"
                }`}>
                {p}
              </button>
            ))}
            {item.priority_pin && (
              <button onClick={() => setPin("clear")}
                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800/60 border border-slate-700 text-red-400 hover:text-red-300">
                clear
              </button>
            )}
          </div>
        )}
      </div>

      {/* Promote goal picker */}
      {showPromote && promoteGoals && (
        <div className="px-4 py-2 border-b border-slate-800/30 bg-violet-900/10">
          <div className="text-xs text-violet-300 mb-1.5">Select a goal to create project under:</div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {promoteGoals.map(g => (
              <button key={g.id} onClick={() => handlePromote(g.id)}
                disabled={promoting}
                className="w-full text-left px-2 py-1.5 rounded bg-slate-800/40 hover:bg-slate-700/40 text-xs text-slate-300 flex items-center gap-2">
                <span>🎯</span>
                <span className="flex-1 truncate">{g.name}</span>
                <span className="text-[10px] text-slate-500">{g.status}</span>
              </button>
            ))}
          </div>
          <button onClick={() => { setShowPromote(false); setPromoteGoals(null); }}
            className="text-[10px] text-slate-500 hover:text-slate-300 mt-1">Cancel</button>
        </div>
      )}

      {/* Scrollable content area */}
      <div className="flex-1 overflow-y-auto">
        {/* Body */}
        <div className="px-4 py-3 text-sm text-slate-300 whitespace-pre-wrap border-b border-slate-800/30">
          {item.body}
        </div>

        {/* Children */}
        {item.children && item.children.length > 0 && (
          <div className="px-4 py-2 border-b border-slate-800/30">
            <div className="text-xs text-slate-500 mb-1 font-medium">Sub-items ({item.children.length})</div>
            {item.children.map(child => (
              <button key={child.id} onClick={() => onItemClick(child.id)}
                className="w-full text-left px-2 py-1.5 rounded hover:bg-slate-800/40 flex items-center gap-2 text-xs">
                <span>{(TYPE_LABELS[child.type] || TYPE_LABELS.finding).emoji}</span>
                <span className="flex-1 truncate text-slate-300">{child.title}</span>
                <span className={`px-1.5 py-0.5 rounded text-white text-[10px] ${STATUS_COLORS[child.status] || "bg-slate-600"}`}>
                  {child.status}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Thread */}
        <div className="px-4 py-2">
          <div className="text-xs text-slate-500 mb-2 font-medium flex items-center gap-1">
            <MessageSquare size={12} /> Discussion ({(item.thread || []).length})
          </div>
          {(item.thread || []).map(msg => (
            <ThreadMessage key={msg.id} msg={msg} />
          ))}
          <div ref={threadEndRef} />
        </div>
      </div>

      {/* Reply input */}
      <div className="border-t border-slate-800/60">
        {/* Mode toggle */}
        <div className="px-4 pt-2 pb-1 flex items-center gap-1">
          <div className="flex items-center bg-slate-800 rounded p-0.5 text-[11px]">
            <button
              onClick={() => setReplyMode("discuss")}
              className={`px-2 py-0.5 rounded transition-colors ${replyMode === "discuss" ? "bg-blue-700 text-white" : "text-slate-400 hover:text-slate-200"}`}
            >
              Discuss
            </button>
            <button
              onClick={() => setReplyMode("note")}
              className={`px-2 py-0.5 rounded transition-colors ${replyMode === "note" ? "bg-amber-700 text-white" : "text-slate-400 hover:text-slate-200"}`}
            >
              Note
            </button>
          </div>
          <span className="text-[10px] text-slate-600 ml-1">
            {replyMode === "discuss" ? "Skipper will respond" : "Saved for next cycle — no LLM response"}
          </span>
        </div>
        <div className="px-4 pb-3 flex items-end gap-2">
          <textarea
            value={reply}
            onChange={e => setReply(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={replyMode === "discuss" ? "Discuss with Skipper..." : "Leave a note for the next cycle..."}
            rows={1}
            className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 resize-none focus:outline-none focus:border-slate-500"
          />
          <button
            onClick={sendReply}
            disabled={!reply.trim() || sending}
            className={`p-2 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed text-white ${
              replyMode === "discuss" ? "bg-blue-600 hover:bg-blue-500" : "bg-amber-600 hover:bg-amber-500"
            }`}
          >
            {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}

function ThreadMessage({ msg }) {
  const isSkipper = msg.author === "skipper";
  return (
    <div className={`mb-3 flex ${isSkipper ? "justify-start" : "justify-end"}`}>
      <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
        isSkipper
          ? "bg-slate-800/60 text-slate-300"
          : "bg-blue-900/40 text-blue-200"
      }`}>
        <div className="text-[10px] text-slate-500 mb-0.5">
          {msg.author} · {new Date(msg.created_at).toLocaleString()}
        </div>
        <div className="whitespace-pre-wrap">{msg.body}</div>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  Cycle Monitor — live observability for running/recent cycles               */
/* ═══════════════════════════════════════════════════════════════════════════ */

const CYCLE_TYPE_LABELS = {
  deep: { label: "Deep Cycle", color: "text-amber-400", bg: "bg-amber-900/20", border: "border-amber-700/40", icon: Zap },
  feedback: { label: "Feedback Cycle", color: "text-cyan-400", bg: "bg-cyan-900/20", border: "border-cyan-700/40", icon: RefreshCw },
  assessment: { label: "Assessment Cycle", color: "text-violet-400", bg: "bg-violet-900/20", border: "border-violet-700/40", icon: Activity },
  planning: { label: "Planning Cycle", color: "text-emerald-400", bg: "bg-emerald-900/20", border: "border-emerald-700/40", icon: ArrowRight },
  vision: { label: "Vision Cycle", color: "text-blue-400", bg: "bg-blue-900/20", border: "border-blue-700/40", icon: Sparkles },
  solo_vision: { label: "Solo: Vision", color: "text-blue-400", bg: "bg-blue-900/20", border: "border-blue-700/40", icon: Sparkles },
  solo_assessment: { label: "Solo: Assessment", color: "text-violet-400", bg: "bg-violet-900/20", border: "border-violet-700/40", icon: Activity },
  solo_gap: { label: "Solo: Gap Analysis", color: "text-orange-400", bg: "bg-orange-900/20", border: "border-orange-700/40", icon: AlertTriangle },
  solo_planning: { label: "Solo: Planning", color: "text-emerald-400", bg: "bg-emerald-900/20", border: "border-emerald-700/40", icon: ArrowRight },
  solo_propose: { label: "Solo: Propose", color: "text-amber-400", bg: "bg-amber-900/20", border: "border-amber-700/40", icon: Zap },
  solo_reconcile: { label: "Solo: Reconcile", color: "text-cyan-400", bg: "bg-cyan-900/20", border: "border-cyan-700/40", icon: RefreshCw },
  unknown: { label: "Cycle", color: "text-slate-400", bg: "bg-slate-800/30", border: "border-slate-700/40", icon: Activity },
};

const PHASE_STATUS_STYLES = {
  completed: { bg: "bg-emerald-600", text: "text-emerald-300", barBg: "bg-emerald-600", icon: CheckCircle2 },
  failed: { bg: "bg-red-600", text: "text-red-300", barBg: "bg-red-600", icon: AlertTriangle },
  running: { bg: "bg-cyan-600", text: "text-cyan-300", barBg: "bg-cyan-500", icon: Play },
  queued: { bg: "bg-slate-700", text: "text-slate-500", barBg: "bg-slate-600", icon: Clock },
  cancelled: { bg: "bg-slate-700", text: "text-slate-500", barBg: "bg-slate-600", icon: XCircle },
};

function CycleMonitor() {
  const [cycles, setCycles] = useState(null);
  const [expanded, setExpanded] = useState({}); // cycle_id -> bool
  const [phaseExpanded, setPhaseExpanded] = useState({}); // phase_id -> bool
  const [unitData, setUnitData] = useState({}); // phase_id -> units[]
  const [polling, setPolling] = useState(true);
  const [showTrigger, setShowTrigger] = useState(false);
  const [cycleTypes, setCycleTypes] = useState(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState(null);

  const loadCycles = useCallback(async () => {
    try {
      const res = await fetch(`${API}/cycles?limit=5`);
      if (!res.ok) return;
      const data = await res.json();
      setCycles(data.cycles || []);

      // Auto-expand any running cycle
      const running = (data.cycles || []).filter(c => c.status === "running" || c.status === "queued");
      if (running.length > 0) {
        setExpanded(prev => {
          const next = { ...prev };
          running.forEach(c => { if (!(c.id in next)) next[c.id] = true; });
          return next;
        });
      }
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => { loadCycles(); }, [loadCycles]);

  // Poll every 5s when there's a running cycle
  useEffect(() => {
    if (!polling) return;
    const hasRunning = cycles?.some(c => c.status === "running" || c.status === "queued");
    const interval = hasRunning ? 5000 : 30000;
    const timer = setInterval(loadCycles, interval);
    return () => clearInterval(timer);
  }, [polling, cycles, loadCycles]);

  const fetchUnits = async (phaseId) => {
    try {
      const res = await fetch(`${API}/phases/${phaseId}/units`);
      if (res.ok) {
        const data = await res.json();
        setUnitData(prev => ({ ...prev, [phaseId]: data.units || [] }));
      }
    } catch (e) { /* silent */ }
  };

  const togglePhase = async (phaseId) => {
    const isOpen = phaseExpanded[phaseId];
    setPhaseExpanded(prev => ({ ...prev, [phaseId]: !isOpen }));
    // Always refresh unit data when expanding
    if (!isOpen) await fetchUnits(phaseId);
  };

  // Refresh expanded phase unit data whenever cycles change (covers running→completed transition)
  useEffect(() => {
    const expandedPhaseIds = Object.entries(phaseExpanded).filter(([, v]) => v).map(([k]) => k);
    if (expandedPhaseIds.length === 0) return;
    // Immediate refresh when cycle data changes
    expandedPhaseIds.forEach(pid => fetchUnits(pid));
    // Continue polling while running
    const hasRunning = cycles?.some(c => c.status === "running" || c.status === "queued");
    if (!hasRunning) return;
    const timer = setInterval(() => {
      expandedPhaseIds.forEach(pid => fetchUnits(pid));
    }, 8000);
    return () => clearInterval(timer);
  }, [cycles, phaseExpanded]);

  const loadCycleTypes = async () => {
    if (cycleTypes) return;
    try {
      const res = await fetch(`${API}/cycle-types`);
      if (res.ok) {
        const data = await res.json();
        setCycleTypes(data.cycle_types || []);
      }
    } catch (e) { /* silent */ }
  };

  const triggerCycle = async (cycleType) => {
    setTriggering(true);
    setTriggerError(null);
    try {
      const res = await fetch(`${API}/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cycle_type: cycleType }),
      });
      const data = await res.json();
      if (!res.ok) {
        setTriggerError(data.detail || `HTTP ${res.status}`);
      } else if (data.ok === false) {
        setTriggerError(data.error || "Failed to start");
      } else {
        setShowTrigger(false);
        setTimeout(loadCycles, 1000);
      }
    } catch (e) {
      setTriggerError(e.message);
    } finally {
      setTriggering(false);
    }
  };

  const hasRunning = cycles?.some(c => c.status === "running" || c.status === "queued");
  const toggleExpand = (id) => setExpanded(prev => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="border-b border-slate-800/60">
      {/* Header with trigger button */}
      <div className="px-4 py-2 flex items-center gap-2 border-b border-slate-800/30">
        <Activity size={13} className="text-slate-500" />
        <span className="text-[11px] font-medium text-slate-400 flex-1">Evolve Cycles</span>
        {!hasRunning && (
          <button
            onClick={() => { setShowTrigger(!showTrigger); loadCycleTypes(); }}
            className="text-[11px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center gap-1"
          >
            <Play size={10} /> Run Cycle
          </button>
        )}
        {hasRunning && (
          <span className="text-[10px] text-cyan-500 flex items-center gap-1">
            <Loader2 size={10} className="animate-spin" /> Running
          </span>
        )}
      </div>

      {/* Trigger panel */}
      {showTrigger && !hasRunning && (
        <div className="px-4 py-3 bg-slate-900/60 border-b border-slate-800/30 max-h-[60vh] overflow-y-auto">
          {triggerError && (
            <div className="mb-2 px-2 py-1.5 rounded bg-red-900/30 border border-red-800/40 text-[11px] text-red-300 flex items-center justify-between">
              <span>{triggerError}</span>
              <button onClick={() => setTriggerError(null)} className="ml-2 hover:text-white"><X size={12} /></button>
            </div>
          )}
          {!cycleTypes && (
            <div className="text-[11px] text-slate-500 flex items-center gap-1">
              <Loader2 size={10} className="animate-spin" /> Loading cycle types...
            </div>
          )}
          {cycleTypes && (
            <div className="space-y-1.5">
              {cycleTypes.map(ct => {
                const typeInfo = CYCLE_TYPE_LABELS[ct.type] || CYCLE_TYPE_LABELS.unknown;
                const TypeIcon = typeInfo.icon;
                return (
                  <button
                    key={ct.type}
                    onClick={() => triggerCycle(ct.type)}
                    disabled={triggering}
                    className={`w-full text-left px-3 py-2 rounded-md border ${typeInfo.border} ${typeInfo.bg} hover:brightness-125 transition-all disabled:opacity-50 flex items-start gap-2`}
                  >
                    <TypeIcon size={14} className={`${typeInfo.color} mt-0.5 shrink-0`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold ${typeInfo.color}`}>{typeInfo.label}</span>
                        <span className="text-[10px] text-slate-600">{ct.phase_count} phases</span>
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5">{ct.description}</div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {ct.phases.map((p, i) => (
                          <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-500">
                            {p.name}
                          </span>
                        ))}
                      </div>
                    </div>
                    {triggering && <Loader2 size={12} className="animate-spin text-slate-400 shrink-0 mt-0.5" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Cycle list */}
      {cycles && cycles.map(cycle => {
        const typeInfo = CYCLE_TYPE_LABELS[cycle.cycle_type] || CYCLE_TYPE_LABELS.unknown;
        const TypeIcon = typeInfo.icon;
        const isExpanded = expanded[cycle.id];
        const isActive = cycle.status === "running" || cycle.status === "queued";
        const totalUnits = cycle.phases.reduce((s, p) => s + p.total_units, 0);
        const doneUnits = cycle.phases.reduce((s, p) => s + p.units_completed + p.units_failed, 0);
        const overallPct = totalUnits > 0 ? Math.round(doneUnits / totalUnits * 100) : 0;

        return (
          <div key={cycle.id} className={`${isActive ? typeInfo.bg : "bg-slate-900/30"}`}>
            {/* Cycle header */}
            <button
              onClick={() => toggleExpand(cycle.id)}
              className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-white/5 transition-colors"
            >
              <TypeIcon size={14} className={isActive ? typeInfo.color + " animate-pulse" : "text-slate-500"} />
              <span className={`text-xs font-semibold ${isActive ? typeInfo.color : "text-slate-400"}`}>
                {typeInfo.label}
              </span>
              <span className="text-[10px] text-slate-600">
                {cycle.phases_done}/{cycle.total_phases} phases
              </span>
              {isActive && (
                <span className="text-[10px] text-slate-500 ml-1">
                  {totalUnits > 0 ? `${doneUnits}/${totalUnits} units (${overallPct}%)` : "starting..."}
                </span>
              )}
              {!isActive && cycle.status === "completed" && (
                <span className="text-[10px] text-emerald-600">{totalUnits} units</span>
              )}
              {cycle.status === "completed" && <CheckCircle2 size={12} className="text-emerald-600" />}
              {cycle.status === "failed" && <AlertTriangle size={12} className="text-red-500" />}
              <span className="text-[10px] text-slate-600 ml-auto">
                {cycle.created_at ? new Date(cycle.created_at).toLocaleDateString() : ""}
              </span>
              {isExpanded ? <ChevronUp size={12} className="text-slate-600" /> : <ChevronDown size={12} className="text-slate-600" />}
            </button>

            {/* Overall progress bar (compact, always visible for active) */}
            {isActive && !isExpanded && totalUnits > 0 && (
              <div className="px-4 pb-2">
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-500 rounded-full"
                    style={{ width: `${overallPct}%` }}
                  />
                </div>
              </div>
            )}

            {/* Expanded phase list */}
            {isExpanded && (
              <div className="px-4 pb-3 space-y-1.5">
                {cycle.phases.map(phase => (
                  <PhaseCard
                    key={phase.id}
                    phase={phase}
                    isPhaseExpanded={!!phaseExpanded[phase.id]}
                    onToggle={() => togglePhase(phase.id)}
                    units={unitData[phase.id]}
                  />
                ))}

                {/* Timing info */}
                <div className="flex items-center gap-3 text-[10px] text-slate-600 pt-1 px-1">
                  {cycle.started_at && (
                    <span>Started {new Date(cycle.started_at).toLocaleTimeString()}</span>
                  )}
                  {cycle.completed_at && (
                    <span>Finished {new Date(cycle.completed_at).toLocaleTimeString()}</span>
                  )}
                  {isActive && cycle.started_at && !cycle.completed_at && (
                    <span>
                      Elapsed: <ElapsedTime since={cycle.started_at} />
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const FINDING_IMPACT = {
  high: "bg-red-900/40 text-red-300 border-red-800/40",
  medium: "bg-amber-900/40 text-amber-300 border-amber-800/40",
  low: "bg-slate-800/40 text-slate-400 border-slate-700/40",
};

function PhaseCard({ phase, isPhaseExpanded, onToggle, units }) {
  const pStyle = PHASE_STATUS_STYLES[phase.status] || PHASE_STATUS_STYLES.queued;
  const PIcon = pStyle.icon;
  const phasePct = phase.total_units > 0
    ? Math.round((phase.units_completed + phase.units_failed) / phase.total_units * 100)
    : (phase.status === "completed" ? 100 : 0);
  const hasSynthesis = phase.synthesis_findings && phase.synthesis_findings.length > 0;
  const canExpand = phase.status !== "queued" || phase.total_units > 0;

  return (
    <div className="rounded-md bg-slate-900/60 border border-slate-800/50 overflow-hidden">
      {/* Phase header — clickable to expand */}
      <button
        onClick={canExpand ? onToggle : undefined}
        className={`w-full px-3 py-2 flex items-center gap-2 ${canExpand ? "hover:bg-white/5 cursor-pointer" : "cursor-default"}`}
      >
        <PIcon size={12} className={`${pStyle.text} ${phase.status === "running" ? "animate-pulse" : ""}`} />
        <span className={`text-xs font-medium ${pStyle.text} flex-1 text-left`}>
          {phase.name}
        </span>
        {hasSynthesis && !isPhaseExpanded && (
          <span className="text-[10px] text-slate-500">
            {phase.synthesis_findings.length} findings
          </span>
        )}
        {phase.total_units > 0 && (
          <span className="text-[10px] text-slate-500">
            {phase.units_completed}{phase.units_failed > 0 ? `+${phase.units_failed}err` : ""}/{phase.total_units}
          </span>
        )}
        {phase.status === "running" && phase.units_running > 0 && (
          <span className="text-[10px] text-cyan-500">
            {phase.units_running} running
          </span>
        )}
        {canExpand && (
          isPhaseExpanded
            ? <ChevronUp size={10} className="text-slate-600" />
            : <ChevronDown size={10} className="text-slate-600" />
        )}
      </button>

      {/* Phase progress bar */}
      {phase.total_units > 0 && !isPhaseExpanded && (
        <div className="px-3 pb-2">
          <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full ${pStyle.barBg} transition-all duration-500 rounded-full`}
              style={{ width: `${phasePct}%` }}
            />
          </div>
        </div>
      )}

      {phase.status === "queued" && phase.total_units === 0 && !isPhaseExpanded && (
        <div className="px-3 pb-2 text-[10px] text-slate-600 italic">Waiting...</div>
      )}

      {/* Expanded: synthesis findings + unit drill-down */}
      {isPhaseExpanded && (
        <div className="border-t border-slate-800/50">
          {/* Synthesis findings summary */}
          {hasSynthesis && (
            <div className="px-3 py-2 space-y-1">
              <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider mb-1">
                Synthesis Findings
              </div>
              {phase.synthesis_findings.map((f, i) => (
                <div key={i} className={`px-2 py-1 rounded text-[11px] border ${FINDING_IMPACT[f.impact] || FINDING_IMPACT.low}`}>
                  <span>{f.title}</span>
                  {f.impact && (
                    <span className="ml-1.5 opacity-60 text-[9px] uppercase">{f.impact}</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Unit-level drill-down */}
          {units && units.length > 0 && (
            <div className="px-3 py-2 border-t border-slate-800/40 space-y-1">
              <div className="text-[10px] text-slate-500 font-medium uppercase tracking-wider mb-1">
                Units ({units.length})
              </div>
              {units.map(unit => (
                <UnitRow key={unit.id} unit={unit} />
              ))}
            </div>
          )}
          {units && units.length === 0 && (
            <div className="px-3 py-2 text-[10px] text-slate-600 italic">No units created</div>
          )}
          {!units && canExpand && (
            <div className="px-3 py-2 text-[10px] text-slate-500 flex items-center gap-1">
              <Loader2 size={10} className="animate-spin" /> Loading units...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function UnitRow({ unit }) {
  const [showFindings, setShowFindings] = useState(false);
  const statusIcon = {
    completed: <CheckCircle2 size={10} className="text-emerald-500" />,
    running: <Loader2 size={10} className="text-cyan-400 animate-spin" />,
    queued: <Clock size={10} className="text-slate-600" />,
    failed: <AlertTriangle size={10} className="text-red-500" />,
  };
  const hasFindings = unit.findings && unit.findings.length > 0;

  return (
    <div className="rounded bg-slate-900/40 border border-slate-800/30">
      <button
        onClick={() => hasFindings && setShowFindings(!showFindings)}
        className={`w-full px-2 py-1.5 flex items-center gap-1.5 text-left ${hasFindings ? "hover:bg-white/5 cursor-pointer" : "cursor-default"}`}
      >
        {statusIcon[unit.status] || statusIcon.queued}
        <span className="text-[11px] text-slate-300 flex-1 truncate">{unit.name}</span>
        {unit.is_synthesis && (
          <span className="text-[9px] px-1 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-800/40">
            synthesis
          </span>
        )}
        {hasFindings && (
          <span className="text-[10px] text-slate-500">{unit.findings.length}</span>
        )}
        {unit.error && (
          <span className="text-[10px] text-red-400 truncate max-w-[120px]">{unit.error}</span>
        )}
        {unit.tokens_used > 0 && (
          <span className="text-[9px] text-slate-600">{(unit.tokens_used / 1000).toFixed(1)}k tok</span>
        )}
        {hasFindings && (
          showFindings
            ? <ChevronUp size={9} className="text-slate-600" />
            : <ChevronDown size={9} className="text-slate-600" />
        )}
      </button>

      {showFindings && (
        <div className="px-2 pb-2 space-y-1 border-t border-slate-800/30">
          {unit.findings.map((f, i) => (
            <div key={i} className="px-2 py-1.5 rounded bg-slate-800/30 text-[11px]">
              <div className="text-slate-300 font-medium">{f.title}</div>
              {f.summary && (
                <div className="text-slate-500 mt-0.5 line-clamp-2">{f.summary}</div>
              )}
              <div className="flex items-center gap-2 mt-0.5">
                {f.impact && (
                  <span className={`text-[9px] ${IMPACT_COLORS[f.impact] || "text-slate-500"}`}>
                    {f.impact}
                  </span>
                )}
                {f.category && <span className="text-[9px] text-slate-600">{f.category}</span>}
                {f.action && <span className="text-[9px] text-blue-400">{f.action}</span>}
              </div>
            </div>
          ))}
          {unit.response_preview && (
            <details className="text-[10px] text-slate-600">
              <summary className="cursor-pointer hover:text-slate-400">Raw response preview</summary>
              <pre className="mt-1 p-2 bg-slate-900 rounded text-[10px] whitespace-pre-wrap overflow-x-auto max-h-40 overflow-y-auto">
                {unit.response_preview}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function ElapsedTime({ since }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const secs = Math.floor((Date.now() - new Date(since).getTime()) / 1000);
  const mins = Math.floor(secs / 60);
  const hrs = Math.floor(mins / 60);
  if (hrs > 0) return `${hrs}h ${mins % 60}m`;
  if (mins > 0) return `${mins}m ${secs % 60}s`;
  return `${secs}s`;
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  Dashboard View                                                            */
/* ═══════════════════════════════════════════════════════════════════════════ */

function DashboardView({ stats, onBack, onRefresh }) {
  if (!stats) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={20} className="animate-spin mr-2" /> Loading stats...
      </div>
    );
  }

  const statCards = [
    { label: "New", value: stats.new || 0, color: "text-blue-400", bg: "bg-blue-900/20" },
    { label: "Approved", value: stats.approved || 0, color: "text-emerald-400", bg: "bg-emerald-900/20" },
    { label: "In Progress", value: stats.in_progress || 0, color: "text-cyan-400", bg: "bg-cyan-900/20" },
    { label: "Completed", value: stats.completed || 0, color: "text-emerald-600", bg: "bg-emerald-900/10" },
    { label: "Deferred", value: stats.deferred || 0, color: "text-slate-400", bg: "bg-slate-800/40" },
    { label: "Total", value: stats.total || 0, color: "text-slate-300", bg: "bg-slate-800/30" },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800/60">
        <button onClick={onBack} className="p-1 rounded hover:bg-slate-800 text-slate-400">
          <ChevronLeft size={16} />
        </button>
        <BarChart3 size={16} className="text-amber-400" />
        <span className="font-semibold text-sm">Evolution Dashboard</span>
        <button onClick={onRefresh} className="ml-auto p-1 rounded hover:bg-slate-800 text-slate-400">
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {statCards.map(card => (
            <div key={card.label} className={`rounded-lg p-4 ${card.bg} border border-slate-800/40`}>
              <div className={`text-2xl font-bold ${card.color}`}>{card.value}</div>
              <div className="text-xs text-slate-500 mt-1">{card.label}</div>
            </div>
          ))}
        </div>

        <div className="mt-6 text-xs text-slate-500">
          <p>Active items: {stats.active || 0} (items not completed/dismissed/rejected)</p>
          <p className="mt-1">The Evolve domain runs weekly deep cycles (hundreds of LLM calls) to analyze Skipper's capabilities and produce these items.</p>
        </div>
      </div>
    </div>
  );
}
