import { useState, useEffect, useCallback } from "react";
import { LogOut, Wifi, WifiOff, Star, Target, FolderKanban, CheckSquare, Bell, BellRing, Car, RefreshCw, Bug, Power, Mail, PanelRightClose, PanelRightOpen, Info, LayoutGrid, MessageSquare } from "lucide-react";
import { hasRole } from "../utils/roles";

const API = window.__API_BASE ?? "";

const FOCUS_ICONS = {
  goal: Target,
  project: FolderKanban,
  task: CheckSquare,
  reminder: Bell,
  nag: BellRing,
  auto_issue: Car,
};

const FOCUS_COLORS = {
  goal: "text-amber-400",
  project: "text-blue-400",
  task: "text-emerald-400",
  reminder: "text-violet-400",
  nag: "text-pink-400",
  auto_issue: "text-orange-400",
};

/**
 * Application shell — top bar + focus banner + split content area.
 *
 * Layout: Top bar (brand + status) → focus banner → content row (AppPanel left + ChatPanel right).
 * On mobile (<768px), the app panel is hidden and chat fills 100%.
 */
export default function Shell({ displayName, userRole, connected, updateAvailable, onLogout, onGoHome, userId, onOpenApp, focusRefreshKey = 0, chatCollapsed = false, onToggleChat, mobileView = "chat", onSetMobileView, children }) {
  const [focusSlots, setFocusSlots] = useState([]);
  const [showRestartConfirm, setShowRestartConfirm] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const isAdmin = hasRole(userRole, "admin");

  async function handleRestart() {
    setRestarting(true);
    setShowRestartConfirm(false);
    try {
      await fetch(`${API}/api/admin/restart`, { method: "POST" });
    } catch {}
    // Wait a moment for the agent to begin shutting down, then poll until it's back
    await new Promise(r => setTimeout(r, 3000));
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/admin/status`, { signal: AbortSignal.timeout(2000) });
        if (r.ok) {
          clearInterval(poll);
          sessionStorage.setItem("sw-update-reload", String(Date.now()));
          window.location.reload();
        }
      } catch {}
    }, 2000);
  }

  const loadFocus = useCallback(async () => {
    if (!userId) return;
    try {
      const res = await fetch(`${API}/api/apps/prioritize/focus?user_id=${userId}`);
      if (res.ok) {
        const d = await res.json();
        setFocusSlots(d.slots || []);
      }
    } catch {}
  }, [userId]);

  useEffect(() => { loadFocus(); }, [loadFocus]);
  // Immediate refresh when Prioritize app signals a change
  useEffect(() => {
    if (focusRefreshKey > 0) loadFocus();
  }, [focusRefreshKey, loadFocus]);
  // Background refresh every 60s
  useEffect(() => {
    const t = setInterval(loadFocus, 60000);
    return () => clearInterval(t);
  }, [loadFocus]);

  function openSource(source_type, source_id, item) {
    if (source_type === "goal") onOpenApp?.("goals", { goalId: source_id });
    else if (source_type === "project") onOpenApp?.("goals", { projectId: source_id });
    else if (source_type === "task") onOpenApp?.("goals", { taskId: source_id });
    else if (source_type === "nag") onOpenApp?.("reminders", { tab: "nags" });
    else if (source_type === "reminder") onOpenApp?.("reminders", { tab: "reminders" });
    else if (source_type === "auto_issue") {
      const vid = item?.vehicle_id || "";
      if (vid) onOpenApp?.("auto-vehicle", { autoVehicleId: vid });
      else onOpenApp?.("auto");
    }
  }

  return (
    <div className="flex flex-col h-full bg-slate-950 text-white">
      {/* ── Top Bar ── */}
      <header className="flex items-center justify-between px-4 h-12 bg-slate-900/80 border-b border-slate-800 shrink-0">
        {/* Left: Brand */}
        <button onClick={onGoHome} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-bold">
            S
          </div>
          <span className="text-sm font-semibold text-slate-200">SkipperBot</span>
        </button>

        {/* Mobile-only: Apps/Chat segmented toggle */}
        {onSetMobileView && (
          <div className="md:hidden flex items-center bg-slate-800/70 border border-slate-700 rounded-full p-0.5 text-xs">
            <button
              onClick={() => onSetMobileView("apps")}
              className={`flex items-center gap-1 px-3 py-1 rounded-full transition-colors ${
                mobileView === "apps"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              aria-pressed={mobileView === "apps"}
            >
              <LayoutGrid size={12} /> Apps
            </button>
            <button
              onClick={() => onSetMobileView("chat")}
              className={`flex items-center gap-1 px-3 py-1 rounded-full transition-colors ${
                mobileView === "chat"
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              aria-pressed={mobileView === "chat"}
            >
              <MessageSquare size={12} /> Chat
            </button>
          </div>
        )}

        {/* Right: Status + user */}
        <div className="flex items-center gap-2 md:gap-3">
          <div className="flex items-center gap-1.5 text-xs">
            {connected ? (
              <Wifi size={14} className="text-emerald-400" />
            ) : (
              <WifiOff size={14} className="text-red-400" />
            )}
            <span className={`hidden md:inline ${connected ? "text-emerald-400" : "text-red-400"}`}>
              {connected ? "Connected" : "Reconnecting…"}
            </span>
          </div>
          {updateAvailable && (
            <button
              onClick={() => {
                // Mark that this is an intentional update-reload so main.jsx's
                // controllerchange listener won't trigger a second reload.
                sessionStorage.setItem("sw-update-reload", String(Date.now()));
                // Clear service worker caches then hard-reload to guarantee new code
                if ('caches' in window) {
                  caches.keys().then(names => Promise.all(names.map(n => caches.delete(n)))).finally(() => {
                    window.location.reload();
                  });
                } else {
                  window.location.reload();
                }
              }}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-600/80 hover:bg-indigo-500 text-white text-xs font-medium animate-pulse hover:animate-none transition-all"
              title="New version available — click to refresh"
            >
              <RefreshCw size={12} />
              Update Available
            </button>
          )}
          {onToggleChat && (
            <button
              onClick={onToggleChat}
              className="hidden md:inline p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
              title={chatCollapsed ? "Show chat panel" : "Hide chat panel (full-width apps)"}
            >
              {chatCollapsed ? <PanelRightOpen size={14} /> : <PanelRightClose size={14} />}
            </button>
          )}
          <button
            onClick={() => onOpenApp?.("notifications")}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-sky-400 transition-colors"
            title="Notifications"
          >
            <Mail size={14} />
          </button>
          <button
            onClick={() => onOpenApp?.("issues")}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-red-400 transition-colors"
            title="Report an issue"
          >
            <Bug size={14} />
          </button>
          <a
            href="https://skipperbot.com"
            target="_blank"
            rel="noopener noreferrer"
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-indigo-400 transition-colors"
            title="About Skipper"
          >
            <Info size={14} />
          </a>
          <span className="hidden md:inline text-xs text-slate-400">{displayName}</span>
          <button
            onClick={onLogout}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
            title="Log out"
          >
            <LogOut size={14} />
          </button>
          {isAdmin && (
            <>
              <div className="w-px h-4 bg-slate-700/60 mx-1" />
              <button
                onClick={() => setShowRestartConfirm(true)}
                className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-red-400 transition-colors"
                title="Restart agent"
              >
                <Power size={14} />
              </button>
            </>
          )}
        </div>
      </header>

      {/* ── Restarting Banner ── */}
      {restarting && (
        <div className="flex items-center justify-center gap-2 px-4 py-2 bg-red-900/40 border-b border-red-800/30 text-red-300 text-xs font-medium animate-pulse">
          <Power size={12} /> Restarting agent... page will reload automatically.
        </div>
      )}

      {/* ── Focus Banner ── */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-1.5 bg-gradient-to-r from-amber-950/30 via-slate-900/60 to-slate-900/60 border-b border-amber-900/20 shrink-0">
        {/* Prioritize app launcher */}
        <button
          onClick={() => onOpenApp?.("prioritize")}
          className="flex items-center gap-1 shrink-0 text-amber-500/70 hover:text-amber-400 transition-colors"
          title="Open Prioritize"
        >
          <Star size={12} />
        </button>
        {/* Focus slot bubbles */}
        {focusSlots.map((slot, idx) => {
          const item = slot.item || {};
          const Icon = FOCUS_ICONS[slot.source_type] || Star;
          const color = FOCUS_COLORS[slot.source_type] || "text-slate-400";
          return (
            <button
              key={slot.id}
              onClick={() => openSource(slot.source_type, slot.source_id, item)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-2xl bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/50 hover:border-amber-700/40 transition-all text-xs group"
              title={`#${idx + 1}: ${item.title || slot.source_id}`}
            >
              <span className="text-amber-500/60 font-bold text-[10px]">{idx + 1}</span>
              <Icon size={10} className={color} />
              <span className="text-slate-300 group-hover:text-white transition-colors">
                {item.title || slot.source_id}
              </span>
            </button>
          );
        })}
        {/* CTA when slots not full */}
        {focusSlots.length < 3 && (
          <button
            onClick={() => onOpenApp?.("prioritize")}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-dashed border-amber-700/50 text-xs shrink-0 animate-pulse hover:animate-none hover:bg-amber-900/20 hover:border-amber-600/60 transition-all"
          >
            <Star size={10} className="text-amber-500" />
            <span className="text-amber-400/80">
              {focusSlots.length === 0 ? "Set your priorities!" : `${3 - focusSlots.length} slot${focusSlots.length === 2 ? "" : "s"} open`}
            </span>
          </button>
        )}
      </div>

      {/* ── Restart Confirm ── */}
      {showRestartConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-5 shadow-xl max-w-xs w-full text-center space-y-3">
            <Power size={28} className="mx-auto text-red-400" />
            <p className="text-sm text-slate-200">Restart the agent?</p>
            <p className="text-xs text-slate-500">All in-flight work will be drained before restart.</p>
            <div className="flex justify-center gap-2 pt-1">
              <button
                onClick={() => setShowRestartConfirm(false)}
                disabled={restarting}
                className="px-4 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded"
              >
                Cancel
              </button>
              <button
                onClick={handleRestart}
                disabled={restarting}
                className="px-4 py-1.5 text-xs bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white rounded font-medium"
              >
                {restarting ? "Restarting..." : "Restart"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Content Area — split: AppPanel (left) + ChatPanel (right) ── */}
      <main className="flex flex-1 min-h-0 overflow-hidden">
        {children}
      </main>
    </div>
  );
}
