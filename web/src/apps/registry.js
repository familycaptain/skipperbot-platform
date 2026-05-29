import { lazy } from "react";
import { FileText, Target, TrendingUp, Briefcase, Home, Search, ShoppingCart, Bell, LineChart, Hammer, Wrench, Image as ImageIcon, MapPin, Car, FlaskConical, HeartPulse, Lightbulb, ListChecks, List, ListTodo, Server, Mail, CalendarDays, CalendarClock, Bug, ClipboardList, Brain, CheckSquare, Sparkles, ChefHat, Coins, BookOpen, Rss, Tv, PlayCircle } from "lucide-react";

/**
 * App registry — central manifest for all desktop apps.
 *
 * Each entry defines:
 *   id         – unique string key
 *   name       – display name for tabs/UI
 *   icon       – Lucide icon component
 *   component  – lazy-loaded React component
 *   singleton  – if true, only one instance can be open at a time
 *
 * Apps receive these standard props:
 *   appId      – the runtime instance ID (may differ from registry id for multi-instance)
 *   userId     – current user's canonical name
 *   context    – optional context object passed when opening (e.g. { docId, goalId })
 *   onTitle    – callback(newTitle) to update the tab label
 */

const APP_MANIFESTS = {
  // `documents` (listing) and `document` (singleton editor) are now
  // discovered from apps/documents/ui/index.js. Removed from the
  // hardcoded registry as part of the documents app packaging.
  // `goals` is now discovered from apps/goals/ui/index.js (see the
  // import.meta.glob block at the bottom of this file). Removed from the
  // hardcoded registry as part of the goals app packaging.
  // `investment` removed for the public release (the investment app is
  // proprietary; not part of skipperbot-platform).
  // `jobs` is now discovered from apps/jobs/ui/index.js (the jobs app
  // owns its own UI). Removed from the hardcoded registry as part of
  // the jobs app packaging.
  home: {
    id: "home",
    name: "Home",
    icon: Home,
    component: lazy(() => import("./HomeApp")),
    singleton: true,
    appPackage: true,
  },
  automation: {
    id: "automation",
    name: "Automation",
    icon: Lightbulb,
    component: lazy(() => import("./AutomationApp")),
    singleton: true,
    appPackage: true,
  },
  scriptures: {
    id: "scriptures",
    name: "Scriptures",
    icon: BookOpen,
    component: lazy(() => import("./ScripturesApp")),
    singleton: true,
    appPackage: true,
  },
  meals: {
    id: "meals",
    name: "Meals",
    icon: ChefHat,
    component: lazy(() => import("./MealsApp")),
    singleton: true,
    appPackage: true,
  },
  anime: {
    id: "anime",
    name: "Anime",
    icon: Tv,
    component: lazy(() => import("./AnimeApp")),
    singleton: true,
    appPackage: true,
  },
  "anime-player": {
    id: "anime-player",
    name: "Anime Player",
    icon: PlayCircle,
    component: lazy(() => import("./AnimePlayerApp")),
    singleton: false,
    appPackage: true,
  },
  // `recipes` and `recipe` are now discovered from apps/recipes/ui/index.js
  // (see the import.meta.glob block at the bottom of this file).
  images: {
    id: "images",
    name: "Images",
    icon: ImageIcon,
    component: lazy(() => import("./ImagesApp")),
    singleton: true,
    page: 2,
  },
  image: {
    id: "image",
    name: "Image",
    icon: ImageIcon,
    component: lazy(() => import("./ImageViewer")),
    singleton: false,
  },
  finder: {
    id: "finder",
    name: "Finder",
    icon: Search,
    component: lazy(() => import("./FinderApp")),
    singleton: true,
  },
  shopping: {
    id: "shopping",
    name: "Shopping",
    icon: ShoppingCart,
    component: lazy(() => import("./PlaceholderApp")),
    singleton: true,
  },
  // `reminders` is now discovered from apps/reminders/ui/index.js (the
  // reminders app owns its own UI). Removed from the hardcoded registry
  // as part of the reminders app packaging.
  // `behaviors` is now discovered from apps/behaviors/ui/index.js (the
  // behaviors app owns its own UI). Removed from the hardcoded registry
  // as part of the behaviors app packaging.
  builder: {
    id: "builder",
    name: "Builder",
    icon: Hammer,
    component: lazy(() => import("./PlaceholderApp")),
    singleton: true,
    page: 2,
  },
  tools: {
    id: "tools",
    name: "Tools",
    icon: Wrench,
    component: lazy(() => import("./ToolsApp")),
    singleton: true,
    page: 3,
  },
  "locator-item": {
    id: "locator-item",
    name: "Item",
    icon: MapPin,
    component: lazy(() => import("./LocatorDetailApp")),
    singleton: false,
  },
  auto: {
    id: "auto",
    name: "Auto",
    icon: Car,
    component: lazy(() => import("./AutoListApp")),
    singleton: true,
    appPackage: true,
  },
  "auto-vehicle": {
    id: "auto-vehicle",
    name: "Vehicle",
    icon: Car,
    component: lazy(() => import("./AutoDetailApp")),
    singleton: false,
    appPackage: true,
  },
  homeopathy: {
    id: "homeopathy",
    name: "Homeopathy",
    icon: FlaskConical,
    component: lazy(() => import("./HomeopathyApp")),
    singleton: true,
    appPackage: true,
  },
  medical: {
    id: "medical",
    name: "Medical",
    icon: HeartPulse,
    component: lazy(() => import("./MedicalApp")),
    singleton: true,
    appPackage: true,
  },
  brainstorming: {
    id: "brainstorming",
    name: "Brainstorming",
    icon: Lightbulb,
    component: lazy(() => import("./BrainstormListApp")),
    singleton: true,
    page: 2,
  },
  brainstorm: {
    id: "brainstorm",
    name: "Idea",
    icon: Lightbulb,
    component: lazy(() => import("./BrainstormDetailApp")),
    singleton: false,
  },
  // `backups` is now discovered from apps/backups/ui/index.js
  // (the backups app owns its own UI). Removed from the hardcoded
  // registry as part of the backups app packaging.
  // `todo` is now discovered from apps/todo/ui/index.js (the todo app
  // owns its own UI). Removed from the hardcoded registry as part of
  // the todo app packaging.
  // `lists` is now discovered from apps/lists/ui/index.js (the lists app
  // owns its own UI). Removed from the hardcoded registry as part of the
  // lists app packaging.
  // `prioritize` is now discovered from apps/prioritize/ui/index.js
  // (the prioritize app owns its own UI). Removed from the hardcoded
  // registry as part of the prioritize app packaging.
  // `tasks` is now discovered from apps/goals/ui/index.js (the goals app
  // owns both the Goals and Tasks UI). Removed from the hardcoded registry
  // as part of the goals app packaging.
  // `chart` removed for the public release (investment-coupled).
  system: {
    id: "system",
    name: "System",
    icon: Server,
    component: lazy(() => import("./SystemApp")),
    singleton: true,
    page: 3,
  },
  issues: {
    id: "issues",
    name: "Issues",
    icon: Bug,
    component: lazy(() => import("./IssuesApp")),
    singleton: true,
    appPackage: true,
    page: 3,
  },
  email: {
    id: "email",
    name: "Email",
    icon: Mail,
    component: lazy(() => import("./EmailApp")),
    singleton: true,
    appPackage: true,
    page: 2,
  },
  calendar: {
    id: "calendar",
    name: "Calendar",
    icon: CalendarDays,
    component: lazy(() => import("./CalendarApp")),
    singleton: true,
  },
  "calendar-day": {
    id: "calendar-day",
    name: "Day",
    icon: CalendarDays,
    component: lazy(() => import("./CalendarDayApp")),
    singleton: false,
    hidden: true,
  },
  // `schedules` is now discovered from apps/schedules/ui/index.js (the
  // schedules app owns its own UI). Removed from the hardcoded registry
  // as part of the schedules app packaging.
  scrum: {
    id: "scrum",
    name: "Scrum",
    icon: ClipboardList,
    component: lazy(() => import("./ScrumApp")),
    singleton: true,
  },
  thinking: {
    id: "thinking",
    name: "Thinking",
    icon: Brain,
    component: lazy(() => import("./ThinkingApp")),
    singleton: true,
    page: 3,
  },
  // `timeline` is now discovered from apps/timeline/ui/index.js
  // (the timeline app owns its own UI). Removed from the hardcoded
  // registry as part of the timeline app packaging.
  // `folders` + `folder` are now discovered from apps/folders/ui/index.js
  // (the folders app owns its own UI). Removed from the hardcoded
  // registry as part of the folders app packaging.
  evolve: {
    id: "evolve",
    name: "Evolve",
    icon: Sparkles,
    component: lazy(() => import("./EvolveApp")),
    singleton: true,
    page: 3,
  },
  // `notifications` is now discovered from apps/notifications/ui/index.js
  // (the notifications app owns its own UI). Removed from the hardcoded
  // registry as part of the notifications app packaging.
  bounties: {
    id: "bounties",
    name: "Bounties",
    icon: Coins,
    component: lazy(() => import("./BountiesApp")),
    singleton: true,
    appPackage: true,
  },
  newsletter: {
    id: "newsletter",
    name: "Newsletter",
    icon: Rss,
    component: lazy(() => import("./NewsletterApp")),
    singleton: true,
    appPackage: true,
    page: 2,
  },
  chores: {
    id: "chores",
    name: "Chores",
    icon: ListChecks,
    component: lazy(() => import("./ChoresApp")),
    singleton: true,
    appPackage: true,
  },
};

