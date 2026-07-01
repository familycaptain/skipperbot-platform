import { useState, useEffect, useCallback } from "react";
import {
  Bell, Clock, Calendar, XCircle, RefreshCw, Loader2,
  ChevronDown, ChevronUp, Plus, Trash2, Edit3, Check, X, AlertCircle,
  Repeat, Zap, User,
} from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

const API = window.__API_BASE || "";

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Helpers ──

function fmtDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit", hour12: true,
    });
  } catch { return iso; }
}

function fmtTimeOnly(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      hour: "numeric", minute: "2-digit", hour12: true,
    });
  } catch { return iso; }
}

function isOverdue(iso) {
  if (!iso) return false;
  try { return new Date(iso) < new Date(); } catch { return false; }
}

function humanRecurrence(rrule) {
  if (!rrule) return null;
  const parts = {};
  rrule.split(";").forEach(p => {
    const [k, v] = p.split("=");
    parts[k] = v;
  });
  const freq = parts.FREQ || "";
  const days = parts.BYDAY || "";
  const interval = parts.INTERVAL ? parseInt(parts.INTERVAL) : 1;
  const dayNames = { MO: "Mon", TU: "Tue", WE: "Wed", TH: "Thu", FR: "Fri", SA: "Sat", SU: "Sun" };

  if (freq === "DAILY" && interval === 1) return "Daily";
  if (freq === "DAILY") return `Every ${interval} days`;
  if (freq === "WEEKLY" && days) {
    const named = days.split(",").map(d => dayNames[d] || d).join(", ");
    return interval > 1 ? `Every ${interval} weeks: ${named}` : `Weekly: ${named}`;
  }
  if (freq === "WEEKLY") return interval > 1 ? `Every ${interval} weeks` : "Weekly";
  if (freq === "MONTHLY" && parts.BYMONTHDAY) return `Monthly on day ${parts.BYMONTHDAY}`;
  if (freq === "MONTHLY" && parts.BYDAY) return `Monthly on ${parts.BYDAY}`;
  if (freq === "MONTHLY") return "Monthly";
  if (freq === "YEARLY") return "Yearly";
  return rrule;
}

// ── Main App ──

