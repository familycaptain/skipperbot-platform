import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search, Plus, MapPin, Tag, X, Loader2, Package,
} from "lucide-react";

/**
 * Item Locator List App — singleton for browsing, searching, and creating located items.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey, isActive
 */
export default function LocatorListApp({ appId, userId, context = {}, onOpenApp, refreshKey, isActive }) {
  const [items, setItems] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeLocation, setActiveLocation] = useState("");
  const [showLocationEditor, setShowLocationEditor] = useState(false);
  const [newLocName, setNewLocName] = useState("");

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery.trim()) params.set("q", searchQuery.trim());
      else if (activeLocation) params.set("location", activeLocation);
      const res = await fetch(`/api/apps/home?${params}`);
      if (res.ok) {
        const data = await res.json();
        setItems(data.items || []);
      }
    } catch {}
    setLoading(false);
  }, [searchQuery, activeLocation]);

  const loadLocations = useCallback(async () => {
    try {
      const res = await fetch("/api/apps/home/locations");
      if (res.ok) {
        const data = await res.json();
        setLocations(data.locations || []);
      }
    } catch {}
  }, []);

  useEffect(() => { loadItems(); }, [loadItems]);
  useEffect(() => { loadLocations(); }, []);

  // Auto-refresh from chat mutations
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadItems();
    loadLocations();
  }, [refreshKey]);

  // Reload when tab becomes active
  const wasActive = useRef(isActive);
  useEffect(() => {
    if (isActive && !wasActive.current) {
      loadItems();
      loadLocations();
    }
    wasActive.current = isActive;
  }, [isActive]);

  function openItem(item) {
    onOpenApp?.("locator-item", { locatorItemId: item.id, title: item.name });
  }

  async function handleCreateItem() {
    try {
      const res = await fetch("/api/apps/home", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "New Item", created_by: userId }),
      });
      if (res.ok) {
        const item = await res.json();
        onOpenApp?.("locator-item", { locatorItemId: item.id, title: item.name, editing: true });
        loadItems();
      }
    } catch {}
  }

  async function handleCreateLocation(e) {
    e.preventDefault();
    if (!newLocName.trim()) return;
    try {
      await fetch("/api/apps/home/locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newLocName.trim() }),
      });
      setNewLocName("");
      loadLocations();
    } catch {}
  }

  async function handleDeleteLocation(locId) {
    try {
      await fetch(`/api/apps/home/locations/${locId}`, { method: "DELETE" });
      if (activeLocation === locations.find(l => l.id === locId)?.name) {
        setActiveLocation("");
      }
      loadLocations();
    } catch {}
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="relative flex-1 max-w-xs">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search items..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setActiveLocation(""); }}
              className="w-full bg-slate-800/60 text-sm text-white pl-7 pr-2 py-1 rounded border border-slate-700 outline-none focus:border-indigo-500"
            />
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowLocationEditor(!showLocationEditor)}
            className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
              showLocationEditor ? "bg-indigo-600 text-white" : "text-slate-400 hover:bg-slate-700 hover:text-white"
            }`}
          >
            <MapPin size={12} /> Locations
          </button>
          <button
            onClick={handleCreateItem}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded transition-colors"
          >
            <Plus size={12} /> New
          </button>
        </div>
      </div>

      {/* Location filter bar — always visible */}
      {!showLocationEditor && (
        <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-900/20 border-b border-slate-800/50 overflow-x-auto shrink-0">
          <button
            onClick={() => setActiveLocation("")}
            className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
              !activeLocation ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            All
          </button>
          {locations.map((loc) => (
            <button
              key={loc.id}
              onClick={() => { setActiveLocation(loc.name); setSearchQuery(""); }}
              className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors flex items-center gap-1 ${
                activeLocation === loc.name
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
              }`}
            >
              {loc.name}
              {activeLocation === loc.name && (
                <X size={10} className="opacity-70 hover:opacity-100" onClick={(e) => { e.stopPropagation(); setActiveLocation(""); }} />
              )}
            </button>
          ))}
          {locations.length === 0 && (
            <span className="text-xs text-slate-600 italic">No locations yet</span>
          )}
        </div>
      )}

      {/* Location editor */}
      {showLocationEditor && (
        <div className="px-3 py-2 bg-slate-900/40 border-b border-slate-800 space-y-2">
          <div className="flex flex-wrap gap-1">
            {locations.map((loc) => (
              <span key={loc.id} className="flex items-center gap-1 px-2 py-0.5 bg-slate-800 rounded-full text-xs text-slate-300">
                {loc.name}
                {!loc.id.startsWith("_inline_") && (
                  <button onClick={() => handleDeleteLocation(loc.id)} className="hover:text-red-400 transition-colors">
                    <X size={10} />
                  </button>
                )}
              </span>
            ))}
          </div>
          <form onSubmit={handleCreateLocation} className="flex items-center gap-1">
            <input
              value={newLocName}
              onChange={(e) => setNewLocName(e.target.value)}
              placeholder="New location..."
              className="bg-slate-800 text-white text-xs px-2 py-1 rounded border border-slate-700 outline-none flex-1 max-w-[200px]"
            />
            <button type="submit" className="px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded">Add</button>
          </form>
        </div>
      )}

      {/* Item list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-400">
            <Loader2 size={18} className="animate-spin mr-2" /> Loading items...
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500 text-sm">
            <Package size={32} className="mb-2 opacity-40" />
            {searchQuery ? "No items match your search." : "No items tracked yet. Click + New to add one!"}
          </div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              onClick={() => openItem(item)}
              className="w-full text-left bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/50 hover:border-slate-600 rounded-lg p-3 transition-colors group"
            >
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-medium text-white truncate group-hover:text-indigo-300 transition-colors">
                  {item.name || "Untitled"}
                </h3>
                {item.description && (
                  <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{item.description}</p>
                )}
                <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500">
                  {item.location && (
                    <span className="flex items-center gap-1">
                      <MapPin size={10} />
                      {item.location}
                      {item.sub_location && <span className="text-slate-600"> &gt; {item.sub_location}</span>}
                    </span>
                  )}
                  {item.category && (
                    <span className="px-1.5 py-0 bg-slate-700/50 rounded text-[10px]">{item.category}</span>
                  )}
                  {item.quantity && (
                    <span>&times;{item.quantity}</span>
                  )}
                  {item.tags?.length > 0 && (
                    <span className="flex items-center gap-1">
                      {item.tags.slice(0, 3).map((t) => (
                        <span key={t} className="px-1.5 py-0 bg-slate-700/30 rounded text-[10px] text-slate-500">{t}</span>
                      ))}
                    </span>
                  )}
                </div>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