// ---------------------------------------------------------------------------
// Packaged-app discovery
// ---------------------------------------------------------------------------
// Each packaged app under /apps/<id>/ui/index.js exports a default array of
// registry entries. Vite resolves this glob at build time (static analysis),
// so every match is bundled with code-splitting intact.
//
// Adding a new packaged app's UI = drop apps/<id>/ui/{index.js, *.jsx} in.
// Removing one = delete the folder. No edits to this file required.
//
// Discovered entries are auto-tagged with `appPackage: true` so the launcher
// styles them as packaged apps without each manifest having to remember.
const _packagedAppModules = import.meta.glob("../../../apps/*/ui/index.js", { eager: true });
for (const mod of Object.values(_packagedAppModules)) {
  const entries = mod.default || [];
  for (const entry of entries) {
    if (APP_MANIFESTS[entry.id]) {
      console.warn(`[registry] Packaged app entry '${entry.id}' collides with a core entry — packaged wins.`);
    }
    APP_MANIFESTS[entry.id] = { ...entry, appPackage: true };
  }
}

/** Get a manifest by app type ID. */
export function getAppManifest(appType) {
  return APP_MANIFESTS[appType] || null;
}

/** Get all registered app manifests (for launcher UI). Excludes utility apps. */
const LAUNCHER_HIDDEN = new Set(["chart", "document", "recipe", "image", "locator-item", "auto-vehicle", "brainstorm", "calendar-day", "folder", "anime-player"]);
export function getAllApps() {
  return Object.values(APP_MANIFESTS).filter(a => !LAUNCHER_HIDDEN.has(a.id)).sort((a, b) => a.name.localeCompare(b.name));
}

/** Get launcher apps for a specific page (1, 2, or 3). Page 1 = everyday, page 2 = tools, page 3 = system. */
export function getAppsForPage(page) {
  return Object.values(APP_MANIFESTS)
    .filter(a => !LAUNCHER_HIDDEN.has(a.id) && (a.page === page || (page === 1 && !a.page)))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Generate a unique instance ID for an app. */
let _instanceCounter = 0;
export function newInstanceId(appType) {
  return `${appType}-${++_instanceCounter}-${Date.now()}`;
}