export default function RemindersApp({ userId, refreshKey, sendChat, context = {} }) {
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState(context.tab || "reminders"); // "reminders" | "nags"
  const [selectedUser, setSelectedUser] = useState(userId);
  const [users, setUsers] = useState([]);
  const [showInactive, setShowInactive] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);

  // Fetch users for dropdown
  useEffect(() => {
    apiFetch("/api/users").then(u => {
      setUsers(u || []);
    }).catch(() => {});
  }, []);

  // Fetch reminders
  const loadReminders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (selectedUser) params.set("user_id", selectedUser);
      if (showInactive) params.set("include_inactive", "true");
      const data = await apiFetch(`/api/apps/reminders?${params}`);
      setReminders(data.reminders || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedUser, showInactive]);

  useEffect(() => { loadReminders(); }, [loadReminders]);

  // Deep-link: switch tab when context changes (e.g. clicking a nag in Prioritize)
  useEffect(() => {
    if (context.tab && (context.tab === "nags" || context.tab === "reminders")) {
      setTab(context.tab);
    }
  }, [context.tab]);

  // Auto-refresh when chat creates/modifies reminders
  useEffect(() => {
    if (refreshKey > 0) loadReminders();
  }, [refreshKey]);

  // Split into reminders vs nags
  const regularReminders = reminders.filter(r => !r.nag);
  const nags = reminders.filter(r => r.nag);
  const displayList = tab === "nags" ? nags : regularReminders;

  const tabs = [
    { id: "reminders", label: "Reminders", icon: Bell, count: regularReminders.length },
    { id: "nags", label: "Nags", icon: Zap, count: nags.length },
  ];

  return (
    <div className="flex flex-col h-full w-full text-sm text-default overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-subtle shrink-0">
        <div className="flex items-center gap-3">
          <Bell size={18} className="text-violet-400" />
          <span className="font-semibold text-default">Reminders</span>
        </div>
        <div className="flex items-center gap-2">
          {/* User dropdown */}
          <div className="relative">
            <select
              value={selectedUser}
              onChange={e => setSelectedUser(e.target.value)}
              className="appearance-none surface-card border border-subtle rounded px-2 py-1 text-xs text-default pr-6 cursor-pointer hover:border-[var(--ds-border)]"
            >
              <option value="">All users</option>
              {users.map(u => (
                <option key={u.name} value={u.name}>{u.display_name || u.name}</option>
              ))}
            </select>
            <ChevronDown size={12} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-faint pointer-events-none" />
          </div>
          <label className="flex items-center gap-1 text-xs text-faint cursor-pointer">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={e => setShowInactive(e.target.checked)}
              className="rounded border-subtle surface-card text-violet-500 w-3 h-3"
            />
            Inactive
          </label>
          <button onClick={loadReminders} className="p-1 rounded hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] transition-colors">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 px-4 pt-2 shrink-0">
        {tabs.map(t => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t text-xs font-medium transition-colors ${
                tab === t.id
                  ? "surface-card text-violet-400 border-b-2 border-violet-400"
                  : "text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"
              }`}
            >
              <Icon size={13} />
              {t.label}
              <span className="text-[10px] opacity-60 ml-0.5">{t.count}</span>
            </button>
          );
        })}
        <div className="flex-1" />
        <button
          onClick={() => setShowNewForm(f => !f)}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-violet-600 hover:bg-violet-500 text-on-accent transition-colors"
        >
          <Plus size={12} />
          New
        </button>
      </div>

      {/* New reminder form (sends to chat) */}
      {showNewForm && (
        <NewReminderForm
          userId={userId}
          isNag={tab === "nags"}
          onClose={() => setShowNewForm(false)}
          sendChat={sendChat}
        />
      )}

      {/* Error */}
      {error && (
        <div className="mx-4 mt-2 p-2 rounded bg-red-900/30 border border-red-700/50 text-red-400 text-xs flex items-center gap-2">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-1.5">
        {loading && reminders.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-faint">
            <Loader2 size={20} className="animate-spin mr-2" />
            Loading...
          </div>
        ) : displayList.length === 0 ? (
          <PristineEmpty
            appId="reminders"
            blurb={getAppManifest("reminders")?.heroes?.[tab === "nags" ? "nags" : "reminders"]}
            records={displayList}
            loading={loading}
            filterActive={selectedUser !== userId || showInactive}
            fallback={
              <div className="flex flex-col items-center justify-center h-32 text-faint gap-2">
                <Bell size={24} className="opacity-30" />
                <span className="text-xs">No {tab === "nags" ? "nags" : "reminders"} found.</span>
              </div>
            }
          />
        ) : (
          displayList.map((r, idx) => (
            <ReminderCard
              key={r.id}
              reminder={r}
              onRefresh={loadReminders}
              isFirst={idx === 0}
              isLast={idx === displayList.length - 1}
              selectedUser={selectedUser}
              showInactive={showInactive}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Reminder Card ──

function ReminderCard({ reminder, onRefresh, isFirst, isLast, selectedUser, showInactive }) {
  const [expanded, setExpanded] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [reordering, setReordering] = useState(false);

  const r = reminder;
  const active = r.active !== false;
  const overdue = active && isOverdue(r.remind_at);
  const isNag = r.nag;
  const isRecurring = !!r.recurrence;

  async function handleCancel() {
    if (!confirm(`Cancel reminder "${r.message.substring(0, 60)}"?`)) return;
    setCancelling(true);
    try {
      await fetch(`${API}/api/apps/reminders/${r.id}/cancel`, { method: "POST" });
      onRefresh();
    } catch {} finally {
      setCancelling(false);
    }
  }

  async function handleReorder(direction) {
    setReordering(true);
    try {
      await fetch(`${API}/api/apps/reminders/${r.id}/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          direction,
          user_id: selectedUser || "",
          active_only: !showInactive,
        }),
      });
      onRefresh();
    } catch {} finally {
      setReordering(false);
    }
  }

  const borderColor = !active
    ? "border-subtle"
    : overdue
    ? "border-amber-600/50"
    : "border-subtle";

  const bgColor = !active
    ? "surface-card"
    : overdue
    ? "bg-amber-900/10"
    : "surface-card";

  return (
    <div className={`rounded-lg border ${borderColor} ${bgColor} transition-colors`}>
      <div
        className="flex items-start gap-3 px-3 py-2.5 cursor-pointer hover:bg-[var(--ds-raised)]"
        onClick={() => setExpanded(e => !e)}
      >
        {/* Sort arrows */}
        <div className="flex flex-col shrink-0 mt-0.5">
          <button
            onClick={e => { e.stopPropagation(); handleReorder("up"); }}
            disabled={isFirst || reordering}
            className="p-0 text-faint hover:text-violet-400 disabled:opacity-20 disabled:cursor-default transition-colors"
            title="Move up"
          >
            <ChevronUp size={13} />
          </button>
          <button
            onClick={e => { e.stopPropagation(); handleReorder("down"); }}
            disabled={isLast || reordering}
            className="p-0 text-faint hover:text-violet-400 disabled:opacity-20 disabled:cursor-default transition-colors"
            title="Move down"
          >
            <ChevronDown size={13} />
          </button>
        </div>

        {/* Icon */}
        <div className="mt-0.5 shrink-0">
          {isNag ? (
            <Zap size={14} className={active ? "text-amber-400" : "text-faint"} />
          ) : isRecurring ? (
            <Repeat size={14} className={active ? "text-violet-400" : "text-faint"} />
          ) : (
            <Bell size={14} className={active ? "text-blue-400" : "text-faint"} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className={`text-xs leading-relaxed ${active ? "text-default" : "text-faint line-through"}`}>
            {r.message}
          </p>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {/* Next fire time */}
            <span className={`text-[11px] flex items-center gap-1 ${overdue ? "text-amber-400" : "text-faint"}`}>
              <Clock size={10} />
              {overdue ? "Overdue: " : "Next: "}
              {fmtDateTime(r.remind_at)}
            </span>

            {/* Type badge */}
            {isNag && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/30 text-amber-400 border border-amber-700/30">
                nag{r.time_slot ? ` · ${r.time_slot}` : ""}
              </span>
            )}
            {isRecurring && !isNag && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-900/30 text-violet-400 border border-violet-700/30">
                {humanRecurrence(r.recurrence)}
              </span>
            )}
            {!active && (
              <span className="text-[10px] px-1.5 py-0.5 rounded surface-card text-faint border border-subtle">
                inactive
              </span>
            )}

            {/* User */}
            {r.user_id && (
              <span className="text-[10px] text-faint flex items-center gap-0.5">
                <User size={9} />
                {r.user_id}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        {active && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={e => { e.stopPropagation(); handleCancel(); }}
              disabled={cancelling}
              className="p-1 rounded hover:bg-red-900/30 text-faint hover:text-red-400 transition-colors"
              title="Cancel reminder"
            >
              {cancelling ? <Loader2 size={13} className="animate-spin" /> : <XCircle size={13} />}
            </button>
          </div>
        )}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="px-3 pb-2.5 border-t border-subtle pt-2 space-y-1.5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
            <span className="text-faint">ID:</span>
            <span className="text-muted font-mono">{r.id}</span>
            <span className="text-faint">Created:</span>
            <span className="text-muted">{fmtDateTime(r.created_at)}</span>
            {isRecurring && (
              <>
                <span className="text-faint">RRULE:</span>
                <span className="text-muted font-mono text-[10px] break-all">{r.recurrence}</span>
              </>
            )}
            {isNag && r.last_nagged && (
              <>
                <span className="text-faint">Last nagged:</span>
                <span className="text-muted">{r.last_nagged}</span>
              </>
            )}
            {isNag && r.time_slot && (
              <>
                <span className="text-faint">Time slot:</span>
                <span className="text-muted">{r.time_slot}</span>
              </>
            )}
          </div>
          <p className="text-[11px] text-faint mt-2 italic">
            To reschedule, tell Skipper in chat: "reschedule {r.id} to ..."
          </p>
        </div>
      )}
    </div>
  );
}

