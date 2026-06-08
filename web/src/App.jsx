import { useState, useEffect, useCallback } from "react";
import { clearToken, getToken } from "./utils/api";
import Shell from "./components/Shell";
import LoginScreen from "./components/LoginScreen";
import ChatPanel from "./components/ChatPanel";
import AppPanel from "./components/AppPanel";
import Onboarding from "./pages/Onboarding";
import useSkipperSocket from "./hooks/useSkipperSocket";
import { getAppManifest, newInstanceId, setDisabledApps } from "./apps/registry";

/**
 * Root application component.
 *
 * Layout: Shell → split content (AppPanel left + ChatPanel right).
 * On mobile (<768px), AppPanel is hidden and ChatPanel fills 100%.
 */
export default function App() {
  const [user, setUser] = useState(() => {
    try {
      const stored = localStorage.getItem("skipperbot_user");
      if (!stored) return null;
      const parsed = JSON.parse(stored);
      // Must have at least { name }
      if (!parsed?.name) return null;
      // A stored user with no bearer token is a broken/half-finished session:
      // the token couldn't be minted (e.g. the auth signing key wasn't set on a
      // first boot), it expired, or the key rotated. Without a token every API
      // call 401s and the chat socket is rejected (403) — the desktop would
      // still mount but sit forever on "Reconnecting". Treat it as logged-out so
      // the login screen shows and a fresh token can be issued.
      if (!getToken()) {
        localStorage.removeItem("skipperbot_user");
        return null;
      }
      return parsed;
    } catch {
      // Old format was a plain string — clear it
      localStorage.removeItem("skipperbot_user");
      return null;
    }
  });

  // Onboarding gate. While we don't yet know whether the platform has
  // any users, we render nothing — the call is one-shot and resolves
  // in <100ms locally.
  //   needsOnboarding = null         (still checking)
  //   needsOnboarding = true         (no non-bot users — show wizard)
  //   needsOnboarding = false        (at least one user exists — fall through to login / desktop)
  const [needsOnboarding, setNeedsOnboarding] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/onboarding/status");
        if (!res.ok) {
          // Treat any 4xx/5xx as "no onboarding needed" — don't trap
          // the user in a wizard because of a transient API error.
          if (!cancelled) setNeedsOnboarding(false);
          return;
        }
        const data = await res.json();
        if (!cancelled) setNeedsOnboarding(!!data.needs_onboarding);
      } catch {
        if (!cancelled) setNeedsOnboarding(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load the operator's "hidden from desktop" app set so the launcher
  // can filter those icons out. Disabling only hides the icon — the
  // app's backend stays loaded.
  const [disabledReady, setDisabledReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/apps/disabled");
        if (res.ok) {
          const data = await res.json();
          setDisabledApps(data.disabled || []);
        }
      } catch { /* leave the set empty — show all icons */ }
      finally { if (!cancelled) setDisabledReady(true); }
    })();
    return () => { cancelled = true; };
  }, []);

  const userId = user?.name || null;

  // Open apps state — array of { id, appType, name, context? }
  // "home" is a virtual tab, always available, never in the openApps array.
  const [openApps, setOpenApps] = useState([]);
  const [activeAppId, setActiveAppId] = useState("home");

  // Chat panel collapse — when true, AppPanel takes the full desktop width.
  // Persisted so the user's preference survives reloads.
  const [chatCollapsed, setChatCollapsed] = useState(() => {
    try { return localStorage.getItem("skipperbot_chat_collapsed") === "1"; }
    catch { return false; }
  });
  const toggleChat = useCallback(() => {
    setChatCollapsed((v) => {
      const next = !v;
      try { localStorage.setItem("skipperbot_chat_collapsed", next ? "1" : "0"); } catch {}
      return next;
    });
  }, []);

  // Mobile view selector — on <768px screens, only one of "chat" | "apps"
  // is visible. Desktop layout is unaffected. Persisted so reload preserves it.
  const [mobileView, setMobileView] = useState(() => {
    try {
      const v = localStorage.getItem("skipperbot_mobile_view");
      return v === "apps" ? "apps" : "chat";
    } catch { return "chat"; }
  });
  const handleSetMobileView = useCallback((v) => {
    setMobileView(v);
    try { localStorage.setItem("skipperbot_mobile_view", v); } catch {}
  }, []);

  /** Open an app by type. For singletons, re-focuses if already open. */
  const handleOpenApp = useCallback((appType, context = {}) => {
    const manifest = getAppManifest(appType);
    if (!manifest) return;

    // On mobile, opening an app should switch the view to the app panel.
    handleSetMobileView("apps");

    // Singleton check: if already open, just focus it
    if (manifest.singleton) {
      setOpenApps((prev) => {
        const existing = prev.find((a) => a.appType === appType);
        if (existing) {
          setActiveAppId(existing.id);
          // Update context so the app can react to the new deep-link
          if (context && Object.keys(context).length > 0) {
            return prev.map((a) => a.id === existing.id ? { ...a, context } : a);
          }
          return prev;
        }
        const instance = {
          id: newInstanceId(appType),
          appType,
          name: manifest.name,
          context,
        };
        setActiveAppId(instance.id);
        return [...prev, instance];
      });
      return;
    }

    // Multi-instance: always create a new one
    const instance = {
      id: newInstanceId(appType),
      appType,
      name: context.title || manifest.name,
      context,
    };
    setOpenApps((prev) => [...prev, instance]);
    setActiveAppId(instance.id);
  }, [handleSetMobileView]);

  /** Update an open app's metadata (e.g. tab title). */
  const handleUpdateApp = useCallback((appId, updates) => {
    setOpenApps((prev) =>
      prev.map((a) => (a.id === appId ? { ...a, ...updates } : a))
    );
  }, []);

  // Goals app auto-refresh: increment key when chat mutates goal data
  const [goalsRefreshKey, setGoalsRefreshKey] = useState(0);
  const handleGoalsUpdated = useCallback(() => {
    setGoalsRefreshKey((k) => k + 1);
  }, []);

  // Docs app auto-refresh: increment key when chat mutates document data
  const [docsRefreshKey, setDocsRefreshKey] = useState(0);
  const handleDocsUpdated = useCallback(() => {
    setDocsRefreshKey((k) => k + 1);
  }, []);

  // Reminders app auto-refresh: increment key when chat mutates reminder data
  const [remindersRefreshKey, setRemindersRefreshKey] = useState(0);
  const handleRemindersUpdated = useCallback(() => {
    setRemindersRefreshKey((k) => k + 1);
  }, []);

  // Recipes app auto-refresh: increment key when chat mutates recipe data
  const [recipesRefreshKey, setRecipesRefreshKey] = useState(0);
  const handleRecipesUpdated = useCallback(() => {
    setRecipesRefreshKey((k) => k + 1);
  }, []);

  // Brainstorming app auto-refresh: increment key when chat mutates idea data
  const [brainstormRefreshKey, setBrainstormRefreshKey] = useState(0);
  const handleBrainstormUpdated = useCallback(() => {
    setBrainstormRefreshKey((k) => k + 1);
  }, []);

  // To-Do app auto-refresh: increment key when chat mutates to-do data
  const [todoRefreshKey, setTodoRefreshKey] = useState(0);
  const handleTodoUpdated = useCallback(() => {
    setTodoRefreshKey((k) => k + 1);
  }, []);

  // Brainstorming inline diff proposal from Skipper
  const [editProposal, setEditProposal] = useState(null);
  const handleEditProposal = useCallback((data) => {
    setEditProposal(data);
  }, []);

  // Focus banner refresh: increment when Prioritize app mutates focus slots
  const [focusRefreshKey, setFocusRefreshKey] = useState(0);
  const handleFocusChanged = useCallback(() => {
    setFocusRefreshKey((k) => k + 1);
  }, []);

  const socket = useSkipperSocket(userId, handleOpenApp, handleGoalsUpdated, handleDocsUpdated, handleRemindersUpdated, handleRecipesUpdated, handleBrainstormUpdated, handleEditProposal, handleTodoUpdated);

  function handleLogin(userObj) {
    localStorage.setItem("skipperbot_user", JSON.stringify(userObj));
    setUser(userObj);
  }

  function handleLogout() {
    clearToken();
    localStorage.removeItem("skipperbot_user");
    setUser(null);
  }

  const handleSelectApp = useCallback((appId) => {
    setActiveAppId(appId);
  }, []);

  const handleCloseApp = useCallback((appId) => {
    setOpenApps((prev) => {
      const next = prev.filter((a) => a.id !== appId);
      // If we closed the active app, switch to the last remaining or Home
      setActiveAppId((current) => {
        if (current !== appId) return current;
        if (next.length > 0) return next[next.length - 1].id;
        socket.sendContext({});
        return "home";
      });
      return next;
    });
  }, [socket.sendContext]);

  // Update document title
  useEffect(() => {
    document.title = user ? `SkipperBot — ${user.display_name}` : "SkipperBot";
  }, [user]);

  if (needsOnboarding === null) {
    // Status check in flight — render nothing for the brief moment
    // before we know. Otherwise the wizard would flash on screen and
    // then immediately disappear on installs that already have users.
    return null;
  }

  if (needsOnboarding) {
    return (
      <Onboarding
        onComplete={(newUser) => {
          handleLogin(newUser);
          setNeedsOnboarding(false);
        }}
      />
    );
  }

  if (!user) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return (
    <Shell displayName={user.display_name} userRole={user.role} connected={socket.connected} updateAvailable={socket.updateAvailable} onLogout={handleLogout} onGoHome={() => { handleSelectApp("home"); handleSetMobileView("apps"); }} userId={userId} onOpenApp={handleOpenApp} focusRefreshKey={focusRefreshKey} chatCollapsed={chatCollapsed} onToggleChat={toggleChat} mobileView={mobileView} onSetMobileView={handleSetMobileView}>
      {/* Left: App panel with taskbar — on mobile, visible only when mobileView==="apps"; on desktop, expands to full width when chat is collapsed */}
      <div className={`min-h-0 min-w-0 ${mobileView === "apps" ? "flex w-full" : "hidden"} md:flex md:w-auto ${chatCollapsed ? "md:flex-1" : "md:flex-[0_0_60%]"}`}>
        <AppPanel
          openApps={openApps}
          activeAppId={activeAppId}
          userId={userId}
          userRole={user.role}
          onSelectApp={handleSelectApp}
          onCloseApp={handleCloseApp}
          onOpenApp={handleOpenApp}
          onUpdateApp={handleUpdateApp}
          onContextChange={socket.sendContext}
          goalsRefreshKey={goalsRefreshKey}
          docsRefreshKey={docsRefreshKey}
          remindersRefreshKey={remindersRefreshKey}
          recipesRefreshKey={recipesRefreshKey}
          brainstormRefreshKey={brainstormRefreshKey}
          todoRefreshKey={todoRefreshKey}
          editProposal={editProposal}
          onClearEditProposal={() => setEditProposal(null)}
          onFocusChanged={handleFocusChanged}
          sendChat={socket.sendMessage}
        />
      </div>

      {/* Right: Chat panel — on mobile, visible only when mobileView==="chat"; on desktop, 40% width, hidden when collapsed */}
      <div className={`min-h-0 min-w-0 overflow-hidden ${mobileView === "chat" ? "flex w-full" : "hidden"} md:flex md:w-auto ${chatCollapsed ? "md:hidden" : "md:flex-[0_0_40%]"}`}>
        <ChatPanel
          userId={userId}
          connected={socket.connected}
          messages={socket.messages}
          isTyping={socket.isTyping}
          progress={socket.progress}
          sending={socket.sending}
          onSend={socket.sendMessage}
        />
      </div>
    </Shell>
  );
}
