import { Suspense, useRef, useState, useEffect, useReducer, useCallback } from "react";
import { X, Compass, Loader2, Home, ChevronLeft, ChevronRight, HelpCircle, EyeOff } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { getAppManifest, getAppsForPage, subscribeAppVisibility, getHiddenApps, setHiddenApps } from "../apps/registry";

/**
 * Left-side application panel with a taskbar at the top.
 *
 * Renders real app components from the registry. Each open app instance
 * includes { id, appType, name, context } — the registry maps appType
 * to a lazy-loaded React component.
 *
 * Props:
 *   openApps    – array of { id, appType, name, context? }
 *   activeAppId – the currently focused app's id
 *   userId      – current user's canonical name
 *   onSelectApp – callback(appId) when a tab is clicked
 *   onCloseApp  – callback(appId) when a tab's close button is clicked
 *   onOpenApp   – callback(appType, context?) to open an app from the launcher
 *   onUpdateApp – callback(appId, updates) to update app state (e.g. tab title)
 */
export default function AppPanel({
  openApps = [],
  activeAppId = null,
  userId = "",
  userRole = "",
  onSelectApp = () => {},
  onCloseApp = () => {},
  onOpenApp = () => {},
  onUpdateApp = () => {},
  onContextChange = () => {},
  goalsRefreshKey = 0,
  docsRefreshKey = 0,
  remindersRefreshKey = 0,
  recipesRefreshKey = 0,
  brainstormRefreshKey = 0,
  todoRefreshKey = 0,
  editProposal = null,
  onClearEditProposal = () => {},
  onFocusChanged = () => {},
  sendChat = () => {},
}) {
  const activeApp = openApps.find((a) => a.id === activeAppId);

  // Taskbar scroll state
  const scrollRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  // In-app Help panel (per-app help.md, served by GET /api/apps/<id>/help).
  const [helpFor, setHelpFor] = useState(null);   // { appType, name } or null
  const [helpText, setHelpText] = useState("");
  const [helpLoading, setHelpLoading] = useState(false);

  const openHelp = useCallback(async () => {
    if (!activeApp) return;
    setHelpFor({ appType: activeApp.appType, name: activeApp.name });
    setHelpLoading(true);
    setHelpText("");
    try {
      const res = await fetch(`/api/apps/${activeApp.appType}/help`);
      if (res.ok) setHelpText((await res.json()).help || "");
    } catch { /* leave blank → placeholder */ }
    finally { setHelpLoading(false); }
  }, [activeApp]);

  const checkOverflow = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 1);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  }, []);

  useEffect(() => {
    checkOverflow();
  }, [openApps.length, checkOverflow]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", checkOverflow, { passive: true });
    const ro = new ResizeObserver(checkOverflow);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", checkOverflow); ro.disconnect(); };
  }, [checkOverflow]);

  // Auto-scroll active tab into view
  useEffect(() => {
    if (!scrollRef.current || activeAppId === "home") return;
    const tab = scrollRef.current.querySelector(`[data-appid="${activeAppId}"]`);
    if (tab) tab.scrollIntoView({ inline: "nearest", block: "nearest", behavior: "smooth" });
  }, [activeAppId]);

  function scrollBy(delta) {
    scrollRef.current?.scrollBy({ left: delta, behavior: "smooth" });
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 min-w-0 border-r border-subtle">
      {/* ── App Taskbar ── */}
      <div className="flex items-center h-9 surface-panel border-b border-subtle shrink-0">
        {/* Left scroll arrow */}
        {canScrollLeft && (
          <button onClick={() => scrollBy(-120)} className="px-0.5 h-full icon-btn shrink-0">
            <ChevronLeft size={14} />
          </button>
        )}

        {/* Scrollable tab strip */}
        <div ref={scrollRef} className="flex items-center flex-1 min-w-0 px-1 gap-0.5 overflow-x-auto taskbar-scroll">
          {/* Home tab — always first, never closeable */}
          <button
            onClick={() => onSelectApp("home")}
            className={`flex items-center gap-1.5 px-2.5 h-7 rounded text-xs whitespace-nowrap transition-colors shrink-0 ${
              activeAppId === "home"
                ? "surface-raised"
                : "icon-btn"
            }`}
          >
            <Home size={14} className="shrink-0" />
          </button>

          {/* Separator */}
          {openApps.length > 0 && <div className="w-px h-4 divider mx-0.5 shrink-0" />}

          {/* App tabs */}
          {openApps.map((app) => {
            const manifest = getAppManifest(app.appType);
            const Icon = manifest?.icon;
            return (
              <button
                key={app.id}
                data-appid={app.id}
                onClick={() => onSelectApp(app.id)}
                className={`group flex items-center gap-1.5 px-2.5 h-7 rounded text-xs whitespace-nowrap transition-colors shrink-0 ${
                  app.id === activeAppId
                    ? "surface-raised"
                    : "icon-btn"
                }`}
              >
                {Icon && <Icon size={12} className="shrink-0 opacity-60" />}
                <span className="max-w-[120px] truncate">{app.name}</span>
                <span
                  role="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCloseApp(app.id);
                  }}
                  className="ml-0.5 p-0.5 rounded opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 hover:bg-[var(--ds-border-strong)] transition-opacity"
                >
                  <X size={10} />
                </span>
              </button>
            );
          })}
        </div>

        {/* Right scroll arrow */}
        {canScrollRight && (
          <button onClick={() => scrollBy(120)} className="px-0.5 h-full icon-btn shrink-0">
            <ChevronRight size={14} />
          </button>
        )}

        {/* Per-app Help — opens the active app's help.md */}
        {activeApp && (
          <button
            onClick={openHelp}
            title={`Help — ${activeApp.name}`}
            className="px-1.5 h-full icon-btn shrink-0"
          >
            <HelpCircle size={15} />
          </button>
        )}
      </div>

      {/* ── App Content Area ── */}
      <div className="flex-1 min-h-0 relative">
        {/* Home screen */}
        <div
          className="absolute inset-0"
          style={{ display: activeAppId === "home" ? "flex" : "none" }}
        >
          <HomeScreen onOpenApp={onOpenApp} />
        </div>

        {/* App instances */}
        {openApps.map((app) => {
          const manifest = getAppManifest(app.appType);
          if (!manifest) return null;
          const AppComponent = manifest.component;
          return (
            <div
              key={app.id}
              className="absolute inset-0 w-full overflow-hidden"
              style={{ display: app.id === activeAppId ? "flex" : "none" }}
            >
              <Suspense
                fallback={
                  <div className="flex items-center justify-center w-full h-full text-muted">
                    <Loader2 size={20} className="animate-spin mr-2" />
                    Loading {app.name}...
                  </div>
                }
              >
                <AppComponent
                  appId={app.id}
                  userId={userId}
                  userRole={userRole}
                  context={app.context || {}}
                  isActive={app.id === activeAppId}
                  onTitle={(newTitle) => onUpdateApp(app.id, { name: newTitle })}
                  onContextChange={app.id === activeAppId ? onContextChange : () => {}}
                  refreshKey={app.appType === "goals" ? goalsRefreshKey : (app.appType === "documents" || app.appType === "document") ? docsRefreshKey : app.appType === "reminders" ? remindersRefreshKey : (app.appType === "recipes" || app.appType === "recipe") ? recipesRefreshKey : (app.appType === "brainstorming" || app.appType === "brainstorm") ? brainstormRefreshKey : app.appType === "todo" ? todoRefreshKey : undefined}
                  onOpenApp={onOpenApp}
                  onClose={() => onCloseApp(app.id)}
                  onFocusChanged={app.appType === "prioritize" ? onFocusChanged : undefined}
                  editProposal={(app.appType === "brainstorming" || app.appType === "brainstorm") ? editProposal : undefined}
                  onClearEditProposal={(app.appType === "brainstorming" || app.appType === "brainstorm") ? onClearEditProposal : undefined}
                  sendChat={sendChat}
                />
              </Suspense>
            </div>
          );
        })}
      </div>

      {/* ── Per-app Help panel — full-width + scrollable (manuals can be long) ── */}
      {helpFor && (
        <div
          className="fixed inset-0 z-50 flex items-stretch sm:items-center justify-center surface-overlay sm:p-4"
          onClick={() => setHelpFor(null)}
        >
          <div
            className="surface-panel border border-subtle shadow-xl w-full h-full sm:h-[94vh] sm:max-w-5xl sm:rounded-lg flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-subtle shrink-0">
              <div className="flex items-center gap-2 text-default">
                <HelpCircle size={16} className="text-accent" />
                <h3 className="text-sm font-semibold">{helpFor.name} — Help &amp; user guide</h3>
              </div>
              <button onClick={() => setHelpFor(null)} className="icon-btn" title="Close">
                <X size={18} />
              </button>
            </div>
            {/* Scrollable body; content held to a comfortable reading measure. */}
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-3xl mx-auto px-5 py-6 text-sm text-default markdown-body">
                {helpLoading ? (
                  <div className="flex items-center gap-2 text-muted">
                    <Loader2 size={14} className="animate-spin" /> Loading…
                  </div>
                ) : helpText ? (
                  <ReactMarkdown>{helpText}</ReactMarkdown>
                ) : (
                  <p className="text-faint">Help for {helpFor.name} is coming soon.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Home screen — always available as the first tab. Shows app launcher with two pages. */
function HomeScreen({ onOpenApp }) {
  const [currentPage, setCurrentPage] = useState(0);
  const touchStartX = useRef(null);

  // Re-render the launcher when a tile is hidden/shown (here or from Settings).
  const [, _bumpVis] = useReducer((x) => x + 1, 0);
  useEffect(() => subscribeAppVisibility(_bumpVis), []);
  // Right-click "hide" context menu: { app, x, y } or null.
  const [tileMenu, setTileMenu] = useState(null);

  async function hideTile(app) {
    setTileMenu(null);
    const next = Array.from(new Set([...getHiddenApps(), app.id]));
    try {
      await fetch("/api/apps/hidden", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden: next }),
      });
    } catch { /* still hide locally */ }
    setHiddenApps(next);   // notifies subscribers → launcher updates immediately
  }

  const page1Apps = getAppsForPage(1);
  const page2Apps = getAppsForPage(2);
  const page3Apps = getAppsForPage(3);
  const pages = [page1Apps, page2Apps, page3Apps];
  const apps = pages[currentPage];
  const cols = Math.ceil(Math.sqrt(apps.length));

  function handleTouchStart(e) {
    touchStartX.current = e.touches[0].clientX;
  }

  function handleTouchEnd(e) {
    if (touchStartX.current === null) return;
    const delta = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(delta) > 50) {
      if (delta < 0 && currentPage < pages.length - 1) setCurrentPage(p => p + 1);
      if (delta > 0 && currentPage > 0) setCurrentPage(p => p - 1);
    }
    touchStartX.current = null;
  }

  return (
    <div
      className="flex flex-row h-full w-full"
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      {/* Left nav hot area — previous page */}
      <div
        className={`flex-1 h-full ${currentPage > 0 ? "cursor-pointer hover:bg-[var(--ds-raised)]" : "cursor-default"}`}
        onClick={() => currentPage > 0 && setCurrentPage(p => p - 1)}
      />

      {/* Center content */}
      <div className="flex flex-col items-center justify-center gap-6 text-faint select-none px-2 py-4">
        <div className="text-center">
          <p className="text-sm font-medium text-muted">
            {currentPage === 0 ? "Agentic Desktop" : currentPage === 1 ? "Tools & More" : "System & Admin"}
          </p>
          <p className="text-xs text-faint mt-1 whitespace-nowrap">
            Open an app below, or ask Skipper in chat.
          </p>
        </div>
        <div
          className="grid gap-3 max-w-full"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
        >
          {apps.map((app) => {
            const Icon = app.icon;
            const isPkg = app.appPackage;
            return (
              <button
                key={app.id}
                onClick={() => onOpenApp(app.id)}
                onContextMenu={(e) => { e.preventDefault(); setTileMenu({ app, x: e.clientX, y: e.clientY }); }}
                title="Right-click to hide from your desktop"
                className={`flex flex-col items-center gap-1.5 px-4 py-3 rounded-xl transition-colors min-w-[80px] ${
                  isPkg
                    ? "app-tile-pkg"
                    : "app-tile"
                }`}
              >
                {Icon && <Icon size={20} className={isPkg ? "text-pkg" : "text-muted"} />}
                <span className={`text-xs ${isPkg ? "text-pkg" : "text-default"}`}>{app.name}</span>
              </button>
            );
          })}
        </div>
        {/* Page dots */}
        <div className="flex items-center gap-3 pb-2">
          {pages.map((_, i) => (
            <button
              key={i}
              onClick={() => setCurrentPage(i)}
              className={`rounded-full transition-all ${
                i === currentPage
                  ? "w-4 h-2 bg-[var(--ds-text)]"
                  : "w-2 h-2 bg-[var(--ds-faint)]"
              }`}
              title={i === 0 ? "Page 1 — Apps" : i === 1 ? "Page 2 — Tools" : "Page 3 — System"}
            />
          ))}
        </div>
      </div>

      {/* Right nav hot area — next page */}
      <div
        className={`flex-1 h-full ${currentPage < pages.length - 1 ? "cursor-pointer hover:bg-[var(--ds-raised)]" : "cursor-default"}`}
        onClick={() => currentPage < pages.length - 1 && setCurrentPage(p => p + 1)}
      />

      {/* Right-click → hide this tile from MY desktop (restore in Settings → Apps). */}
      {tileMenu && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setTileMenu(null)}
            onContextMenu={(e) => { e.preventDefault(); setTileMenu(null); }}
          />
          <div
            className="fixed z-50 min-w-[200px] rounded-lg border border-subtle surface-card shadow-xl py-1 text-sm"
            style={{ left: Math.min(tileMenu.x, window.innerWidth - 230), top: Math.min(tileMenu.y, window.innerHeight - 60) }}
          >
            <button
              onClick={() => hideTile(tileMenu.app)}
              className="w-full text-left px-3 py-2 text-default hover:bg-[var(--ds-raised)] inline-flex items-center gap-2"
            >
              <EyeOff size={14} className="text-muted" /> Hide {tileMenu.app.name} from my desktop
            </button>
          </div>
        </>
      )}
    </div>
  );
}
