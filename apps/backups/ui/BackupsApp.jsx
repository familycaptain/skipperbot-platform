import { useState, useEffect, useCallback, useRef } from "react";
import {
  HardDrive, Server, RefreshCw, Play, Loader2, Trash2, CheckCircle,
  XCircle, MinusCircle, Clock, Database, FolderArchive, AlertCircle,
} from "lucide-react";

const TRADING_URL = import.meta.env.VITE_TRADING_URL || "https://skippertrader.yourdomain.example";
const TRADING_KEY = import.meta.env.VITE_TRADING_KEY || "";

function fmtBytes(b) {
  if (!b) return "0 B";
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1073741824) return `${(b / 1048576).toFixed(1)} MB`;
  return `${(b / 1073741824).toFixed(2)} GB`;
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}

function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

function fmtDuration(secs) {
  if (!secs) return "0s";
  if (secs < 60) return `${Math.round(secs)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return `${m}m ${s}s`;
}

const STATUS_STYLES = {
  completed: { icon: CheckCircle, color: "text-emerald-400", bg: "bg-emerald-900/20", label: "Success" },
  failed: { icon: XCircle, color: "text-red-400", bg: "bg-red-900/20", label: "Failed" },
  running: { icon: Loader2, color: "text-accent", bg: "surface-card", label: "Running" },
  skipped: { icon: MinusCircle, color: "text-faint", bg: "surface-card", label: "Skipped" },
};

const EMPTY_SOURCE = {
  backups: [],
  config: null,
  loading: true,
  available: true,
  error: "",
};

const SOURCE_META = {
  skipperbot: {
    label: "Skipperbot",
    subtitle: "Windows server",
    icon: HardDrive,
  },
  trading: {
    label: "Trading Service",
    subtitle: "AWS EC2 / Linux",
    icon: Server,
  },
};

function tradingHeaders(extra = {}) {
  return {
    "X-API-Key": TRADING_KEY,
    ...extra,
  };
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed (${res.status})`);
  }
  return res.json();
}

