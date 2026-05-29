import { useState, useEffect, useRef, useCallback } from "react";
import {
  Search, Loader2, Target, FileText, UtensilsCrossed, Bell,
  MapPin, Car, CalendarClock, Lightbulb, ListTodo, X,
} from "lucide-react";

/**
 * Finder App — universal search across all SkipperBot entity types.
 *
 * Phase 1 (MVP): Client-side fan-out to existing search APIs in parallel.
 * Searches: Goals/Projects/Tasks, Documents, Recipes, Reminders,
 *           Schedules, Items (Locator), Auto (vehicles), Brainstorming, To-Do.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey, isActive
 */

const SEARCH_SOURCES = [
  {
    key: "goals",
    label: "Goals",
    icon: Target,
    color: "text-amber-400",
    fetch: async (q) => {
      const res = await fetch(`/api/apps/goals/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return (data.results || []).map((r) => ({
        id: r.id,
        title: r.name,
        type: r.type,
        status: r.status,
        subtitle: r.type + (r.match === "notes" ? " · matched in notes" : ""),
        open: (onOpenApp) => {
          const ctx =
            r.type === "goal" ? { goalId: r.id } :
            r.type === "project" ? { projectId: r.id } :
            { taskId: r.id };
          onOpenApp("goals", ctx);
        },
      }));
    },
  },
  {
    key: "documents",
    label: "Documents",
    icon: FileText,
    color: "text-blue-400",
    fetch: async (q) => {
      const res = await fetch(`/api/apps/documents/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return (data.results || []).map((r) => ({
        id: r.id,
        title: r.title,
        subtitle: [
          r.word_count ? `${r.word_count} words` : null,
          r.tags?.length ? r.tags.join(", ") : null,
        ].filter(Boolean).join(" · ") || "document",
        open: (onOpenApp) => onOpenApp("document", { docId: r.id, title: r.title }),
      }));
    },
  },
  {
    key: "recipes",
    label: "Recipes",
    icon: UtensilsCrossed,
    color: "text-orange-400",
    fetch: async (q) => {
      const res = await fetch(`/api/apps/recipes?q=${encodeURIComponent(q)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return (data.recipes || []).map((r) => ({
        id: r.id,
        title: r.title,
        subtitle: [
          r.servings ? `${r.servings} servings` : null,
          r.categories?.length ? r.categories.join(", ") : null,
        ].filter(Boolean).join(" · ") || "recipe",
        open: (onOpenApp) => onOpenApp("recipe", { recipeId: r.id, title: r.title }),
      }));
    },
  },
  {
    key: "reminders",
    label: "Reminders",
    icon: Bell,
    color: "text-violet-400",
    fetch: async (q, userId) => {
      const res = await fetch(`/api/apps/reminders?user_id=${encodeURIComponent(userId)}`);
      if (!res.ok) return [];
      const data = await res.json();
      const query = q.toLowerCase();
      return (data.reminders || [])
        .filter((r) => r.active !== false && r.message?.toLowerCase().includes(query))
        .slice(0, 10)
        .map((r) => ({
          id: r.id,
          title: r.message,
          subtitle: r.remind_at
            ? new Date(r.remind_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
            : r.recurrence || "reminder",
          open: (onOpenApp) => onOpenApp("reminders"),
        }));
    },
  },
  {
    key: "schedules",
    label: "Schedules",
    icon: CalendarClock,
    color: "text-cyan-400",
    fetch: async (q) => {
      const res = await fetch("/api/apps/schedules");
      if (!res.ok) return [];
      const data = await res.json();
      const query = q.toLowerCase();
      return (data.schedules || [])
        .filter((s) =>
          s.title?.toLowerCase().includes(query) ||
          s.description?.toLowerCase().includes(query) ||
          s.category?.toLowerCase().includes(query)
        )
        .slice(0, 10)
        .map((s) => ({
          id: s.id,
          title: s.title,
          subtitle: [s.category, s.assigned_to].filter(Boolean).join(" · ") || "schedule",
          open: (onOpenApp) => onOpenApp("schedules", { scheduleId: s.id }),
        }));
    },
  },
  {
    key: "locator",
    label: "Items",
    icon: MapPin,
    color: "text-emerald-400",
    fetch: async (q) => {
      const res = await fetch(`/api/apps/home?q=${encodeURIComponent(q)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return (data.items || []).map((r) => ({
        id: r.id,
        title: r.name,
        subtitle: [r.location, r.sub_location].filter(Boolean).join(" → ") || "item",
        open: (onOpenApp) => onOpenApp("locator-item", { locatorItemId: r.id, title: r.name }),
      }));
    },
  },
  {
    key: "auto",
    label: "Vehicles",
    icon: Car,
    color: "text-rose-400",
    fetch: async (q) => {
      const res = await fetch(`/api/apps/auto?q=${encodeURIComponent(q)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return (data.vehicles || [])
        .slice(0, 10)
        .map((v) => ({
          id: v.id,
          title: v.nickname || `${v.year} ${v.make} ${v.model}`,
          subtitle: [v.year, v.make, v.model].filter(Boolean).join(" "),
          open: (onOpenApp) => onOpenApp("auto-vehicle", { autoVehicleId: v.id, title: v.nickname || v.make }),
        }));
    },
  },
  {
    key: "brainstorming",
    label: "Ideas",
    icon: Lightbulb,
    color: "text-yellow-400",
    fetch: async (q) => {
      const res = await fetch(`/api/apps/brainstorming?q=${encodeURIComponent(q)}`);
      if (!res.ok) return [];
      const data = await res.json();
      const ideas = Array.isArray(data) ? data : (data.ideas || []);
      return ideas.map((r) => ({
        id: r.id,
        title: r.title,
        subtitle: [
          r.status,
          r.tags?.length ? r.tags.join(", ") : null,
        ].filter(Boolean).join(" · ") || "idea",
        open: (onOpenApp) => onOpenApp("brainstorm", { ideaId: r.id, title: r.title }),
      }));
    },
  },
  {
    key: "todo",
    label: "To-Do",
    icon: ListTodo,
    color: "text-lime-400",
    fetch: async (q, userId) => {
      const res = await fetch(`/api/apps/todo/items?user_id=${encodeURIComponent(userId)}&include_archived=false`);
      if (!res.ok) return [];
      const data = await res.json();
      const query = q.toLowerCase();
      return (data.items || [])
        .filter((i) => !i.archived && i.text?.toLowerCase().includes(query))
        .slice(0, 10)
        .map((i) => ({
          id: i.id,
          title: i.text,
          subtitle: "to-do",
          open: (onOpenApp) => onOpenApp("todo"),
        }));
    },
  },
];

// Direct ID lookup — maps prefix → { endpoint, source key, result mapper }
const ID_PREFIXES = [
  { prefix: "g-",   key: "goals",        fetch: async (id, onOpenApp) => {
    const res = await fetch(`/api/apps/goals/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.name, subtitle: "goal", open: (o) => o("goals", { goalId: d.id }) };
  }},
  { prefix: "p-",   key: "goals",        fetch: async (id, onOpenApp) => {
    const res = await fetch(`/api/apps/goals/projects/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.name, subtitle: "project", open: (o) => o("goals", { projectId: d.id }) };
  }},
  { prefix: "t-",   key: "goals",        fetch: async (id, onOpenApp) => {
    const res = await fetch(`/api/apps/goals/tasks/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.name, subtitle: "task", open: (o) => o("goals", { taskId: d.id }) };
  }},
  { prefix: "d-",   key: "documents",    fetch: async (id) => {
    const res = await fetch(`/api/apps/documents/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.title, subtitle: "document", open: (o) => o("document", { docId: d.id, title: d.title }) };
  }},
  { prefix: "sch-", key: "schedules",    fetch: async (id) => {
    const res = await fetch(`/api/apps/schedules/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.title, subtitle: d.category || "schedule", open: (o) => o("schedules", { scheduleId: d.id }) };
  }},
  { prefix: "bi-",  key: "brainstorming", fetch: async (id) => {
    const res = await fetch(`/api/apps/brainstorming/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.title, subtitle: "idea", open: (o) => o("brainstorm", { ideaId: d.id, title: d.title }) };
  }},
  { prefix: "loc-", key: "locator",      fetch: async (id) => {
    const res = await fetch(`/api/apps/home/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.name, subtitle: [d.location, d.sub_location].filter(Boolean).join(" → ") || "item", open: (o) => o("locator-item", { locatorItemId: d.id, title: d.name }) };
  }},
  { prefix: "iss-", key: "issues",       fetch: async (id) => {
    const res = await fetch(`/api/apps/issues/${id}`); if (!res.ok) return null;
    const d = await res.json();
    return { id: d.id, title: d.title, subtitle: `${d.type} · ${d.status}`, open: () => {} };
  }},
];

function detectIdLookup(query) {
  const q = query.trim();
  for (const entry of ID_PREFIXES) {
    if (q.startsWith(entry.prefix) && q.length > entry.prefix.length) {
      return entry;
    }
  }
  return null;
}

const MIN_QUERY_LEN = 2;
const DEBOUNCE_MS = 300;

export default function FinderApp({ appId, userId, context = {}, onTitle, onOpenApp, refreshKey, isActive }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = not searched yet
  const [loading, setLoading] = useState(false);
  const [activeFilter, setActiveFilter] = useState("all");
  const inputRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => { onTitle?.("Finder"); }, []);

  // Auto-focus on open and when tab becomes active
  useEffect(() => {
    if (isActive) setTimeout(() => inputRef.current?.focus(), 50);
  }, [isActive]);

  const runSearch = useCallback(async (q) => {
    if (!q || q.trim().length < MIN_QUERY_LEN) {
      setResults(null);
      return;
    }
    setLoading(true);
    const trimmed = q.trim();
    try {
      // Direct ID lookup — skip fan-out if query is an entity ID
      const idMatch = detectIdLookup(trimmed);
      if (idMatch) {
        const item = await idMatch.fetch(trimmed);
        if (item) {
          setResults({ [idMatch.key]: [item] });
        } else {
          setResults({});
        }
        setLoading(false);
        return;
      }

      const sources = activeFilter === "all"
        ? SEARCH_SOURCES
        : SEARCH_SOURCES.filter((s) => s.key === activeFilter);

      const settled = await Promise.allSettled(
        sources.map((src) => src.fetch(trimmed, userId).then((items) => ({ key: src.key, items })))
      );

      const grouped = {};
      for (const r of settled) {
        if (r.status === "fulfilled" && r.value.items.length > 0) {
          grouped[r.value.key] = r.value.items;
        }
      }
      setResults(grouped);
    } catch {
      setResults({});
    } finally {
      setLoading(false);
    }
  }, [activeFilter, userId]);

  function handleChange(e) {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(timerRef.current);
    if (val.trim().length < MIN_QUERY_LEN) {
      setResults(null);
      return;
    }
    timerRef.current = setTimeout(() => runSearch(val), DEBOUNCE_MS);
  }

  function handleClear() {
    setQuery("");
    setResults(null);
    inputRef.current?.focus();
  }

  function handleKeyDown(e) {
    if (e.key === "Escape") handleClear();
  }

  const totalResults = results
    ? Object.values(results).reduce((sum, arr) => sum + arr.length, 0)
    : 0;

  return (
    <div className="flex flex-col h-full w-full">
      {/* Search bar */}
      <div className="px-4 pt-4 pb-2 shrink-0">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search everything..."
            autoFocus
            className="w-full pl-9 pr-9 py-2.5 rounded-lg bg-slate-800/80 border border-slate-700/60 text-sm text-slate-200 placeholder-slate-500 outline-none focus:border-indigo-500/60 focus:ring-1 focus:ring-indigo-500/30 transition-all"
          />
          {query && (
            <button onClick={handleClear} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Filter bubbles */}
      <div className="px-4 pb-2 flex flex-wrap gap-1.5 shrink-0">
        <FilterBubble label="All" active={activeFilter === "all"} onClick={() => setActiveFilter("all")} />
        {SEARCH_SOURCES.map((src) => (
          <FilterBubble
            key={src.key}
            label={src.label}
            active={activeFilter === src.key}
            onClick={() => setActiveFilter(src.key)}
          />
        ))}
      </div>

      {/* Results area */}
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {loading && (
          <div className="flex items-center justify-center py-12 text-slate-500">
            <Loader2 size={20} className="animate-spin mr-2" />
            <span className="text-sm">Searching...</span>
          </div>
        )}

        {!loading && results === null && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500">
            <Search size={32} className="mb-3 opacity-40" />
            <p className="text-sm">Search across all your goals, documents, recipes, and more</p>
            <p className="text-xs text-slate-600 mt-1">Type at least 2 characters to search</p>
          </div>
        )}

        {!loading && results !== null && totalResults === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500">
            <Search size={32} className="mb-3 opacity-40" />
            <p className="text-sm">No results for &ldquo;{query.trim()}&rdquo;</p>
            {activeFilter !== "all" && (
              <button
                onClick={() => { setActiveFilter("all"); setTimeout(() => runSearch(query), 50); }}
                className="text-xs text-indigo-400 hover:text-indigo-300 mt-2"
              >
                Search all categories instead
              </button>
            )}
          </div>
        )}

        {!loading && results !== null && totalResults > 0 && (() => {
          const srcKeys = new Set(SEARCH_SOURCES.map(s => s.key));
          const extraKeys = Object.keys(results).filter(k => !srcKeys.has(k) && results[k]?.length > 0);
          return (
          <div className="space-y-4">
            {SEARCH_SOURCES.map((src) => {
              const items = results[src.key];
              if (!items || items.length === 0) return null;
              const Icon = src.icon;
              return (
                <div key={src.key}>
                  {/* Section header */}
                  <div className="flex items-center gap-2 mb-1.5">
                    <Icon size={14} className={src.color} />
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{src.label}</span>
                    <span className="text-xs text-slate-600">({items.length})</span>
                  </div>
                  {/* Result cards */}
                  <div className="space-y-1">
                    {items.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => item.open(onOpenApp)}
                        className="w-full text-left px-3 py-2 rounded-md bg-slate-800/50 hover:bg-slate-700/60 border border-slate-800 hover:border-slate-700 transition-colors group"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-slate-200 truncate flex-1 group-hover:text-white">
                            {item.title}
                          </span>
                          <span className="text-[10px] text-slate-600 font-mono shrink-0">{item.id}</span>
                        </div>
                        {item.subtitle && (
                          <div className="text-xs text-slate-500 mt-0.5 truncate">{item.subtitle}</div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
            {/* ID-only results (e.g. issues) not in SEARCH_SOURCES */}
            {extraKeys.map((key) => {
              const items = results[key];
              return (
                <div key={key}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <Search size={14} className="text-slate-400" />
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{key}</span>
                    <span className="text-xs text-slate-600">({items.length})</span>
                  </div>
                  <div className="space-y-1">
                    {items.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => item.open(onOpenApp)}
                        className="w-full text-left px-3 py-2 rounded-md bg-slate-800/50 hover:bg-slate-700/60 border border-slate-800 hover:border-slate-700 transition-colors group"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-slate-200 truncate flex-1 group-hover:text-white">{item.title}</span>
                          <span className="text-[10px] text-slate-600 font-mono shrink-0">{item.id}</span>
                        </div>
                        {item.subtitle && <div className="text-xs text-slate-500 mt-0.5 truncate">{item.subtitle}</div>}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          );
        })()}
      </div>
    </div>
  );
}

function FilterBubble({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-xs transition-colors ${
        active
          ? "bg-indigo-600/80 text-white"
          : "bg-slate-800/60 text-slate-400 hover:bg-slate-700/60 hover:text-slate-300"
      }`}
    >
      {label}
    </button>
  );
}
