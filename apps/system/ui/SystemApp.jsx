import { useState, useEffect, useCallback } from "react";
import {
  Server, Database, RefreshCw, Loader2, Activity,
  Brain, FileText, Bell, MessageSquare, List,
  HardDrive, Briefcase,
  Link, Image, Target, FolderKanban, CheckSquare, Clock,
  RotateCcw, BookOpen, Inbox, Sparkles,
} from "lucide-react";

const API = "";

function fmtNum(n) {
  if (n == null) return "—";
  return n.toLocaleString();
}

function fmtDuration(secs) {
  if (!secs) return "—";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch { return iso; }
}

function StatCard({ icon: Icon, label, value, sub, color = "text-default" }) {
  return (
    <div className="surface-card rounded-lg border border-subtle p-3 flex items-center gap-3">
      <div className={`p-2 rounded-lg surface-raised ${color}`}>
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-semibold text-default">{value}</div>
        <div className="text-[10px] text-faint truncate">{label}</div>
        {sub && <div className="text-[10px] text-faint">{sub}</div>}
      </div>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, color = "text-muted" }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <Icon size={14} className={color} />
      <h3 className={`text-xs font-semibold uppercase tracking-wide ${color}`}>{title}</h3>
    </div>
  );
}

function StatusBadge({ status }) {
  if (!status) return null;
  const styles = {
    completed: "bg-emerald-900/30 text-emerald-400 border-emerald-800",
    running: "surface-card text-accent border-subtle",
    failed: "bg-red-900/30 text-red-400 border-red-800",
    queued: "bg-amber-900/30 text-amber-400 border-amber-800",
  };
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${styles[status] || "surface-card text-faint border-subtle"}`}>
      {status}
    </span>
  );
}

export default function SystemApp({ appId, userId, isActive }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [agentStatus, setAgentStatus] = useState(null);
  const [restarting, setRestarting] = useState(false);
  const [confirmRestart, setConfirmRestart] = useState(false);

  const loadData = useCallback(async (showRefresh) => {
    if (showRefresh) setRefreshing(true);
    try {
      const res = await fetch(`${API}/api/apps/system/metrics`);
      if (res.ok) setData(await res.json());
    } catch (e) {
      console.error("Failed to load system metrics:", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadAgentStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/admin/status`);
      if (res.ok) setAgentStatus(await res.json());
    } catch {}
  }, []);

  async function handleRestart() {
    setRestarting(true);
    setConfirmRestart(false);
    try {
      await fetch(`${API}/api/admin/restart`, { method: "POST" });
    } catch {}
  }

  useEffect(() => { loadData(false); loadAgentStatus(); }, [loadData, loadAgentStatus]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-faint" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-faint text-sm">
        Failed to load system metrics.
      </div>
    );
  }

  const c = data.counts || {};
  const sys = data.system || {};

  return (
    <div className="h-full overflow-y-auto p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server size={18} className="text-accent" />
          <h1 className="text-base font-bold text-default">System</h1>
        </div>
        <div className="flex items-center gap-2">
          {agentStatus && (
            <span className="text-[10px] text-faint">
              up {fmtDuration(agentStatus.uptime_seconds)}
              {agentStatus.env === "dev" && <span className="ml-1 px-1 py-0.5 rounded bg-amber-900/40 text-amber-400 font-bold">DEV</span>}
            </span>
          )}
          {confirmRestart ? (
            <span className="flex items-center gap-1">
              <span className="text-[10px] text-amber-400">Restart agent?</span>
              <button onClick={handleRestart} className="px-1.5 py-0.5 text-[10px] rounded btn-danger">Yes</button>
              <button onClick={() => setConfirmRestart(false)} className="px-1.5 py-0.5 text-[10px] rounded surface-raised hover:bg-[var(--ds-raised)] text-default">No</button>
            </span>
          ) : restarting || agentStatus?.shutting_down ? (
            <span className="flex items-center gap-1 text-[10px] text-amber-400">
              <Loader2 size={10} className="animate-spin" /> Restarting...
            </span>
          ) : (
            <button
              onClick={() => setConfirmRestart(true)}
              className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-amber-800/50 hover:bg-amber-700/50 text-amber-300 transition-colors"
            >
              <RotateCcw size={10} /> Restart
            </button>
          )}
          <button
            onClick={() => { loadData(true); loadAgentStatus(); }}
            disabled={refreshing}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded surface-raised hover:bg-[var(--ds-raised)] disabled:opacity-50 text-default transition-colors"
          >
            {refreshing ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
            Refresh
          </button>
        </div>
      </div>

      {/* Server Health */}
      <div>
        <SectionHeader icon={Activity} title="Server Health" color="text-accent" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatCard icon={Clock} label="Uptime" value={fmtDuration(sys.uptime_seconds)} color="text-accent" />
          <StatCard icon={Server} label="Memory" value={`${sys.memory_mb || 0} MB`} color="text-purple-400" />
          <StatCard icon={Database} label="Database" value={data.database?.size || "?"} color="text-emerald-400" />
          <StatCard icon={Activity} label="Python" value={sys.python || "?"} sub={`PID ${sys.pid || "?"}`} color="text-amber-400" />
        </div>
      </div>

      {/* Consciousness — the one serial log + its subconscious (specs/CONSCIOUSNESS.md) */}
      {data.consciousness && data.consciousness.total != null && (
        <div>
          <SectionHeader icon={Sparkles} title="Consciousness" color="text-purple-400" />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <StatCard
              icon={MessageSquare}
              label="Timeline Events"
              value={fmtNum(data.consciousness.total)}
              color="text-accent"
            />
            <StatCard
              icon={Brain}
              label="Embedded"
              value={fmtNum(data.consciousness.embedded)}
              sub={data.consciousness.embed_pending > 0
                ? `${fmtNum(data.consciousness.embed_pending)} pending`
                : "caught up"}
              color={data.consciousness.embed_pending > 0 ? "text-amber-400" : "text-emerald-400"}
            />
            <StatCard
              icon={BookOpen}
              label="Summaries"
              value={fmtNum(data.consciousness.summaries)}
              color="text-purple-400"
            />
            <StatCard
              icon={Inbox}
              label="Attention Queue"
              value={fmtNum(data.consciousness.attention_queue)}
              sub={data.consciousness.attention_queue === 0 ? "all attended" : "owed a turn"}
              color={data.consciousness.attention_queue === 0 ? "text-emerald-400" : "text-amber-400"}
            />
          </div>
        </div>
      )}

      {/* Data Records */}
      <div>
        <SectionHeader icon={Database} title="Data Records" color="text-emerald-400" />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          <StatCard icon={Brain} label="Memories" value={fmtNum(c.memories)} color="text-purple-400" />
          <StatCard
            icon={Inbox}
            label="Memory Queue"
            value={fmtNum(c.memory_queue_pending)}
            sub={c.memory_queue_pending === 0 ? "all done" : "pending ingestion"}
            color={c.memory_queue_pending === 0 ? "text-emerald-400" : "text-amber-400"}
          />
          <StatCard icon={FileText} label="Documents" value={fmtNum(c.documents)} color="text-blue-400" />
          <StatCard icon={Bell} label="Reminders" value={fmtNum(c.reminders)} sub={`${fmtNum(c.reminders_active)} active`} color="text-amber-400" />
          <StatCard icon={MessageSquare} label="Chat Turns" value={fmtNum(c.chat_turns)} color="text-accent" />
          <StatCard icon={Target} label="Goals" value={fmtNum(c.goals)} color="text-rose-400" />
          <StatCard icon={FolderKanban} label="Projects" value={fmtNum(c.projects)} color="text-orange-400" />
          <StatCard icon={CheckSquare} label="Tasks" value={fmtNum(c.tasks)} color="text-accent" />
          <StatCard icon={List} label="Lists" value={fmtNum(c.lists)} sub={`${fmtNum(c.list_items)} items`} color="text-accent" />
          <StatCard icon={Image} label="Images" value={fmtNum(c.images)} color="text-pink-400" />
          <StatCard icon={Link} label="Links" value={fmtNum(c.links)} color="text-muted" />
          <StatCard icon={FileText} label="Artifacts" value={fmtNum(c.artifacts)} color="text-violet-400" />
          <StatCard icon={Bell} label="Notifications" value={fmtNum(c.notifications)} color="text-amber-400" />
        </div>
      </div>

      {/* Knowledge Base */}
      <div>
        <SectionHeader icon={Brain} title="Knowledge Base" color="text-purple-400" />
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <StatCard icon={FileText} label="Sources" value={fmtNum(c.knowledge_sources)} color="text-purple-400" />
          <StatCard icon={Database} label="Chunks" value={fmtNum(c.knowledge_chunks)} color="text-purple-400" />
        </div>
      </div>

      {/* Document Curation */}
      {data.doc_curation && (
        <div>
          <SectionHeader icon={BookOpen} title="Document Curation" color="text-indigo-400" />
          {(() => {
            const dc = data.doc_curation;
            const pct = dc.total_memories > 0
              ? Math.round((dc.cursor_position / dc.total_memories) * 100)
              : 0;
            const lc = dc.last_cycle;
            return (
              <div className="space-y-3">
                {/* Progress bar */}
                <div className="surface-card rounded-lg border border-subtle p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-muted">
                      {fmtNum(dc.cursor_position)} / {fmtNum(dc.total_memories)} memories processed
                    </span>
                    <span className="text-xs font-semibold text-indigo-400">{pct}%</span>
                  </div>
                  <div className="w-full h-2 surface-raised rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="mt-2 text-[10px] text-faint">
                    {fmtNum(dc.remaining)} remaining
                    {dc.remaining > 500 && (
                      <span className="ml-1 px-1 py-0.5 rounded bg-amber-900/40 text-amber-400 font-bold">
                        CATCHUP
                      </span>
                    )}
                  </div>
                </div>

                {/* Last cycle info */}
                {lc && (
                  <div className="surface-card rounded border border-subtle px-3 py-2">
                    <div className="text-xs text-muted flex items-center justify-between">
                      <span>
                        <span className="text-faint">Last cycle:</span>{" "}
                        {lc.processed_count != null && (
                          <span className="text-default">{lc.processed_count} processed</span>
                        )}
                        {lc.offered_count != null && (
                          <span className="text-faint"> / {lc.offered_count} offered</span>
                        )}
                        {lc.all_processed && (
                          <span className="ml-1 px-1 py-0.5 rounded text-[10px] bg-emerald-900/30 text-emerald-400 border border-emerald-800">all done</span>
                        )}
                        {lc.auto_advanced && (
                          <span className="ml-1 px-1 py-0.5 rounded text-[10px] bg-amber-900/30 text-amber-400 border border-amber-800">auto-advanced</span>
                        )}
                      </span>
                      <span className="text-[10px] text-faint">{fmtDate(lc.processed_at)}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {/* Jobs & Services */}
      <div>
        <SectionHeader icon={Briefcase} title="Jobs & Services" color="text-amber-400" />
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <StatCard icon={Briefcase} label="Total Jobs" value={fmtNum(c.jobs)} color="text-amber-400" />
          <StatCard icon={Activity} label="Running" value={fmtNum(c.jobs_running)} color="text-accent" />
          <StatCard icon={Clock} label="Queued" value={fmtNum(c.jobs_queued)} color="text-muted" />
          <StatCard icon={HardDrive} label="Backups" value={fmtNum(c.backups)} color="text-accent" />
        </div>

        {/* Latest activity cards */}
        <div className="mt-3 space-y-2">
          {data.latest_job && (
            <div className="surface-card rounded border border-subtle px-3 py-2 flex items-center justify-between">
              <div className="text-xs text-muted">
                <span className="text-faint">Last job:</span>{" "}
                <span className="text-default">{data.latest_job.name}</span>{" "}
                <StatusBadge status={data.latest_job.status} />
              </div>
              <div className="text-[10px] text-faint">{fmtDate(data.latest_job.last_run_at)}</div>
            </div>
          )}
          {data.latest_backup && (
            <div className="surface-card rounded border border-subtle px-3 py-2 flex items-center justify-between">
              <div className="text-xs text-muted">
                <span className="text-faint">Last backup:</span>{" "}
                <StatusBadge status={data.latest_backup.status} />
                {data.latest_backup.duration_secs && (
                  <span className="ml-1 text-faint">({Math.round(data.latest_backup.duration_secs)}s)</span>
                )}
              </div>
              <div className="text-[10px] text-faint">{fmtDate(data.latest_backup.started_at)}</div>
            </div>
          )}
          {data.latest_investment && (
            <div className="surface-card rounded border border-subtle px-3 py-2 flex items-center justify-between">
              <div className="text-xs text-muted">
                <span className="text-faint">Last analysis:</span>{" "}
                <StatusBadge status={data.latest_investment.status} />
                {data.latest_investment.posture && (
                  <span className="ml-1 text-faint">({data.latest_investment.posture})</span>
                )}
              </div>
              <div className="text-[10px] text-faint">{fmtDate(data.latest_investment.created_at)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
