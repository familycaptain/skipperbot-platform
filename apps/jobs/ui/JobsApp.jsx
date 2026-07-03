import { useState, useEffect, useRef, useCallback } from "react";
import {
  Briefcase, Play, Square, RotateCcw, ChevronLeft, ChevronRight,
  Loader2, AlertCircle, Clock, CheckCircle2, XCircle, Pause,
  Terminal, Settings2, Calendar, Filter,
} from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

const API = window.__API_BASE || "";

function StatusBadge({ status }) {
  const map = {
    running:   { color: "text-blue-400 bg-blue-900/40 border-blue-700/50", icon: Loader2, spin: true },
    queued:    { color: "text-yellow-400 bg-yellow-900/40 border-yellow-700/50", icon: Clock },
    completed: { color: "text-emerald-400 bg-emerald-900/40 border-emerald-700/50", icon: CheckCircle2 },
    failed:    { color: "text-red-400 bg-red-900/40 border-red-700/50", icon: XCircle },
    cancelled: { color: "text-muted surface-card border-subtle", icon: XCircle },
    active:    { color: "text-purple-400 bg-purple-900/40 border-purple-700/50", icon: Calendar },
    paused:    { color: "text-orange-400 bg-orange-900/40 border-orange-700/50", icon: Pause },
  };
  const m = map[status] || map.queued;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded border ${m.color}`}>
      <Icon size={10} className={m.spin ? "animate-spin" : ""} />
      {status}
    </span>
  );
}

function fmtTime(v) {
  if (!v) return "—";
  try {
    const d = new Date(v);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch { return String(v); }
}

function ProgressBar({ pct }) {
  return (
    <div className="w-full surface-raised rounded-full h-1.5">
      <div
        className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
        style={{ width: `${Math.min(pct || 0, 100)}%` }}
      />
    </div>
  );
}

// ── Main App ──
export default function JobsApp({ userId, context, refreshKey }) {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all"); // all, running, queued, completed, failed, scheduled

  useEffect(() => { loadJobs(); }, []);
  useEffect(() => { if (refreshKey) loadJobs(); }, [refreshKey]);

  // Auto-poll while any job is running
  useEffect(() => {
    const hasRunning = jobs.some(j => j.status === "running" || j.status === "queued");
    if (!hasRunning) return;
    const poll = setInterval(loadJobs, 5000);
    return () => clearInterval(poll);
  }, [jobs]);

  async function apiFetch(url) {
    const sep = url.includes("?") ? "&" : "?";
    const res = await fetch(`${API}${url}${sep}user_id=${encodeURIComponent(userId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function loadJobs() {
    try {
      setLoading(true);
      const data = await apiFetch("/api/jobs?limit=100");
      setJobs(data);
    } catch (e) {
      console.error("Failed to load jobs:", e);
    } finally {
      setLoading(false);
    }
  }

  async function cancelJob(jobId) {
    if (!confirm("Cancel this job?")) return;
    try {
      await fetch(`${API}/api/jobs/${jobId}/cancel?user_id=${encodeURIComponent(userId)}`, { method: "POST" });
      loadJobs();
      if (selectedJob?.id === jobId) {
        const updated = await apiFetch(`/api/jobs/${jobId}`);
        setSelectedJob(updated);
      }
    } catch (e) { alert(`Cancel failed: ${e.message}`); }
  }

  async function rerunJob(jobId) {
    try {
      const newJob = await (await fetch(`${API}/api/jobs/${jobId}/rerun?user_id=${encodeURIComponent(userId)}`, { method: "POST" })).json();
      loadJobs();
      setSelectedJob(newJob);
    } catch (e) { alert(`Rerun failed: ${e.message}`); }
  }

  function selectJob(job) {
    setSelectedJob(job);
  }

  const filtered = jobs.filter(j => {
    if (filter === "all") return true;
    return j.status === filter;
  });

  // If viewing a detail, show that
  if (selectedJob) {
    return (
      <div className="h-full w-full flex flex-col surface-panel text-default">
        <JobDetail
          job={selectedJob}
          userId={userId}
          onBack={() => { setSelectedJob(null); loadJobs(); }}
          onCancel={cancelJob}
          onRerun={rerunJob}
          apiFetch={apiFetch}
        />
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col surface-panel text-default">
      {/* Header */}
      <div className="px-4 py-3 border-b border-subtle flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Briefcase size={18} className="text-blue-400" />
          <span className="font-semibold text-sm">Jobs</span>
          <span className="text-[10px] text-faint">{jobs.length} total</span>
        </div>
        <button onClick={loadJobs} className="p-1 rounded hover:bg-[var(--ds-raised)] transition-colors">
          <RotateCcw size={14} className={loading ? "animate-spin text-muted" : "text-muted"} />
        </button>
      </div>

      {/* Filter bar */}
      <div className="px-4 py-2 border-b border-subtle flex items-center gap-1.5 overflow-x-auto">
        {["all", "running", "queued", "completed", "failed"].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
              filter === f
                ? "bg-[var(--ds-accent)] text-on-accent"
                : "surface-card text-muted hover:bg-[var(--ds-raised)]"
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
            {f !== "all" && (
              <span className="ml-1 opacity-60">
                {jobs.filter(j => j.status === f).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Job list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <PristineEmpty
            appId="jobs"
            blurb={getAppManifest("jobs")?.blurb}
            records={jobs}
            loading={loading}
            filterActive={filter !== "all"}
            fallback={
              <div className="flex items-center justify-center h-32 text-faint text-xs">
                No jobs found
              </div>
            }
          />
        ) : (
          <div className="divide-y divide-[var(--ds-border)]">
            {filtered.map(job => (
              <button
                key={job.id}
                onClick={() => selectJob(job)}
                className="w-full text-left px-4 py-2.5 hover:bg-[var(--ds-card)] transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <StatusBadge status={job.status} />
                    <span className="text-xs font-medium text-default truncate">{job.name}</span>
                  </div>
                  <ChevronRight size={12} className="text-faint flex-shrink-0" />
                </div>
                <div className="flex items-center justify-between text-[10px] text-faint">
                  <div className="flex items-center gap-3">
                    <span>{job.job_type}</span>
                    <span>{job.id}</span>
                  </div>
                  <span>{fmtTime(job.started_at || job.created_at)}</span>
                </div>
                {job.status === "running" && (
                  <div className="mt-1.5 flex items-center gap-2">
                    <ProgressBar pct={job.progress_pct} />
                    <span className="text-[10px] text-muted flex-shrink-0">{job.progress_pct}%</span>
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


// ── Job Detail View ──
function JobDetail({ job: initialJob, userId, onBack, onCancel, onRerun, apiFetch }) {
  const [job, setJob] = useState(initialJob);
  const [logs, setLogs] = useState([]);
  const [lastLogId, setLastLogId] = useState(0);
  const [activeTab, setActiveTab] = useState("logs");
  const logEndRef = useRef(null);
  const isRunning = job.status === "running" || job.status === "queued";

  // Load job + logs
  useEffect(() => {
    loadJobDetail();
    loadLogs(0);
  }, [initialJob.id]);

  // Poll while running
  useEffect(() => {
    if (!isRunning) return;
    const poll = setInterval(() => {
      loadJobDetail();
      loadLogs(lastLogId);
    }, 3000);
    return () => clearInterval(poll);
  }, [isRunning, lastLogId]);

  // Auto-scroll logs
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  async function loadJobDetail() {
    try {
      const data = await apiFetch(`/api/jobs/${initialJob.id}`);
      setJob(data);
    } catch {}
  }

  async function loadLogs(afterId) {
    try {
      const data = await apiFetch(`/api/jobs/${initialJob.id}/logs?after=${afterId}`);
      if (data.length > 0) {
        setLogs(prev => afterId === 0 ? data : [...prev, ...data]);
        setLastLogId(data[data.length - 1].id);
      }
    } catch {}
  }

  const config = job.config || {};
  const output = job.output || {};

  return (
    <>
      {/* Header */}
      <div className="px-4 py-3 border-b border-subtle">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <button onClick={onBack} className="p-1 rounded hover:bg-[var(--ds-raised)]">
              <ChevronLeft size={14} className="text-muted" />
            </button>
            <StatusBadge status={job.status} />
            <span className="text-sm font-semibold text-default truncate">{job.name}</span>
          </div>
          <div className="flex items-center gap-1.5">
            {isRunning && (
              <button
                onClick={() => onCancel(job.id)}
                className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-red-800 hover:bg-red-700 text-red-100"
              >
                <Square size={10} /> Stop
              </button>
            )}
            {!isRunning && job.status !== "active" && (
              <button
                onClick={() => onRerun(job.id)}
                className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-blue-700 hover:bg-blue-600 text-blue-100"
              >
                <RotateCcw size={10} /> Re-run
              </button>
            )}
          </div>
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-4 text-[10px] text-faint flex-wrap">
          <span>{job.id}</span>
          <span>Type: <span className="text-default">{job.job_type}</span></span>
          {job.created_by && <span>By: <span className="text-default">{job.created_by}</span></span>}
          {job.run_count > 0 && <span>Runs: <span className="text-default">{job.run_count}</span></span>}
        </div>

        {/* Progress bar */}
        {isRunning && (
          <div className="mt-2 flex items-center gap-2">
            <ProgressBar pct={job.progress_pct} />
            <span className="text-[10px] text-muted flex-shrink-0">{job.progress_pct}%</span>
            <span className="text-[10px] text-faint truncate">{job.progress}</span>
          </div>
        )}

        {/* Timestamps */}
        <div className="mt-1.5 flex items-center gap-4 text-[10px] text-faint">
          <span>Created: {fmtTime(job.created_at)}</span>
          {job.started_at && <span>Started: {fmtTime(job.started_at)}</span>}
          {job.completed_at && <span>Finished: {fmtTime(job.completed_at)}</span>}
          {job.started_at && job.completed_at && (
            <span>Duration: {formatDuration(job.started_at, job.completed_at)}</span>
          )}
        </div>

        {/* Error */}
        {job.error && (
          <div className="mt-2 px-2 py-1.5 rounded bg-red-900/30 border border-red-800 text-red-300 text-[10px]">
            {job.error}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-subtle">
        {[
          { id: "logs", label: "Logs", icon: Terminal },
          { id: "config", label: "Config", icon: Settings2 },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors ${
              activeTab === t.id
                ? "text-blue-400 border-b-2 border-blue-400"
                : "text-faint hover:text-[var(--ds-text)]"
            }`}
          >
            <t.icon size={12} />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === "logs" && (
          <LogsPanel logs={logs} isRunning={isRunning} logEndRef={logEndRef} />
        )}
        {activeTab === "config" && (
          <ConfigPanel config={config} output={output} job={job} />
        )}
      </div>
    </>
  );
}


// ── Logs Panel ──
function LogsPanel({ logs, isRunning, logEndRef }) {
  if (logs.length === 0 && !isRunning) {
    return (
      <div className="flex items-center justify-center h-32 text-faint text-xs">
        No logs captured for this job
      </div>
    );
  }

  const levelColor = {
    INFO: "text-default",
    WARNING: "text-yellow-400",
    ERROR: "text-red-400",
    DEBUG: "text-faint",
  };

  return (
    <div className="font-mono text-[11px] leading-relaxed p-3 surface-page">
      {logs.map((log, i) => (
        <div key={log.id || i} className="flex gap-2 hover:bg-[var(--ds-card)] px-1 rounded">
          <span className="text-faint flex-shrink-0 select-none">
            {new Date(log.ts).toLocaleTimeString("en-US", { hour12: false })}
          </span>
          <span className={`${levelColor[log.level] || levelColor.INFO} break-all`}>
            {log.message}
          </span>
        </div>
      ))}
      {isRunning && (
        <div className="flex items-center gap-2 text-faint mt-1">
          <Loader2 size={10} className="animate-spin" />
          <span>Streaming...</span>
        </div>
      )}
      <div ref={logEndRef} />
    </div>
  );
}


// ── Config Panel ──
function ConfigPanel({ config, output, job }) {
  return (
    <div className="p-4 space-y-4">
      {/* Config */}
      <div>
        <h4 className="text-xs font-semibold text-muted mb-2 uppercase tracking-wide">Configuration</h4>
        <pre className="text-[11px] text-default surface-card rounded p-3 overflow-x-auto whitespace-pre-wrap">
          {JSON.stringify(config, null, 2)}
        </pre>
      </div>

      {/* Output */}
      {Object.keys(output).length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted mb-2 uppercase tracking-wide">Output</h4>
          <pre className="text-[11px] text-default surface-card rounded p-3 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(output, null, 2)}
          </pre>
        </div>
      )}

      {/* Last result */}
      {job.last_result && (
        <div>
          <h4 className="text-xs font-semibold text-muted mb-2 uppercase tracking-wide">Last Result</h4>
          <div className="text-xs text-default surface-card rounded p-3">
            {job.last_result}
          </div>
        </div>
      )}

      {/* Description */}
      {job.description && (
        <div>
          <h4 className="text-xs font-semibold text-muted mb-2 uppercase tracking-wide">Description</h4>
          <div className="text-xs text-default">{job.description}</div>
        </div>
      )}
    </div>
  );
}


// ── Helpers ──
function formatDuration(start, end) {
  try {
    const ms = new Date(end) - new Date(start);
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const rs = s % 60;
    if (m < 60) return `${m}m ${rs}s`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return `${h}h ${rm}m`;
  } catch { return "—"; }
}
