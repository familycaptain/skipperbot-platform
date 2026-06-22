import { useState, useEffect, useCallback } from "react";
import {
  Bell, ChevronDown, ChevronUp, RefreshCw, Mail,
  Smartphone, Eye, EyeOff, Send, Trash2, ExternalLink,
} from "lucide-react";

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
    websocket: { label: "Web", cls: "surface-card text-accent border-subtle/40" },
    chat: { label: "Chat", cls: "bg-emerald-900/60 text-emerald-300 border-emerald-700/40" },
  };
  const key = (channel || "").toLowerCase();
  const info = map[key] || { label: channel || "—", cls: "surface-card text-muted border-subtle" };
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium border ${info.cls}`}>
      {info.label}
    </span>
  );
}

function sourceBadge(sourceType) {
  if (!sourceType) return null;
  return (
    <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium surface-card text-muted border border-subtle">
      {sourceType}
    </span>
  );
}

function NotificationRow({ notif }) {
  const [expanded, setExpanded] = useState(false);
  const firstLine = (notif.message || "").split("\n")[0].trim();
  const hasMore = notif.message && notif.message.trim() !== firstLine;

  return (
    <div className="border border-subtle rounded-lg surface-card hover:bg-[var(--ds-card)] transition-colors">
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3"
        onClick={() => hasMore && setExpanded(e => !e)}
        style={{ cursor: hasMore ? "pointer" : "default" }}
      >
        <Bell size={14} className="text-faint mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs text-faint">{fmtDateTime(notif.created_at)}</span>
            {channelBadge(notif.channel)}
            {sourceBadge(notif.source_type)}
          </div>
          <p className="text-sm text-default leading-snug break-words">
            {firstLine || <span className="text-faint italic">empty</span>}
            {!expanded && hasMore && (
              <span className="text-faint ml-1">…</span>
            )}
          </p>
        </div>
        {hasMore && (
          <span className="text-faint shrink-0 mt-0.5">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        )}
      </button>
      {expanded && hasMore && (
        <div className="px-4 pb-3 pl-11">
          <pre className="text-xs text-default whitespace-pre-wrap break-words surface-panel rounded p-3 border border-subtle">
            {notif.message.trim()}
          </pre>
        </div>
      )}
    </div>
  );
}

function PushoverCard({ userId }) {
  const [status, setStatus] = useState(null); // {app_token_configured, configured, enabled, device}
  const [loading, setLoading] = useState(false);
  const [statusError, setStatusError] = useState(null);
  const [open, setOpen] = useState(false);

  // form state
  const [userKey, setUserKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [device, setDevice] = useState("");
  const [enabled, setEnabled] = useState(false);

  // action state
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState(null); // {ok, text}
  const [removing, setRemoving] = useState(false);

  const applyStatus = useCallback((d) => {
    setStatus(d);
    setDevice(d.device || "");
    setEnabled(!!d.enabled);
    // Collapsed by default if fully set up + enabled; expanded otherwise.
    setOpen(!(d.configured && d.enabled));
  }, []);

  const loadStatus = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setStatusError(null);
    try {
      const res = await fetch(`${API}/api/apps/notifications/pushover?user_id=${encodeURIComponent(userId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      applyStatus(d);
    } catch (e) {
      setStatusError(e.message);
    } finally {
      setLoading(false);
    }
  }, [userId, applyStatus]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const save = async () => {
    if (!userId) return;
    setSaving(true);
    setActionError(null);
    setSaved(false);
    setTestMsg(null);
    try {
      const res = await fetch(`${API}/api/apps/notifications/pushover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, user_key: userKey, device, enabled }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok || d.ok === false) throw new Error(d.error || `HTTP ${res.status}`);
      setStatus(d);
      setDevice(d.device || "");
      setEnabled(!!d.enabled);
      setUserKey("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setActionError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async () => {
    if (!userId) return;
    setTesting(true);
    setTestMsg(null);
    setActionError(null);
    try {
      const res = await fetch(`${API}/api/apps/notifications/pushover/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      const d = await res.json().catch(() => ({}));
      if (d.ok) {
        setTestMsg({ ok: true, text: d.message || "Test sent." });
      } else {
        setTestMsg({ ok: false, text: d.error || `HTTP ${res.status}` });
      }
    } catch (e) {
      setTestMsg({ ok: false, text: e.message });
    } finally {
      setTesting(false);
    }
  };

  const remove = async () => {
    if (!userId) return;
    setRemoving(true);
    setActionError(null);
    setTestMsg(null);
    try {
      const res = await fetch(`${API}/api/apps/notifications/pushover?user_id=${encodeURIComponent(userId)}`, {
        method: "DELETE",
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok || d.ok === false) throw new Error(d.error || `HTTP ${res.status}`);
      setUserKey("");
      await loadStatus();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setRemoving(false);
    }
  };

  if (!userId) return null;

  const appReady = status?.app_token_configured;
  const configured = status?.configured;

  let statusPill;
  if (!status) {
    statusPill = null;
  } else if (configured && status.enabled) {
    statusPill = <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-300 border border-emerald-700/40">On</span>;
  } else if (configured) {
    statusPill = <span className="text-[10px] font-medium px-1.5 py-0.5 rounded surface-card text-muted border border-subtle">Off</span>;
  } else {
    statusPill = <span className="text-[10px] font-medium px-1.5 py-0.5 rounded surface-card text-faint border border-subtle">Not set up</span>;
  }

  return (
    <div className="border border-subtle rounded-lg surface-card overflow-hidden">
      <button
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-[var(--ds-card)] transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <Smartphone size={15} className="text-orange-400 shrink-0" />
        <span className="font-semibold text-default text-sm">Pushover</span>
        {statusPill}
        {loading && <RefreshCw size={12} className="animate-spin text-faint" />}
        <span className="ml-auto text-faint shrink-0">
          {open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </span>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-subtle">
          {statusError && (
            <div className="text-red-400 text-xs py-2">Couldn't load Pushover status: {statusError}</div>
          )}

          {status && !appReady && (
            <div className="text-xs text-faint surface-panel rounded p-3 border border-subtle mt-3">
              Pushover isn't enabled on this server yet. An admin needs to set the
              Pushover app token in <span className="text-muted">Settings → Notifications</span>.
            </div>
          )}

          {status && appReady && (
            <div className="space-y-3 mt-3">
              <div>
                <label className="block text-xs text-muted mb-1">Pushover user key</label>
                <div className="relative">
                  <input
                    type={showKey ? "text" : "password"}
                    value={userKey}
                    onChange={e => setUserKey(e.target.value)}
                    placeholder={configured ? "•••••••• saved — type to replace" : "your pushover.net user key"}
                    autoComplete="off"
                    className="w-full surface-card border border-subtle rounded px-3 py-1.5 pr-9 text-sm text-default placeholder-slate-500 focus:outline-none focus:border-[var(--ds-border)] font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(s => !s)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]"
                    title={showKey ? "Hide" : "Show"}
                  >
                    {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs text-muted mb-1">Device <span className="text-faint">(optional)</span></label>
                <input
                  type="text"
                  value={device}
                  onChange={e => setDevice(e.target.value)}
                  placeholder="all devices"
                  className="w-full surface-card border border-subtle rounded px-3 py-1.5 text-sm text-default placeholder-slate-500 focus:outline-none focus:border-[var(--ds-border)]"
                />
              </div>

              <label className="flex items-center gap-2 text-sm text-default cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={e => setEnabled(e.target.checked)}
                  className="accent-orange-500 w-4 h-4"
                />
                Enabled
              </label>

              <div className="flex items-center gap-2 flex-wrap pt-1">
                <button
                  onClick={save}
                  disabled={saving}
                  className="px-3 py-1.5 rounded text-sm font-medium bg-orange-700/70 hover:bg-orange-600 text-orange-50 transition-colors disabled:opacity-40"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={sendTest}
                  disabled={testing || !configured}
                  className="px-3 py-1.5 rounded text-sm font-medium surface-raised hover:bg-[var(--ds-raised)] text-default transition-colors disabled:opacity-40 flex items-center gap-1.5"
                  title={!configured ? "Save a user key first" : "Send a test push"}
                >
                  <Send size={13} /> {testing ? "Sending…" : "Send test"}
                </button>
                {configured && (
                  <button
                    onClick={remove}
                    disabled={removing}
                    className="px-3 py-1.5 rounded text-sm font-medium bg-red-900/50 hover:bg-red-800/70 text-red-300 transition-colors disabled:opacity-40 flex items-center gap-1.5 ml-auto"
                  >
                    <Trash2 size={13} /> {removing ? "Removing…" : "Remove"}
                  </button>
                )}
              </div>

              {saved && <div className="text-emerald-400 text-xs">Saved</div>}
              {actionError && <div className="text-red-400 text-xs">{actionError}</div>}
              {testMsg && (
                <div className={`text-xs ${testMsg.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {testMsg.text}
                </div>
              )}

              <a
                href="https://pushover.net"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-accent hover:text-accent"
              >
                Get your user key at pushover.net <ExternalLink size={11} />
              </a>
            </div>
          )}
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
    <div className="flex flex-col h-full w-full surface-page">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-subtle surface-panel shrink-0">
        <div className="flex items-center gap-2">
          <Mail size={16} className="text-accent" />
          <span className="font-semibold text-default text-sm">Notifications</span>
          {!loading && (
            <span className="text-xs text-faint ml-1">({notifications.length})</span>
          )}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-1.5 rounded hover:bg-[var(--ds-card)] text-muted hover:text-[var(--ds-text)] transition-colors disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Search */}
      <div className="px-4 py-2 border-b border-subtle shrink-0">
        <input
          type="text"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter notifications…"
          className="w-full surface-card border border-subtle rounded px-3 py-1.5 text-sm text-default placeholder-slate-500 focus:outline-none focus:border-[var(--ds-border)]"
        />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        <PushoverCard userId={userId} />
        {loading && (
          <div className="flex items-center justify-center py-12 text-faint text-sm">
            <RefreshCw size={14} className="animate-spin mr-2" /> Loading…
          </div>
        )}
        {error && (
          <div className="text-red-400 text-sm px-2 py-4 text-center">{error}</div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-faint gap-2">
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