export default function BackupsApp({ isActive }) {
  const [sources, setSources] = useState({
    skipperbot: { ...EMPTY_SOURCE },
    trading: {
      ...EMPTY_SOURCE,
      available: Boolean(TRADING_URL && TRADING_KEY),
      error: TRADING_URL && TRADING_KEY ? "" : "Trading service URL or API key is not configured.",
    },
  });
  const pollRef = useRef(null);

  const loadSkipperbot = useCallback(async (showSpinner = false) => {
    if (showSpinner) {
      setSources((prev) => ({
        ...prev,
        skipperbot: { ...prev.skipperbot, loading: true, error: "" },
      }));
    }

    try {
      const [backupsData, configData] = await Promise.all([
        fetchJson("/api/apps/backups"),
        fetchJson("/api/apps/backups/config"),
      ]);
      setSources((prev) => ({
        ...prev,
        skipperbot: {
          backups: backupsData.backups || [],
          config: configData,
          loading: false,
          available: true,
          error: "",
        },
      }));
    } catch (e) {
      setSources((prev) => ({
        ...prev,
        skipperbot: {
          ...prev.skipperbot,
          loading: false,
          available: false,
          error: e.message || "Could not load Skipperbot backups.",
        },
      }));
    }
  }, []);

  const loadTrading = useCallback(async (showSpinner = false) => {
    if (!TRADING_URL || !TRADING_KEY) {
      setSources((prev) => ({
        ...prev,
        trading: {
          ...prev.trading,
          loading: false,
          available: false,
          error: "Trading service URL or API key is not configured.",
        },
      }));
      return;
    }

    if (showSpinner) {
      setSources((prev) => ({
        ...prev,
        trading: { ...prev.trading, loading: true, error: "" },
      }));
    }

    try {
      const [backupsData, configData] = await Promise.all([
        fetchJson(`${TRADING_URL}/api/backups`, { headers: tradingHeaders() }),
        fetchJson(`${TRADING_URL}/api/backups/config`, { headers: tradingHeaders() }),
      ]);
      setSources((prev) => ({
        ...prev,
        trading: {
          backups: backupsData.backups || [],
          config: configData,
          loading: false,
          available: true,
          error: "",
        },
      }));
    } catch (e) {
      setSources((prev) => ({
        ...prev,
        trading: {
          ...prev.trading,
          loading: false,
          available: false,
          error: e.message || "Could not reach the trading service.",
        },
      }));
    }
  }, []);

  const loadAll = useCallback(async (showSpinner = false) => {
    await Promise.all([
      loadSkipperbot(showSpinner),
      loadTrading(showSpinner),
    ]);
  }, [loadSkipperbot, loadTrading]);

  useEffect(() => {
    loadAll(true);
  }, [loadAll]);

  const wasActive = useRef(isActive);
  useEffect(() => {
    if (isActive && !wasActive.current) loadAll(false);
    wasActive.current = isActive;
  }, [isActive, loadAll]);

  useEffect(() => {
    const hasRunning = Object.values(sources).some((source) =>
      (source.backups || []).some((backup) => backup.status === "running")
    );

    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(() => loadAll(false), 5000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [sources, loadAll]);

  async function handleRunNow(sourceKey) {
    try {
      if (sourceKey === "skipperbot") {
        await fetchJson("/api/apps/backups/run", { method: "POST" });
      } else {
        await fetchJson(`${TRADING_URL}/api/backups/run`, {
          method: "POST",
          headers: tradingHeaders(),
        });
      }
      setTimeout(() => {
        if (sourceKey === "skipperbot") loadSkipperbot(false);
        else loadTrading(false);
      }, 1500);
    } catch (e) {
      setSources((prev) => ({
        ...prev,
        [sourceKey]: {
          ...prev[sourceKey],
          error: e.message || "Could not start backup.",
        },
      }));
    }
  }

  async function handleToggle(sourceKey) {
    const source = sources[sourceKey];
    if (!source.config) return;

    const nextEnabled = !source.config.enabled;
    try {
      if (sourceKey === "skipperbot") {
        await fetchJson("/api/apps/backups/enabled", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: nextEnabled }),
        });
        await loadSkipperbot(false);
      } else {
        await fetchJson(`${TRADING_URL}/api/backups/enabled`, {
          method: "PATCH",
          headers: tradingHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ enabled: nextEnabled }),
        });
        await loadTrading(false);
      }
    } catch (e) {
      setSources((prev) => ({
        ...prev,
        [sourceKey]: {
          ...prev[sourceKey],
          error: e.message || "Could not update backup setting.",
        },
      }));
    }
  }

  async function handleDelete(sourceKey, backupId) {
    if (!confirm("Delete this backup and its saved files?")) return;

    try {
      if (sourceKey === "skipperbot") {
        await fetchJson(`/api/apps/backups/${backupId}`, { method: "DELETE" });
        await loadSkipperbot(false);
      } else {
        await fetchJson(`${TRADING_URL}/api/backups/${backupId}`, {
          method: "DELETE",
          headers: tradingHeaders(),
        });
        await loadTrading(false);
      }
    } catch (e) {
      setSources((prev) => ({
        ...prev,
        [sourceKey]: {
          ...prev[sourceKey],
          error: e.message || "Could not delete backup.",
        },
      }));
    }
  }

  return (
    <div className="flex flex-col h-full w-full text-sm text-default overflow-hidden">
      <div className="flex items-center justify-between px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <div className="flex items-center gap-2">
          <HardDrive size={16} className="text-accent shrink-0" />
          <span className="text-sm font-medium text-default">Backups</span>
        </div>
        <button
          onClick={() => loadAll(true)}
          className="p-1.5 rounded hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] transition-colors"
          title="Refresh all backup sources"
        >
          <RefreshCw
            size={13}
            className={Object.values(sources).some((source) => source.loading) ? "animate-spin" : ""}
          />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {Object.entries(SOURCE_META).map(([sourceKey, meta]) => (
            <BackupSection
              key={sourceKey}
              sourceKey={sourceKey}
              meta={meta}
              state={sources[sourceKey]}
              onRefresh={() => (sourceKey === "skipperbot" ? loadSkipperbot(true) : loadTrading(true))}
              onRunNow={() => handleRunNow(sourceKey)}
              onToggle={() => handleToggle(sourceKey)}
              onDelete={(backupId) => handleDelete(sourceKey, backupId)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function BackupSection({ sourceKey, meta, state, onRefresh, onRunNow, onToggle, onDelete }) {
  const { backups, config, loading, available, error } = state;
  const latest = backups.find((backup) => backup.status === "completed");
  const completedCount = backups.filter((backup) => backup.status === "completed").length;
  const running = backups.some((backup) => backup.status === "running");
  const Icon = meta.icon;

  return (
    <section className="flex flex-col min-h-[380px] rounded-xl border border-subtle surface-page overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-subtle surface-panel">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Icon size={15} className="text-accent shrink-0" />
            <span className="text-sm font-medium text-default">{meta.label}</span>
            {!available && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/30 text-red-300 border border-red-800/40">
                Offline
              </span>
            )}
          </div>
          <div className="text-[11px] text-faint">{meta.subtitle}</div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={onRefresh}
            className="p-1.5 rounded hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] transition-colors"
            title={`Refresh ${meta.label}`}
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={onRunNow}
            disabled={!available || running}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-[var(--ds-accent)] hover:bg-[var(--ds-accent)] disabled:opacity-40 text-on-accent rounded transition-colors"
          >
            {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Run Now
          </button>
        </div>
      </div>

      {config && available && (
        <div className="flex items-center gap-3 px-3 py-2 surface-panel border-b border-subtle text-xs shrink-0">
          <button
            onClick={onToggle}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full transition-colors ${
              config.enabled
                ? "bg-emerald-900/30 text-emerald-400 border border-emerald-700/30"
                : "surface-card text-faint border border-subtle"
            }`}
          >
            <div className={`w-2 h-2 rounded-full ${config.enabled ? "bg-emerald-400" : "surface-raised"}`} />
            {config.enabled ? "Enabled" : "Paused"}
          </button>

          <span className="text-faint flex items-center gap-1">
            <Clock size={10} />
            {config.cron || "0 2 * * *"}
          </span>

          {config.filesystem_path && (
            <span className="text-faint truncate max-w-[220px]" title={config.filesystem_path}>
              {config.filesystem_path}
            </span>
          )}

          <span className="text-faint ml-auto">
            {completedCount}/{config.retention} slots
          </span>
        </div>
      )}

      {latest && available && (
        <div className="px-3 py-2 border-b border-subtle surface-panel shrink-0">
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle size={12} className="text-emerald-400" />
            <span className="text-default">
              Latest: {fmtDate(latest.started_at)} - {fmtDuration(latest.duration_secs)}
            </span>
            <span className="text-faint">
              DB: {fmtBytes(latest.pg_dump_size)}
              {latest.zip_size > 0 ? ` - Files: ${fmtBytes(latest.zip_size)}` : " - DB only"}
            </span>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {!available ? (
          <UnavailableState error={error} />
        ) : loading && backups.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-muted">
            <Loader2 size={18} className="animate-spin mr-2" /> Loading...
          </div>
        ) : backups.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-faint text-sm">
            <Icon size={32} className="mb-2 opacity-40" />
            No backups yet. Click "Run Now" to create the first backup.
          </div>
        ) : (
          backups.map((backup) => (
            <BackupCard
              key={`${sourceKey}:${backup.id}`}
              backup={backup}
              onDelete={onDelete}
            />
          ))
        )}

        {available && error && (
          <div className="text-[11px] text-red-400 px-1 pt-1">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}

function UnavailableState({ error }) {
  return (
    <div className="flex flex-col items-center justify-center h-40 text-center text-faint px-4">
      <AlertCircle size={30} className="mb-2 text-red-400/80" />
      <div className="text-sm text-default">Backup source unavailable</div>
      <div className="mt-1 text-[11px] text-faint max-w-sm">
        {error || "Could not load this backup source right now."}
      </div>
    </div>
  );
}

function BackupCard({ backup: b, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const s = STATUS_STYLES[b.status] || STATUS_STYLES.completed;
  const StatusIcon = s.icon;
  const isRunning = b.status === "running";

  const topCounts = Object.entries(b.table_counts || {})
    .filter(([, v]) => v > 0)
    .sort(([, a], [, z]) => z - a)
    .slice(0, 6);

  return (
    <div className={`rounded-lg border border-subtle ${s.bg} transition-colors`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left flex items-center gap-3 px-3 py-2.5"
      >
        <StatusIcon
          size={16}
          className={`${s.color} shrink-0 ${isRunning ? "animate-spin" : ""}`}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-default font-medium">{fmtDate(b.started_at)}</span>
            <span className="text-[10px] text-faint">{fmtTime(b.started_at)}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.bg} ${s.color} border border-current/20`}>
              {s.label}
            </span>
            {b.duration_secs > 0 && (
              <span className="text-[10px] text-faint">{fmtDuration(b.duration_secs)}</span>
            )}
          </div>

          {b.status === "completed" && (
            <div className="mt-0.5 text-[11px] text-faint flex items-center gap-3">
              <span className="flex items-center gap-1">
                <Database size={9} /> {fmtBytes(b.pg_dump_size)}
              </span>
              {b.zip_size > 0 && (
                <span className="flex items-center gap-1">
                  <FolderArchive size={9} /> {fmtBytes(b.zip_size)}
                </span>
              )}
              {b.gdrive_status && (
                <span className="text-faint">
                  Drive: {b.gdrive_status}
                </span>
              )}
            </div>
          )}

          {b.status === "failed" && b.error && (
            <div className="mt-0.5 text-[11px] text-red-400 truncate">{b.error}</div>
          )}

          {b.status === "skipped" && (
            <div className="mt-0.5 text-[11px] text-faint italic">Backups were disabled</div>
          )}
        </div>
      </button>

      {expanded && b.status === "completed" && (
        <div className="border-t border-subtle px-3 pb-3 pt-2 space-y-2">
          {topCounts.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
              {topCounts.map(([table, count]) => (
                <span key={table}>
                  <span className="text-faint">{table}:</span> {count.toLocaleString()}
                </span>
              ))}
            </div>
          )}

          {b.hostname && (
            <div className="text-[11px] text-faint">
              Host: <span className="font-mono">{b.hostname}</span>
            </div>
          )}

          {b.network_path && (
            <div className="text-[11px] text-faint truncate" title={b.network_path}>
              {b.network_path}
            </div>
          )}

          {b.files_created?.length > 0 && (
            <div className="text-[10px] text-faint space-y-0.5">
              {b.files_created.map((f, i) => (
                <div key={i} className="truncate font-mono">{f}</div>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2 pt-1 border-t border-subtle">
            <span className="text-[10px] text-faint font-mono">{b.id}</span>
            <div className="flex-1" />
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(b.id); }}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded hover:bg-red-900/30 text-faint hover:text-red-400 transition-colors"
            >
              <Trash2 size={10} /> Delete
            </button>
          </div>
        </div>
      )}

      {expanded && b.status === "failed" && b.error && (
        <div className="border-t border-subtle px-3 pb-3 pt-2">
          <pre className="text-[11px] text-red-400 whitespace-pre-wrap break-words">{b.error}</pre>
          <div className="flex items-center gap-2 pt-2 mt-2 border-t border-subtle">
            <span className="text-[10px] text-faint font-mono">{b.id}</span>
            <div className="flex-1" />
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(b.id); }}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded hover:bg-red-900/30 text-faint hover:text-red-400 transition-colors"
            >
              <Trash2 size={10} /> Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
