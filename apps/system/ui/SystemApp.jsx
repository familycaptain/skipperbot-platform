import { useState, useEffect, useCallback } from "react";
import {
  Server, Database, RefreshCw, Loader2, Activity,
  Brain, FileText, Bell, MessageSquare, List,
  HardDrive, Briefcase,
  Link, Image, Target, FolderKanban, CheckSquare, Clock,
  RotateCcw, BookOpen, Inbox,
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

function StatCard({ icon: Icon, label, value, sub, color = "text-gray-300" }) {
  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-3 flex items-center gap-3">
      <div className={`p-2 rounded-lg bg-gray-700/50 ${color}`}>
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-semibold text-gray-200">{value}</div>
        <div className="text-[10px] text-gray-500 truncate">{label}</div>
        {sub && <div className="text-[10px] text-gray-600">{sub}</div>}
      </div>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, color = "text-gray-400" }) {
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
    running: "bg-sky-900/30 text-sky-400 border-sky-800",
    failed: "bg-red-900/30 text-red-400 border-red-800",
    queued: "bg-amber-900/30 text-amber-400 border-amber-800",
  };
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${styles[status] || "bg-gray-800 text-gray-500 border-gray-700"}`}>
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
        <Loader2 size={24} className="animate-spin text-gray-500" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
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
          <Server size={18} className="text-cyan-400" />
          <h1 className="text-base font-bold text-gray-200">System</h1>
        </div>
        <div className="flex items-center gap-2">
          {agentStatus && (
            <span className="text-[10px] text-gray-500">
              up {fmtDuration(agentStatus.uptime_seconds)}
              {agentStatus.env === "dev" && <span className="ml-1 px-1 py-0.5 rounded bg-amber-900/40 text-amber-400 font-bold">DEV</span>}
            </span>
          )}
          {confirmRestart ? (
            <span className="flex items-center gap-1">
              <span className="text-[10px] text-amber-400">Restart agent?</span>
              <button onClick={handleRestart} className="px-1.5 py-0.5 text-[10px] rounded bg-red-700 hover:bg-red-600 text-white">Yes</button>
              <button onClick={() => setConfirmRestart(false)} className="px-1.5 py-0.5 text-[10px] rounded bg-gray-700 hover:bg-gray-600 text-gray-300">No</button>
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
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-gray-300 transition-colors"
          >
            {refreshing ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
            Refresh
          </button>
        </div>
      </div>

      {/* Server Health */}
      <div>
        <SectionHeader icon={Activity} title="Server Health" color="text-cyan-400" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatCard icon={Clock} label="Uptime" value={fmtDuration(sys.uptime_seconds)} color="text-cyan-400" />
          <StatCard icon={Server} label="Memory" value={`${sys.memory_mb || 0} MB`} color="text-purple-400" />
          <StatCard icon={Database} label="Database" value={data.database?.size || "?"} color="text-emerald-400" />
          <StatCard icon={Activity} label="Python" value={sys.python || "?"} sub={`PID ${sys.pid || "?"}`} color="text-amber-400" />
        </div>
      </div>

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
          <StatCard icon={MessageSquare} label="Chat Turns" value={fmtNum(c.chat_turns)} color="text-sky-400" />
          <StatCard icon={Target} label="Goals" value={fmtNum(c.goals)} color="text-rose-400" />
          <StatCard icon={FolderKanban} label="Projects" value={fmtNum(c.projects)} color="text-orange-400" />
          <StatCard icon={CheckSquare} label="Tasks" value={fmtNum(c.tasks)} color="text-teal-400" />
          <StatCard icon={List} label="Lists" value={fmtNum(c.lists)} sub={`${fmtNum(c.list_items)} items`} color="text-sky-400" />
          <StatCard icon={Image} label="Images" value={fmtNum(c.images)} color="text-pink-400" />
          <StatCard icon={Link} label="Links" value={fmtNum(c.links)} color="text-gray-400" />
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
                <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-400">
                      {fmtNum(dc.cursor_position)} / {fmtNum(dc.total_memories)} memories processed
                    </span>
                    <span className="text-xs font-semibold text-indigo-400">{pct}%</span>
                  </div>
                  <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="mt-2 text-[10px] text-gray-500">
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
                  <div className="bg-gray-800/30 rounded border border-gray-700/50 px-3 py-2">
                    <div className="text-xs text-gray-400 flex items-center justify-between">
                      <span>
                        <span className="text-gray-500">Last cycle:</span>{" "}
                        {lc.processed_count != null && (
                          <span className="text-gray-300">{lc.processed_count} processed</span>
                        )}
                        {lc.offered_count != null && (
                          <span className="text-gray-500"> / {lc.offered_count} offered</span>
                        )}
                        {lc.all_processed && (
                          <span className="ml-1 px-1 py-0.5 rounded text-[10px] bg-emerald-900/30 text-emerald-400 border border-emerald-800">all done</span>
                        )}
                        {lc.auto_advanced && (
                          <span className="ml-1 px-1 py-0.5 rounded text-[10px] bg-amber-900/30 text-amber-400 border border-amber-800">auto-advanced</span>
                        )}
                      </span>
                      <span className="text-[10px] text-gray-600">{fmtDate(lc.processed_at)}</span>
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
          <StatCard icon={Activity} label="Running" value={fmtNum(c.jobs_running)} color="text-sky-400" />
          <StatCard icon={Clock} label="Queued" value={fmtNum(c.jobs_queued)} color="text-gray-400" />
          <StatCard icon={HardDrive} label="Backups" value={fmtNum(c.backups)} color="text-cyan-400" />
        </div>

        {/* Latest activity cards */}
        <div className="mt-3 space-y-2">
          {data.latest_job && (
            <div className="bg-gray-800/30 rounded border border-gray-700/50 px-3 py-2 flex items-center justify-between">
              <div className="text-xs text-gray-400">
                <span className="text-gray-500">Last job:</span>{" "}
                <span className="text-gray-300">{data.latest_job.name}</span>{" "}
                <StatusBadge status={data.latest_job.status} />
              </div>
              <div className="text-[10px] text-gray-600">{fmtDate(data.latest_job.last_run_at)}</div>
            </div>
          )}
          {data.latest_backup && (
            <div className="bg-gray-800/30 rounded border border-gray-700/50 px-3 py-2 flex items-center justify-between">
              <div className="text-xs text-gray-400">
                <span className="text-gray-500">Last backup:</span>{" "}
                <StatusBadge status={data.latest_backup.status} />
                {data.latest_backup.duration_secs && (
                  <span className="ml-1 text-gray-600">({Math.round(data.latest_backup.duration_secs)}s)</span>
                )}
              </div>
              <div className="text-[10px] text-gray-600">{fmtDate(data.latest_backup.started_at)}</div>
            </div>
          )}
          {data.latest_investment && (
            <div className="bg-gray-800/30 rounded border border-gray-700/50 px-3 py-2 flex items-center justify-between">
              <div className="text-xs text-gray-400">
                <span className="text-gray-500">Last analysis:</span>{" "}
                <StatusBadge status={data.latest_investment.status} />
                {data.latest_investment.posture && (
                  <span className="ml-1 text-gray-500">({data.latest_investment.posture})</span>
                )}
              </div>
              <div className="text-[10px] text-gray-600">{fmtDate(data.latest_investment.created_at)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
