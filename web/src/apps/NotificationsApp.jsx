import { useState, useEffect, useCallback } from "react";
import { Bell, ChevronDown, ChevronUp, RefreshCw, Mail } from "lucide-react";

const API = window.__API_BASE ?? "";

function fmtDateTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function channelBadge(channel) {
  const map = {
    discord: { label: "Discord", cls: "bg-indigo-900/60 text-indigo-300 border-indigo-700/40" },
    pushover: { label: "Pushover", cls: "bg-orange-900/60 text-orange-300 border-orange-700/40" },
    websocket: { label: "Web", cls: "bg-sky-900/60 text-sky-300 border-sky-700/40" },
    chat: { label: "Chat", cls: "bg-emerald-900/60 text-emerald-300 border-emerald-700/40" },
  };
  const key = (channel || "").toLowerCase();
  const info = map[key] || { label: channel || "—", cls: "bg-slate-800 text-slate-400 border-slate-700/40" };
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium border ${info.cls}`}>
      {info.label}
    </span>
  );
}

function sourceBadge(sourceType) {
  if (!sourceType) return null;
  return (
    <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700/40">
      {sourceType}
    </span>
  );
}

function NotificationRow({ notif }) {
  const [expanded, setExpanded] = useState(false);
  const firstLine = (notif.message || "").split("\n")[0].trim();
  const hasMore = notif.message && notif.message.trim() !== firstLine;

  return (
    <div className="border border-slate-700/50 rounded-lg bg-slate-800/40 hover:bg-slate-800/60 transition-colors">
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3"
        onClick={() => hasMore && setExpanded(e => !e)}
        style={{ cursor: hasMore ? "pointer" : "default" }}
      >
        <Bell size={14} className="text-slate-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs text-slate-500">{fmtDateTime(notif.created_at)}</span>
            {channelBadge(notif.channel)}
            {sourceBadge(notif.source_type)}
          </div>
          <p className="text-sm text-slate-200 leading-snug break-words">
            {firstLine || <span className="text-slate-500 italic">empty</span>}
            {!expanded && hasMore && (
              <span className="text-slate-500 ml-1">…</span>
            )}
          </p>
        </div>
        {hasMore && (
          <span className="text-slate-500 shrink-0 mt-0.5">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        )}
      </button>
      {expanded && hasMore && (
        <div className="px-4 pb-3 pl-11">
          <pre className="text-xs text-slate-300 whitespace-pre-wrap break-words bg-slate-900/50 rounded p-3 border border-slate-700/30">
            {notif.message.trim()}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function NotificationsApp({ userId }) {
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/apps/notifications?recipient=${encodeURIComponent(userId)}&limit=200`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      setNotifications(d.notifications || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  const filtered = notifications.filter(n => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return (n.message || "").toLowerCase().includes(q)
      || (n.source_type || "").toLowerCase().includes(q)
      || (n.channel || "").toLowerCase().includes(q);
  });

  return (
    <div className="flex flex-col h-full bg-slate-950 text-white">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/60 shrink-0">
        <div className="flex items-center gap-2">
          <Mail size={16} className="text-sky-400" />
          <span className="font-semibold text-slate-100 text-sm">Notifications</span>
          {!loading && (
            <span className="text-xs text-slate-500 ml-1">({notifications.length})</span>
          )}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Search */}
      <div className="px-4 py-2 border-b border-slate-800/60 shrink-0">
        <input
          type="text"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter notifications…"
          className="w-full bg-slate-800/60 border border-slate-700/50 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-slate-500"
        />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {loading && (
          <div className="flex items-center justify-center py-12 text-slate-500 text-sm">
            <RefreshCw size={14} className="animate-spin mr-2" /> Loading…
          </div>
        )}
        {error && (
          <div className="text-red-400 text-sm px-2 py-4 text-center">{error}</div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500 gap-2">
            <Bell size={28} className="opacity-30" />
            <p className="text-sm">{filter ? "No matching notifications" : "No notifications yet"}</p>
          </div>
        )}
        {!loading && filtered.map(n => (
          <NotificationRow key={n.id} notif={n} />
        ))}
      </div>
    </div>
  );
}
