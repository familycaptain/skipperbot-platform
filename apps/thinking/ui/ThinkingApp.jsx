import { useState, useEffect, useCallback } from "react";
import {
  Brain, Activity, Zap, Clock, Eye, StickyNote, Target, AlertTriangle,
  CheckCircle2, XCircle, ChevronDown, ChevronRight, RefreshCw, Filter,
  Cpu, DollarSign, Timer, Loader2, Pause, Play,
} from "lucide-react";

const API = "";

// ── Helpers ──

function fmtTime(v) {
  if (!v) return "—";
  try {
    const d = new Date(v);
    return d.toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch { return String(v); }
}

function fmtTimeShort(v) {
  if (!v) return "—";
  try {
    const d = new Date(v);
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch { return String(v); }
}

function relativeTime(v) {
  if (!v) return "";
  try {
    const d = new Date(v);
    const now = new Date();
    const diffMs = now - d;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch { return ""; }
}

// ── Badges ──

const STATE_TYPE_META = {
  focus:            { icon: Target,         color: "text-blue-400",    bg: "bg-blue-500/10",    border: "border-blue-700/50",    label: "Focus" },
  working_memory:   { icon: Brain,          color: "text-purple-400",  bg: "bg-purple-500/10",  border: "border-purple-700/50",  label: "Memory" },
  pending_action:   { icon: Clock,          color: "text-amber-400",   bg: "bg-amber-500/10",   border: "border-amber-700/50",   label: "Pending" },
  observation:      { icon: Eye,            color: "text-cyan-400",    bg: "bg-cyan-500/10",    border: "border-cyan-700/50",    label: "Observation" },
  note:             { icon: StickyNote,     color: "text-slate-400",   bg: "bg-slate-500/10",   border: "border-slate-600/50",   label: "Note" },
  process_position: { icon: Activity,       color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-700/50", label: "Process" },
};

const STATUS_META = {
  active:   { color: "text-emerald-400 bg-emerald-900/30 border-emerald-700/40", icon: Play },
  resolved: { color: "text-slate-400 bg-slate-800/30 border-slate-600/40",       icon: CheckCircle2 },
  deferred: { color: "text-yellow-400 bg-yellow-900/30 border-yellow-700/40",    icon: Pause },
  expired:  { color: "text-red-400 bg-red-900/30 border-red-700/40",             icon: XCircle },
};

const DOMAIN_COLORS = {
  pm:         "text-blue-300 bg-blue-900/40 border-blue-700/40",
  investment: "text-emerald-300 bg-emerald-900/40 border-emerald-700/40",
  general:    "text-slate-300 bg-slate-800/40 border-slate-600/40",
};

const PRIORITY_DOT = {
  high:   "bg-red-400",
  medium: "bg-amber-400",
  low:    "bg-slate-500",
};

const TRIGGER_META = {
  timer: { icon: Timer, color: "text-slate-400 bg-slate-800/40" },
  event: { icon: Zap,   color: "text-yellow-400 bg-yellow-900/40" },
  self:  { icon: Brain, color: "text-purple-400 bg-purple-900/40" },
  user:  { icon: Activity, color: "text-blue-400 bg-blue-900/40" },
};

const MODEL_META = {
  skip:      { color: "text-slate-500 bg-slate-800/30", label: "Skip" },
  cheap:     { color: "text-green-400 bg-green-900/30", label: "Cheap" },
  standard:  { color: "text-blue-400 bg-blue-900/30",   label: "Standard" },
  expensive: { color: "text-amber-400 bg-amber-900/30", label: "Expensive" },
};

function DomainBadge({ domain }) {
  const c = DOMAIN_COLORS[domain] || DOMAIN_COLORS.general;
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded border ${c}`}>
      {domain}
    </span>
  );
}

function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.active;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded border ${m.color}`}>
      <Icon size={9} /> {status}
    </span>
  );
}

function TypeBadge({ stateType }) {
  const m = STATE_TYPE_META[stateType] || STATE_TYPE_META.note;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded ${m.bg} ${m.color}`}>
      <Icon size={10} /> {m.label}
    </span>
  );
}

function PriorityDot({ priority }) {
  if (!priority) return null;
  const c = PRIORITY_DOT[priority] || PRIORITY_DOT.low;
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${c}`} title={priority} />;
}

function TriggerBadge({ trigger }) {
  const m = TRIGGER_META[trigger] || TRIGGER_META.timer;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded ${m.color}`}>
      <Icon size={9} /> {trigger}
    </span>
  );
}

function ModelBadge({ model }) {
  const m = MODEL_META[model] || MODEL_META.skip;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded ${m.color}`}>
      <Cpu size={9} /> {m.label}
    </span>
  );
}