// ── New Reminder Form ──
// Sends the request to Skipper via chat (free-text time evaluation)

function NewReminderForm({ userId, isNag, onClose, sendChat }) {
  const [message, setMessage] = useState("");
  const [timing, setTiming] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!message.trim()) return;

    // Build a natural language chat message for Skipper
    const chatMsg = isNag
      ? `Set a nag for ${userId}: "${message.trim()}"${timing.trim() ? ` ${timing.trim()}` : ""}`
      : `Set a reminder for ${userId}: "${message.trim()}" ${timing.trim() || ""}`.trim();

    // Send through the WebSocket (appears in chat as a user message)
    if (sendChat) sendChat(chatMsg);
    onClose();
  }

  return (
    <div className="mx-4 mt-2 p-3 rounded-lg surface-card border border-violet-700/40 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-violet-400">
          {isNag ? "New Nag" : "New Reminder"} — via Skipper
        </span>
        <button onClick={onClose} className="text-faint hover:text-[var(--ds-text)]">
          <X size={14} />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-2">
        <input
          type="text"
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder={isNag ? "What should we nag about?" : "What should we remind about?"}
          className="w-full surface-panel border border-subtle rounded px-2 py-1.5 text-xs text-default placeholder-gray-600 focus:outline-none focus:border-violet-500"
          autoFocus
        />
        <input
          type="text"
          value={timing}
          onChange={e => setTiming(e.target.value)}
          placeholder={isNag ? "Time slot: morning, afternoon, evening (optional)" : "When? e.g. \"tomorrow at 9am\", \"every weekday at 8am\""}
          className="w-full surface-panel border border-subtle rounded px-2 py-1.5 text-xs text-default placeholder-gray-600 focus:outline-none focus:border-violet-500"
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-2 py-1 text-xs rounded border border-subtle text-muted hover:bg-[var(--ds-raised)] transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!message.trim()}
            className="flex items-center gap-1 px-3 py-1 text-xs rounded bg-violet-600 hover:bg-violet-500 text-on-accent disabled:opacity-50 transition-colors"
          >
            <Plus size={12} />
            Ask Skipper
          </button>
        </div>
      </form>
      <p className="text-[10px] text-faint leading-relaxed">
        Skipper will interpret the timing and create the reminder. The response will appear in chat.
      </p>
    </div>
  );
}