// ── Budget Bar ──

function BudgetBar({ budget }) {
  if (!budget) return null;
  const pct = budget.usage_pct || 0;
  const barColor = pct > 90 ? "bg-red-500" : pct > 70 ? "bg-amber-500" : "bg-emerald-500";
  const byDomainRaw = budget.by_domain || [];
  // Aggregate all g-* domains into a single "goals" entry
  const byDomain = (() => {
    const goalTokens = { domain: "goals", total_tokens: 0, cycle_count: 0 };
    const rest = [];
    for (const d of byDomainRaw) {
      if (d.domain.startsWith("g-")) {
        goalTokens.total_tokens += d.total_tokens || 0;
        goalTokens.cycle_count += d.cycle_count || 0;
      } else {
        rest.push(d);
      }
    }
    if (goalTokens.total_tokens > 0 || goalTokens.cycle_count > 0) rest.push(goalTokens);
    return rest;
  })();
  return (
    <div className="px-3 py-2 bg-slate-800/50 border-b border-slate-700/50">
      <div className="flex items-center gap-3">
        <DollarSign size={12} className="text-slate-400" />
        <div className="flex-1">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[10px] text-slate-400">
              Today: {(budget.total_tokens || 0).toLocaleString()} / {(budget.budget || 0).toLocaleString()} tokens
              {budget.daily_cost_usd != null && (
                <span className="ml-2 text-emerald-400 font-medium">${Number(budget.daily_cost_usd).toFixed(2)}</span>
              )}
            </span>
            <span className="text-[10px] text-slate-500">
              {budget.cycle_count || 0} cycles
            </span>
          </div>
          <div className="w-full bg-slate-700 rounded-full h-1">
            <div className={`${barColor} h-1 rounded-full transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
        </div>
        <span className="text-[10px] font-mono text-slate-400">{pct.toFixed(1)}%</span>
      </div>
      {byDomain.length > 0 && (
        <div className="flex gap-3 mt-1.5 ml-6">
          {byDomain.map(d => (
            <span key={d.domain} className="text-[10px] text-slate-500">
              <DomainBadge domain={d.domain} />
              {" "}{(d.total_tokens || 0).toLocaleString()}
              <span className="text-slate-600 ml-0.5">({d.cycle_count}c)</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── State Card ──

function StateCard({ state }) {
  const [expanded, setExpanded] = useState(false);
  const m = STATE_TYPE_META[state.state_type] || STATE_TYPE_META.note;

  let contentDisplay = state.content || "";
  let parsed = null;
  try { parsed = JSON.parse(contentDisplay); } catch {}

  const isResolved = state.status === "resolved" || state.status === "expired";

  return (
    <div className={`border-b border-slate-700/30 ${isResolved ? "opacity-50" : ""}`}>
      <button
        className="w-full px-3 py-2 text-left hover:bg-slate-800/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <PriorityDot priority={state.priority} />
          <TypeBadge stateType={state.state_type} />
          <DomainBadge domain={state.domain} />
          <StatusBadge status={state.status} />
          <span className="flex-1" />
          <span className="text-[10px] text-slate-500" title={state.updated_at || state.created_at}>
            {relativeTime(state.updated_at || state.created_at)}
          </span>
          {expanded ? <ChevronDown size={12} className="text-slate-500" /> : <ChevronRight size={12} className="text-slate-500" />}
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="text-xs text-slate-300 truncate">
            {parsed?.entity_name || parsed?.summary || (contentDisplay.length > 120 ? contentDisplay.slice(0, 120) + "..." : contentDisplay)}
          </span>
        </div>
        {state.subject_id && (
          <span className="text-[10px] text-slate-500 font-mono">{state.subject_id}</span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {state.due_at && (
            <div className="flex items-center gap-1 text-[10px]">
              <Clock size={9} className="text-amber-400" />
              <span className="text-amber-300">Due: {fmtTime(state.due_at)}</span>
            </div>
          )}
          {state.resolved_at && (
            <div className="flex items-center gap-1 text-[10px]">
              <CheckCircle2 size={9} className="text-slate-400" />
              <span className="text-slate-400">Resolved: {fmtTime(state.resolved_at)}</span>
            </div>
          )}
          <div className="text-[11px] text-slate-300 bg-slate-800/50 rounded p-2 font-mono whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
            {parsed ? JSON.stringify(parsed, null, 2) : contentDisplay}
          </div>
          <div className="text-[10px] text-slate-500">
            ID: {state.id} &middot; Created: {fmtTime(state.created_at)}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Log Entry Card ──

function LogCard({ entry }) {
  const [expanded, setExpanded] = useState(false);
  const actions = entry.actions_taken || [];
  const hasContent = entry.reasoning || actions.length > 0;

  return (
    <div className="border-b border-slate-700/30 overflow-hidden">
      <button
        className="w-full px-3 py-2 text-left hover:bg-slate-800/30 transition-colors overflow-hidden"
        onClick={() => hasContent && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] text-slate-400 font-mono w-16 shrink-0">
            {fmtTimeShort(entry.cycle_at)}
          </span>
          <DomainBadge domain={entry.domain} />
          <TriggerBadge trigger={entry.trigger} />
          <ModelBadge model={entry.model_used} />
          {entry.tokens_used > 0 && (
            <span className="text-[10px] text-slate-500">{entry.tokens_used.toLocaleString()} tok</span>
          )}
          <span className="flex-1" />
          {actions.length > 0 && (
            <span className="text-[10px] text-emerald-400">{actions.length} action{actions.length !== 1 ? "s" : ""}</span>
          )}
          {hasContent && (expanded ? <ChevronDown size={12} className="text-slate-500" /> : <ChevronRight size={12} className="text-slate-500" />)}
        </div>
        {entry.input_summary && (
          <p className={`mt-0.5 text-xs text-slate-400 pl-[72px] ${expanded ? "whitespace-pre-wrap break-words" : "truncate"}`}>{entry.input_summary}</p>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 pl-[72px] space-y-2">
          {entry.reasoning && (
            <div>
              <span className="text-[10px] text-slate-500 font-medium">Reasoning</span>
              <div className="text-[11px] text-slate-300 bg-slate-800/50 rounded p-2 whitespace-pre-wrap max-h-48 overflow-y-auto">
                {entry.reasoning}
              </div>
            </div>
          )}
          {actions.length > 0 && (
            <div>
              <span className="text-[10px] text-slate-500 font-medium">Actions</span>
              <div className="space-y-0.5">
                {actions.map((a, i) => (
                  <div key={i} className="text-[11px] text-slate-300 bg-slate-800/50 rounded px-2 py-1 font-mono">
                    {a.type}: {a.detail || a.state_id || a.entity_id || JSON.stringify(a)}
                  </div>
                ))}
              </div>
            </div>
          )}
          {entry.context_snapshot && (
            <details className="text-[10px]">
              <summary className="text-slate-500 cursor-pointer hover:text-slate-300">Context snapshot</summary>
              <pre className="text-slate-400 bg-slate-900/50 rounded p-2 mt-1 overflow-x-auto max-h-48 overflow-y-auto">
                {JSON.stringify(entry.context_snapshot, null, 2)}
              </pre>
            </details>
          )}
          <div className="text-[10px] text-slate-500">ID: {entry.id}</div>
        </div>
      )}
    </div>
  );
}

// ── Domain Card ──

function DomainCard({ domain, onToggle }) {
  const [toggling, setToggling] = useState(false);
  const cadence = domain.cadence || {};
  const hours = cadence.active_hours || [];
  const isChat = domain.name === "chat";

  async function handleToggle() {
    setToggling(true);
    try {
      await fetch(`${API}/api/apps/thinking/domains/${domain.name}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !domain.enabled }),
      });
      if (onToggle) onToggle();
    } catch (e) { console.error("Toggle domain error:", e); }
    setToggling(false);
  }

  return (
    <div className={`px-3 py-2 border-b border-slate-700/30 ${!domain.enabled ? "opacity-60" : ""}`}>
      <div className="flex items-center gap-2">
        <DomainBadge domain={domain.name} />
        {isChat ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded text-emerald-400 bg-emerald-900/30">
            <Play size={9} /> Always On
          </span>
        ) : (
          <button
            onClick={handleToggle}
            disabled={toggling}
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded cursor-pointer transition-colors ${
              domain.enabled
                ? "text-emerald-400 bg-emerald-900/30 hover:bg-emerald-900/50"
                : "text-red-400 bg-red-900/30 hover:bg-red-900/50"
            }`}
            title={domain.enabled ? "Click to disable" : "Click to enable"}
          >
            {toggling ? <Loader2 size={9} className="animate-spin" /> : domain.enabled ? <Play size={9} /> : <Pause size={9} />}
            {domain.enabled ? "Enabled" : "Disabled"}
          </button>
        )}
        <span className={`px-1.5 py-0.5 text-[10px] rounded ${
          domain.budget_priority === "critical" ? "text-red-300 bg-red-900/30" :
          domain.budget_priority === "low" ? "text-slate-400 bg-slate-800/30" :
          "text-blue-300 bg-blue-900/30"
        }`}>
          {domain.budget_priority}
        </span>
      </div>
      <p className="text-xs text-slate-400 mt-1">{domain.description}</p>
      <div className="flex gap-3 mt-1 text-[10px] text-slate-500">
        {hours.length >= 2 && <span>Hours: {hours[0]}:00–{hours[1]}:00</span>}
        {cadence.interval_minutes && <span>Interval: {cadence.interval_minutes}m</span>}
      </div>
      {!isChat && domain.observe_tool !== "n/a" && (
        <div className="flex gap-2 mt-1 text-[10px] text-slate-500 font-mono">
          <span>{domain.observe_tool}</span>
          <span>{domain.evaluate_tool}</span>
          <span>{domain.act_tool}</span>
        </div>
      )}
      {isChat && (
        <div className="mt-1 text-[10px] text-slate-500">
          Event-driven — dispatched immediately on user message
        </div>
      )}
    </div>
  );
}

// ── Main App ──

export default function ThinkingApp({ userId, context, refreshKey }) {
  const [tab, setTab] = useState("mind"); // mind | log | domains
  const [loading, setLoading] = useState(false);

  // Mind tab state
  const [states, setStates] = useState([]);
  const [domainFilter, setDomainFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");

  // Log tab state
  const [logs, setLogs] = useState([]);
  const [logDomain, setLogDomain] = useState("");
  const [logDays, setLogDays] = useState(1);

  // Domains tab
  const [domains, setDomains] = useState([]);

  // Budget
  const [budget, setBudget] = useState(null);

  // ── Loaders ──

  const loadStates = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (domainFilter) params.set("domain", domainFilter);
      if (typeFilter) params.set("state_type", typeFilter);
      if (statusFilter) params.set("status", statusFilter);
      params.set("limit", "100");
      const res = await fetch(`${API}/api/apps/thinking/state?${params}`);
      const data = await res.json();
      setStates(data.states || []);
    } catch (e) { console.error("ThinkingApp state load error:", e); }
    setLoading(false);
  }, [domainFilter, typeFilter, statusFilter]);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (logDomain) params.set("domain", logDomain);
      params.set("days", String(logDays));
      params.set("limit", "100");
      const res = await fetch(`${API}/api/apps/thinking/log?${params}`);
      const data = await res.json();
      setLogs(data.entries || []);
    } catch (e) { console.error("ThinkingApp log load error:", e); }
    setLoading(false);
  }, [logDomain, logDays]);

  const loadDomains = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/apps/thinking/domains?enabled_only=false`);
      const data = await res.json();
      setDomains(data.domains || []);
    } catch (e) { console.error("ThinkingApp domains load error:", e); }
  }, []);

  const loadBudget = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/apps/thinking/budget`);
      const data = await res.json();
      setBudget(data);
    } catch {}
  }, []);

  // Load on tab change
  useEffect(() => {
    loadBudget();
    loadDomains();
    if (tab === "mind") loadStates();
    else if (tab === "log") loadLogs();
  }, [tab, loadStates, loadLogs, loadDomains, loadBudget]);

  // Refresh
  useEffect(() => {
    if (refreshKey) {
      loadBudget();
      if (tab === "mind") loadStates();
      else if (tab === "log") loadLogs();
    }
  }, [refreshKey]);

  // Auto-poll every 30s
  useEffect(() => {
    const iv = setInterval(() => {
      loadBudget();
      if (tab === "mind") loadStates();
      else if (tab === "log") loadLogs();
    }, 30000);
    return () => clearInterval(iv);
  }, [tab, loadStates, loadLogs, loadBudget]);

  // ── Group states by type ──
  const stateGroups = {};
  const groupOrder = ["focus", "pending_action", "working_memory", "observation", "note", "process_position"];
  for (const s of states) {
    const t = s.state_type || "note";
    if (!stateGroups[t]) stateGroups[t] = [];
    stateGroups[t].push(s);
  }

  function handleRefresh() {
    loadBudget();
    if (tab === "mind") loadStates();
    else if (tab === "log") loadLogs();
    else if (tab === "domains") loadDomains();
  }

  return (
    <div className="flex flex-col h-full w-full min-w-0 overflow-hidden bg-slate-900 text-white">
      {/* Budget bar */}
      <BudgetBar budget={budget} />

      {/* Tab bar + filters */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-700/50 bg-slate-800/30">
        {[
          { id: "mind", label: "Mind", icon: Brain },
          { id: "log", label: "Log", icon: Activity },
          { id: "domains", label: "Domains", icon: Cpu },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded transition-colors ${
              tab === t.id ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            <t.icon size={12} /> {t.label}
          </button>
        ))}

        <span className="flex-1" />

        {/* Filters for Mind tab */}
        {tab === "mind" && (
          <div className="flex items-center gap-1.5">
            <select
              value={domainFilter}
              onChange={e => setDomainFilter(e.target.value)}
              className="text-[10px] bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
            >
              <option value="">All domains</option>
              <option value="pm">PM</option>
              <option value="general">General</option>
            </select>
            <select
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value)}
              className="text-[10px] bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
            >
              <option value="">All types</option>
              <option value="focus">Focus</option>
              <option value="working_memory">Memory</option>
              <option value="pending_action">Pending</option>
              <option value="observation">Observation</option>
              <option value="note">Note</option>
              <option value="process_position">Process</option>
            </select>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="text-[10px] bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
            >
              <option value="active">Active</option>
              <option value="">All</option>
              <option value="resolved">Resolved</option>
              <option value="expired">Expired</option>
            </select>
          </div>
        )}

        {/* Filters for Log tab */}
        {tab === "log" && (
          <div className="flex items-center gap-1.5">
            <select
              value={logDomain}
              onChange={e => setLogDomain(e.target.value)}
              className="text-[10px] bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
            >
              <option value="">All domains</option>
              {domains.map(d => (
                <option key={d.name} value={d.name}>{d.name}</option>
              ))}
            </select>
            <select
              value={logDays}
              onChange={e => setLogDays(Number(e.target.value))}
              className="text-[10px] bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
            >
              <option value={1}>Today</option>
              <option value={3}>3 days</option>
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
            </select>
          </div>
        )}

        <button
          onClick={handleRefresh}
          className="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {loading && states.length === 0 && logs.length === 0 && (
          <div className="flex items-center justify-center py-12 text-slate-500">
            <Loader2 size={16} className="animate-spin mr-2" /> Loading...
          </div>
        )}

        {/* ── Mind tab ── */}
        {tab === "mind" && (
          <div>
            {states.length === 0 && !loading && (
              <div className="text-center py-12 text-slate-500 text-sm">
                <Brain size={24} className="mx-auto mb-2 opacity-40" />
                No state entries found.
                <p className="text-[10px] mt-1">Skipper's mind is empty — the thinking loop hasn't produced any state yet.</p>
              </div>
            )}
            {groupOrder.map(type => {
              const group = stateGroups[type];
              if (!group || group.length === 0) return null;
              const meta = STATE_TYPE_META[type] || STATE_TYPE_META.note;
              const Icon = meta.icon;
              return (
                <div key={type}>
                  <div className={`sticky top-0 z-10 flex items-center gap-2 px-3 py-1.5 text-xs font-medium border-b border-slate-700/30 bg-slate-900/95 backdrop-blur ${meta.color}`}>
                    <Icon size={12} />
                    {meta.label}
                    <span className="text-slate-500 font-normal">({group.length})</span>
                  </div>
                  {group.map(s => <StateCard key={s.id} state={s} />)}
                </div>
              );
            })}
            {/* Any types not in groupOrder */}
            {Object.keys(stateGroups).filter(t => !groupOrder.includes(t)).map(type => {
              const group = stateGroups[type];
              return (
                <div key={type}>
                  <div className="sticky top-0 z-10 flex items-center gap-2 px-3 py-1.5 text-xs font-medium border-b border-slate-700/30 bg-slate-900/95 backdrop-blur text-slate-400">
                    {type} ({group.length})
                  </div>
                  {group.map(s => <StateCard key={s.id} state={s} />)}
                </div>
              );
            })}
          </div>
        )}

        {/* ── Log tab ── */}
        {tab === "log" && (
          <div>
            {logs.length === 0 && !loading && (
              <div className="text-center py-12 text-slate-500 text-sm">
                <Activity size={24} className="mx-auto mb-2 opacity-40" />
                No thinking cycles logged yet.
                <p className="text-[10px] mt-1">The thinking scheduler will log cycles as they run.</p>
              </div>
            )}
            {logs.map(entry => <LogCard key={entry.id} entry={entry} />)}
          </div>
        )}

        {/* ── Domains tab ── */}
        {tab === "domains" && (
          <div>
            {domains.length === 0 && !loading && (
              <div className="text-center py-12 text-slate-500 text-sm">
                No domains configured.
              </div>
            )}
            {domains.map(d => <DomainCard key={d.name} domain={d} onToggle={loadDomains} />)}
          </div>
        )}
      </div>
    </div>
  );
}
