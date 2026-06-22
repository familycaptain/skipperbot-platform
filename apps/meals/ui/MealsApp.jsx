import { useState, useEffect, useCallback, useRef } from "react";
import {
  Shuffle, X, Plus, ChevronDown, ChevronRight, Star, Search,
  UtensilsCrossed, Flame, Zap, Clock, Tag, Globe, Boxes, Pencil,
  Trash2, Check, AlertCircle, BookOpen, CalendarDays, RefreshCw,
  Camera, Image as ImageIcon, FileDown
} from "lucide-react";

const API = "/api/apps/meals";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function imgSrc(img) {
  if (!img) return null;
  if (img.storage_path) return "/" + img.storage_path;
  return `/api/apps/images/${img.id}/file`;
}

function api(path, opts = {}) {
  return fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e)));
}

function EffortBadge({ effort }) {
  const map = {
    low:    { label: "Low",    icon: Zap,   cls: "bg-green-900/40 text-green-300 border border-green-700/50" },
    medium: { label: "Medium", icon: Flame, cls: "bg-amber-900/40 text-amber-300 border border-amber-700/50" },
    high:   { label: "High",   icon: Clock, cls: "bg-red-900/40 text-red-300 border border-red-700/50" },
  };
  const e = map[effort] || map.medium;
  const Icon = e.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${e.cls}`}>
      <Icon size={10} />{e.label}
    </span>
  );
}

function StarRating({ value, onChange, readonly = false }) {
  const [hover, setHover] = useState(0);
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map(n => (
        <Star
          key={n}
          size={14}
          className={`cursor-pointer transition-colors ${
            n <= (hover || value || 0)
              ? "fill-amber-400 text-amber-400"
              : "text-faint"
          } ${readonly ? "cursor-default" : ""}`}
          onClick={() => !readonly && onChange && onChange(n === value ? null : n)}
          onMouseEnter={() => !readonly && setHover(n)}
          onMouseLeave={() => !readonly && setHover(0)}
        />
      ))}
    </div>
  );
}

function TagChip({ label, onRemove, color = "zinc" }) {
  const colors = {
    zinc: "surface-raised text-default border border-subtle",
    blue: "bg-blue-900/40 text-blue-300 border border-blue-700/50",
    green: "bg-green-900/40 text-green-300 border border-green-700/50",
    red: "bg-red-900/40 text-red-300 border border-red-700/50",
  };
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${colors[color] || colors.zinc}`}>
      {label}
      {onRemove && <X size={10} className="cursor-pointer hover:text-[var(--ds-text)]" onClick={onRemove} />}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Meal Photo Strip
// ---------------------------------------------------------------------------

function MealPhotoStrip({ mealId, initialPhotos, userId }) {
  const [photos, setPhotos] = useState(initialPhotos || []);
  const [uploading, setUploading] = useState(false);
  const [lightbox, setLightbox] = useState(null);
  const inputRef = useRef();

  useEffect(() => { setPhotos(initialPhotos || []); }, [initialPhotos]);

  async function handleFileChange(e) {
    const file = e.target.files[0];
    if (!file || !mealId) return;
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("entity_type", "meal");
    fd.append("entity_id", mealId);
    fd.append("uploaded_by", userId || "");
    try {
      const res = await fetch("/api/apps/images/upload", { method: "POST", body: fd });
      if (res.ok) {
        const img = await res.json();
        setPhotos(prev => [...prev, img]);
      }
    } catch {}
    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleRemove(imgId) {
    await fetch(`${API}/${mealId}/photos/${imgId}/unlink`, { method: "DELETE" });
    setPhotos(prev => prev.filter(i => i.id !== imgId));
  }

  async function handleSetPrimary(imgId) {
    await fetch(`${API}/${mealId}/photos/${imgId}/set-primary`, { method: "POST" });
    setPhotos(prev => {
      const target = prev.find(i => i.id === imgId);
      const rest = prev.filter(i => i.id !== imgId);
      return target ? [target, ...rest] : prev;
    });
  }

  return (
    <div>
      {lightbox && (
        <div
          className="fixed inset-0 surface-overlay z-50 flex items-center justify-center"
          onClick={() => setLightbox(null)}
        >
          <button
            className="absolute top-4 right-4 text-default/70 hover:text-[var(--ds-text)]"
            onClick={() => setLightbox(null)}
          >
            <X size={24} />
          </button>
          <img
            src={lightbox}
            alt=""
            className="max-w-full max-h-[90vh] object-contain rounded-lg"
            onClick={e => e.stopPropagation()}
          />
        </div>
      )}

      <div className="flex flex-wrap gap-2 items-center">
        {photos.map((img, idx) => (
          <div key={img.id} className="relative group">
            <img
              src={imgSrc(img)}
              alt=""
              className={`w-20 h-20 object-cover rounded-lg cursor-pointer transition-all ${
                idx === 0
                  ? "border-2 border-amber-500/70"
                  : "border border-subtle hover:border-[var(--ds-border)]"
              }`}
              onClick={() => setLightbox(imgSrc(img))}
            />
            {/* Primary star badge */}
            {idx === 0
              ? <div className="absolute top-1 left-1 w-4 h-4 rounded-full bg-amber-500 flex items-center justify-center" title="Primary photo">
                  <Star size={9} fill="white" className="text-default" />
                </div>
              : <button
                  onClick={e => { e.stopPropagation(); handleSetPrimary(img.id); }}
                  className="absolute top-1 left-1 w-4 h-4 rounded-full surface-card hover:bg-amber-500 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all"
                  title="Set as primary"
                >
                  <Star size={9} className="text-muted group-hover:text-[var(--ds-text)]" />
                </button>
            }
            <button
              onClick={e => { e.stopPropagation(); handleRemove(img.id); }}
              className="absolute -top-1.5 -right-1.5 bg-red-600 hover:bg-red-500 text-on-accent rounded-full w-5 h-5 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <X size={10} />
            </button>
          </div>
        ))}

        <label className={`w-20 h-20 rounded-lg border-2 border-dashed flex flex-col items-center justify-center cursor-pointer transition-colors gap-1 ${
          uploading ? "border-subtle opacity-50" : "border-subtle hover:border-[var(--ds-border)]"
        }`}>
          {uploading
            ? <div className="w-5 h-5 border-2 border-subtle border-t-transparent rounded-full animate-spin" />
            : <>
                <Camera size={18} className="text-faint" />
                <span className="text-xs text-faint">Add</span>
              </>
          }
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
            disabled={uploading}
          />
        </label>
      </div>

      {photos.length === 0 && !uploading && (
        <p className="text-xs text-faint mt-1">No photos yet — tap Add to attach one</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Discover Tab
// ---------------------------------------------------------------------------

function DiscoverTab({ userId }) {
  const [cuisines, setCuisines] = useState([]);
  const [tags, setTags] = useState([]);
  const [components, setComponents] = useState([]);
  const [filters, setFilters] = useState([]);
  const [results, setResults] = useState(null); // null = not yet run
  const [loading, setLoading] = useState(false);
  const [surprised, setSurprised] = useState(null);

  // Filter builder state
  const [addType, setAddType] = useState("cuisine");
  const [addMode, setAddMode] = useState("include");
  const [addValue, setAddValue] = useState("");
  const [componentSearch, setComponentSearch] = useState("");

  useEffect(() => {
    api("/cuisines").then(d => setCuisines(d.cuisines || [])).catch(() => {});
    api("/tags").then(d => setTags(d.tags || [])).catch(() => {});
    api("/components").then(d => setComponents(d.components || [])).catch(() => {});
  }, []);

  const runDiscover = useCallback(async (filterList) => {
    setLoading(true);
    setSurprised(null);
    try {
      const data = await api("/discover", {
        method: "POST",
        body: JSON.stringify({ filters: filterList }),
      });
      setResults(data.meals || []);
    } catch (e) {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const addFilter = () => {
    if (!addValue) return;
    const f = { type: addType, mode: addMode, value: addValue };
    const next = [...filters, f];
    setFilters(next);
    setAddValue("");
    setComponentSearch("");
    runDiscover(next);
  };

  const removeFilter = (i) => {
    const next = filters.filter((_, idx) => idx !== i);
    setFilters(next);
    if (next.length === 0) setResults(null);
    else runDiscover(next);
  };

  const clearAll = () => {
    setFilters([]);
    setResults(null);
    setSurprised(null);
  };

  const surpriseMe = async () => {
    setLoading(true);
    setSurprised(null);
    try {
      const data = await api("/discover/random", {
        method: "POST",
        body: JSON.stringify({ filters }),
      });
      setSurprised(data.meal || null);
      if (data.meal && !results) {
        const all = await api("/discover", {
          method: "POST",
          body: JSON.stringify({ filters }),
        });
        setResults(all.meals || []);
      }
    } catch (e) {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  const valueOptions = () => {
    if (addType === "cuisine") return cuisines.map(c => c.name);
    if (addType === "effort") return ["low", "medium", "high"];
    if (addType === "tag") return tags.map(t => t.name);
    return [];
  };

  const filteredComponents = components.filter(c =>
    !componentSearch || c.name.toLowerCase().includes(componentSearch.toLowerCase())
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Active filters */}
      {filters.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 p-3 surface-card rounded-lg border border-subtle">
          {filters.map((f, i) => (
            <TagChip
              key={i}
              label={`${f.mode === "include" ? "✓" : "✗"} ${f.type}: ${f.value}`}
              color={f.mode === "include" ? "green" : "red"}
              onRemove={() => removeFilter(i)}
            />
          ))}
          <button onClick={clearAll} className="text-xs text-faint hover:text-[var(--ds-text)] ml-auto">
            Clear all
          </button>
        </div>
      )}

      {/* Filter builder */}
      <div className="flex flex-wrap gap-2 items-end p-3 surface-card rounded-lg border border-subtle">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-faint">Mode</label>
          <div className="flex rounded overflow-hidden border border-subtle">
            {["include", "exclude"].map(m => (
              <button
                key={m}
                onClick={() => setAddMode(m)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  addMode === m
                    ? m === "include" ? "bg-green-700/60 text-green-200" : "bg-red-700/60 text-red-200"
                    : "surface-raised text-muted hover:bg-[var(--ds-raised)]"
                }`}
              >
                {m === "include" ? "✓ Include" : "✗ Exclude"}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-faint">Filter by</label>
          <select
            value={addType}
            onChange={e => { setAddType(e.target.value); setAddValue(""); setComponentSearch(""); }}
            className="surface-raised border border-subtle rounded px-2 py-1.5 text-sm text-default"
          >
            <option value="cuisine">Cuisine</option>
            <option value="effort">Effort</option>
            <option value="tag">Tag</option>
            <option value="component">Component</option>
          </select>
        </div>

        <div className="flex flex-col gap-1 min-w-40">
          <label className="text-xs text-faint">Value</label>
          {addType === "component" ? (
            <div className="relative">
              <input
                value={componentSearch}
                onChange={e => { setComponentSearch(e.target.value); setAddValue(e.target.value); }}
                placeholder="Search components..."
                className="surface-raised border border-subtle rounded px-2 py-1.5 text-sm text-default w-full"
              />
              {componentSearch && filteredComponents.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 surface-card border border-subtle rounded shadow-lg z-10 max-h-40 overflow-y-auto">
                  {filteredComponents.slice(0, 8).map(c => (
                    <div
                      key={c.id}
                      className="px-3 py-1.5 text-sm text-default hover:bg-[var(--ds-raised)] cursor-pointer"
                      onClick={() => { setComponentSearch(c.name); setAddValue(c.name); }}
                    >
                      {c.name} <span className="text-faint text-xs">({c.type})</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <select
              value={addValue}
              onChange={e => setAddValue(e.target.value)}
              className="surface-raised border border-subtle rounded px-2 py-1.5 text-sm text-default"
            >
              <option value="">— select —</option>
              {valueOptions().map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          )}
        </div>

        <button
          onClick={addFilter}
          disabled={!addValue}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-600/70 hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed text-on-accent text-sm rounded transition-colors"
        >
          <Plus size={14} /> Add Filter
        </button>

        <button
          onClick={surpriseMe}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-1.5 bg-purple-600/70 hover:bg-purple-600 disabled:opacity-40 text-on-accent text-sm rounded transition-colors ml-auto"
        >
          <Shuffle size={14} /> Surprise Me
        </button>
      </div>

      {/* Surprise result */}
      {surprised && (
        <div className="p-4 bg-purple-900/30 border border-purple-600/50 rounded-lg">
          <div className="text-xs text-purple-400 font-medium mb-1 flex items-center gap-1">
            <Shuffle size={12} /> TONIGHT'S PICK
          </div>
          <div className="text-xl font-bold text-default">{surprised.name}</div>
          <div className="flex items-center gap-2 mt-2">
            {surprised.cuisine && <TagChip label={surprised.cuisine} color="blue" />}
            <EffortBadge effort={surprised.effort} />
            {(surprised.tags || []).slice(0, 3).map(t => <TagChip key={t} label={t} />)}
          </div>
        </div>
      )}

      {/* Results */}
      {loading && (
        <div className="text-center text-faint py-8">Searching...</div>
      )}

      {!loading && results !== null && (
        <>
          <div className="text-xs text-faint">
            {results.length} meal{results.length !== 1 ? "s" : ""} match
            {results.length !== 1 ? "" : "es"} your filters
          </div>
          {results.length === 0 ? (
            <div className="text-center text-faint py-8">
              <AlertCircle size={32} className="mx-auto mb-2 opacity-40" />
              No meals match. Try relaxing your filters.
            </div>
          ) : (
            <div className="grid gap-2">
              {results.map(m => (
                <MealCard
                  key={m.id}
                  meal={m}
                  highlighted={surprised?.id === m.id}
                />
              ))}
            </div>
          )}
        </>
      )}

      {!loading && results === null && filters.length === 0 && (
        <div className="text-center text-faint py-12">
          <UtensilsCrossed size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Add filters above to narrow down the meal list,</p>
          <p className="text-sm">or hit <strong className="text-purple-400">Surprise Me</strong> for a random pick.</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Browse Tab
// ---------------------------------------------------------------------------

function BrowseTab({ onEditMeal, refreshKey }) {
  const [meals, setMeals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [effort, setEffort] = useState("");
  const [tags, setTags] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [localRefresh, setLocalRefresh] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (tag) params.set("tag", tag);
      if (effort) params.set("effort", effort);
      const data = await api(`?${params}`);
      setMeals(data.meals || []);
    } finally {
      setLoading(false);
    }
  }, [q, tag, effort]);

  useEffect(() => {
    api("/tag-cloud").then(d => setTags(d.tags || [])).catch(() => {});
  }, [localRefresh, refreshKey]);

  useEffect(() => { load(); }, [load, refreshKey, localRefresh]);


  return (
    <div className="flex flex-col gap-0">
      {/* Search + effort + new */}
      <div className="flex flex-wrap gap-2 items-center px-0 pb-2">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={q}
            onChange={e => { setQ(e.target.value); setTag(""); }}
            placeholder="Search meals..."
            className="w-full surface-card border border-subtle rounded px-3 py-1.5 pl-8 text-sm text-default"
          />
        </div>
        <div className="flex rounded overflow-hidden border border-subtle">
          {["", "low", "medium", "high"].map(e => (
            <button
              key={e}
              onClick={() => setEffort(e)}
              className={`px-2.5 py-1.5 text-xs transition-colors ${
                effort === e ? "surface-raised text-default" : "surface-card text-muted hover:bg-[var(--ds-raised)]"
              }`}
            >
              {e === "" ? "All" : e.charAt(0).toUpperCase() + e.slice(1)}
            </button>
          ))}
        </div>
        <button
          onClick={() => setLocalRefresh(r => r + 1)}
          className="flex items-center gap-1 px-2.5 py-1.5 surface-card hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] text-sm rounded border border-subtle transition-colors"
          title="Refresh meals and tags"
        >
          <RefreshCw size={14} />
        </button>
        <button
          onClick={() => window.open(`/meal-menu.html${tag ? "?tag=" + encodeURIComponent(tag) : ""}`, "_blank")}
          className="flex items-center gap-1 px-2.5 py-1.5 surface-card hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] text-sm rounded border border-subtle transition-colors"
          title="Export menu PDF"
        >
          <FileDown size={14} />
        </button>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-600/70 hover:bg-blue-600 text-on-accent text-sm rounded transition-colors"
        >
          <Plus size={14} /> New Meal
        </button>
      </div>

      {/* Tag cloud (cuisine is a tag now) */}
      {tags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 py-2 border-b border-subtle mb-2">
          <button
            onClick={() => setTag("")}
            className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
              !tag ? "bg-blue-600 text-on-accent" : "surface-card text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)]"
            }`}
          >
            All
          </button>
          {tags.map(t => (
            <button
              key={t.name}
              onClick={() => { setTag(tag === t.name ? "" : t.name); setQ(""); }}
              className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
                tag === t.name
                  ? "bg-blue-600 text-on-accent"
                  : "surface-card text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)]"
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {showAdd && (
        <AddMealForm
          onSave={async (data) => {
            await api("", { method: "POST", body: JSON.stringify(data) });
            setShowAdd(false);
            load();
          }}
          onCancel={() => setShowAdd(false)}
        />
      )}

      {loading ? (
        <div className="text-center text-faint py-8">Loading...</div>
      ) : meals.length === 0 ? (
        <div className="text-center text-faint py-8">No meals found.</div>
      ) : (
        <div className="grid gap-2">
          {meals.map(m => (
            <MealCard key={m.id} meal={m} onEdit={() => onEditMeal(m.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Meal Card
// ---------------------------------------------------------------------------

function MealCard({ meal, onEdit, highlighted = false }) {
  const thumb = meal.primary_photo ? imgSrc(meal.primary_photo) : null;
  return (
    <div
      onClick={onEdit}
      className={`flex items-center gap-3 p-3 rounded-lg border transition-colors ${
        onEdit ? "cursor-pointer" : ""
      } ${
        highlighted
          ? "bg-purple-900/20 border-purple-600/50 hover:border-purple-500/60"
          : "surface-card border-subtle hover:border-[var(--ds-border)] hover:bg-[var(--ds-card)]"
      }`}
    >
      {/* Photo thumbnail */}
      <div className="shrink-0 w-14 h-14 rounded-lg overflow-hidden border border-subtle">
        {thumb
          ? <img src={thumb} alt="" className="w-full h-full object-cover" />
          : <div className="w-full h-full surface-card flex items-center justify-center">
              <Camera size={18} className="text-default" />
            </div>
        }
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-default truncate">{meal.name}</span>
          <EffortBadge effort={meal.effort} />
          {meal.rating && <StarRating value={meal.rating} readonly />}
        </div>
        {meal.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {meal.tags.slice(0, 5).map(t => <TagChip key={t} label={t} />)}
            {meal.tags.length > 5 && <span className="text-xs text-faint">+{meal.tags.length - 5}</span>}
          </div>
        )}
      </div>
      {onEdit && <ChevronRight size={16} className="text-faint shrink-0" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Meal Detail / Edit
// ---------------------------------------------------------------------------

function MealDetailView({ mealId, onBack, onSaved, userId }) {
  const [meal, setMeal] = useState(null);
  const [editing, setEditing] = useState(false);
  const [allTags, setAllTags] = useState([]);
  const [allComponents, setAllComponents] = useState([]);
  const [form, setForm] = useState({});
  const [compLinks, setCompLinks] = useState([]);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [compSearch, setCompSearch] = useState("");
  const [showCompSearch, setShowCompSearch] = useState(false);

  const load = useCallback(async () => {
    const [mealData, tagData, compData] = await Promise.all([
      api(`/${mealId}`),
      api("/tags"),
      api("/components"),
    ]);
    setMeal(mealData);
    setForm(mealData);
    setCompLinks(mealData.components || []);
    setAllTags(tagData.tags || []);
    setAllComponents(compData.components || []);
  }, [mealId]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await api(`/${mealId}`, { method: "PUT", body: JSON.stringify(form) });
      await api(`/${mealId}/components`, {
        method: "PUT",
        body: JSON.stringify({ components: compLinks }),
      });
      setEditing(false);
      await load();
      onSaved && onSaved();
    } finally {
      setSaving(false);
    }
  };

  const deleteMeal = async () => {
    if (!meal) return;
    const ok = confirm(
      `Delete "${meal.name}"?\n\nThis will remove the meal from the library. Any meal log entries will stay, but their link to this meal will be cleared. This cannot be undone.`
    );
    if (!ok) return;

    setDeleting(true);
    try {
      await api(`/${mealId}`, { method: "DELETE" });
      onSaved && onSaved();
      onBack && onBack();
    } catch (e) {
      alert(e?.detail || e?.message || "Failed to delete meal");
    } finally {
      setDeleting(false);
    }
  };

  const deleteComp = (idx) => setCompLinks(compLinks.filter((_, i) => i !== idx));

  const addCompLink = (comp) => {
    if (compLinks.find(c => c.component_id === comp.id)) return;
    setCompLinks([...compLinks, {
      component_id: comp.id,
      component_name: comp.name,
      component_type: comp.type,
      role: "side",
      sort_order: compLinks.length,
      notes: "",
    }]);
    setCompSearch("");
    setShowCompSearch(false);
  };

  const updateCompLink = (idx, field, value) => {
    const next = [...compLinks];
    next[idx] = { ...next[idx], [field]: value };
    setCompLinks(next);
  };

  if (!meal) return <div className="text-faint text-sm py-8 text-center">Loading...</div>;

  const toggleTag = (tagName) => {
    const tags = form.tags || [];
    setForm(f => ({
      ...f,
      tags: tags.includes(tagName) ? tags.filter(t => t !== tagName) : [...tags, tagName],
    }));
  };

  const filteredComps = allComponents.filter(c =>
    compSearch && c.name.toLowerCase().includes(compSearch.toLowerCase()) &&
    !compLinks.find(l => l.component_id === c.id)
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <button onClick={onBack} className="text-faint hover:text-[var(--ds-text)] text-sm flex items-center gap-1">
          ← Back
        </button>
        <div className="flex-1" />
        <button
          onClick={deleteMeal}
          disabled={deleting || saving}
          className="flex items-center gap-1 px-3 py-1.5 text-sm bg-red-600/20 hover:bg-red-600/30 text-red-300 rounded transition-colors disabled:opacity-50"
          title="Delete meal"
        >
          <Trash2 size={13} /> {deleting ? "Deleting..." : "Delete"}
        </button>
        {!editing ? (
          <button onClick={() => setEditing(true)} className="flex items-center gap-1 px-3 py-1.5 text-sm surface-raised hover:bg-[var(--ds-raised)] text-default rounded transition-colors">
            <Pencil size={13} /> Edit
          </button>
        ) : (
          <div className="flex gap-2">
            <button onClick={() => { setEditing(false); setForm(meal); setCompLinks(meal.components || []); }} className="px-3 py-1.5 text-sm text-muted hover:text-[var(--ds-text)]">
              Cancel
            </button>
            <button onClick={save} disabled={saving} className="flex items-center gap-1 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-on-accent rounded disabled:opacity-50">
              <Check size={13} /> {saving ? "Saving..." : "Save"}
            </button>
          </div>
        )}
      </div>

      {/* Name */}
      {editing ? (
        <input
          value={form.name || ""}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          className="text-2xl font-bold bg-transparent border-b border-subtle text-default outline-none pb-1 w-full"
        />
      ) : (
        <h2 className="text-2xl font-bold text-default">{meal.name}</h2>
      )}

      {/* Meta row */}
      <div className="flex flex-wrap gap-3 items-center">
        {editing ? (
          <>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-faint">Effort</label>
              <div className="flex rounded overflow-hidden border border-subtle">
                {["low", "medium", "high"].map(e => (
                  <button
                    key={e}
                    onClick={() => setForm(f => ({ ...f, effort: e }))}
                    className={`px-3 py-1 text-xs transition-colors ${
                      form.effort === e ? "surface-raised text-default" : "surface-raised text-muted hover:bg-[var(--ds-raised)]"
                    }`}
                  >
                    {e.charAt(0).toUpperCase() + e.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-faint">Rating</label>
              <StarRating
                value={form.rating}
                onChange={v => setForm(f => ({ ...f, rating: v }))}
              />
            </div>
          </>
        ) : (
          <>
            <EffortBadge effort={meal.effort} />
            {meal.rating && <StarRating value={meal.rating} readonly />}
          </>
        )}
      </div>

      {/* Description */}
      <div>
        <label className="text-xs text-faint block mb-1">Description</label>
        {editing ? (
          <input
            value={form.description || ""}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="Brief description..."
            className="w-full surface-card border border-subtle rounded px-3 py-1.5 text-sm text-default"
          />
        ) : (
          meal.description && <p className="text-sm text-default">{meal.description}</p>
        )}
      </div>

      {/* Tags */}
      <div>
        <label className="text-xs text-faint block mb-1.5 flex items-center gap-1"><Tag size={11} /> Tags</label>
        {editing ? (
          <div className="flex flex-wrap gap-1.5">
            {allTags.map(t => (
              <button
                key={t.name}
                onClick={() => toggleTag(t.name)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  (form.tags || []).includes(t.name)
                    ? "bg-blue-700/50 text-blue-200 border-blue-600/50"
                    : "surface-raised text-muted border-subtle hover:border-[var(--ds-border)]"
                }`}
              >
                {t.name}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {(meal.tags || []).length === 0
              ? <span className="text-xs text-faint">No tags</span>
              : (meal.tags || []).map(t => <TagChip key={t} label={t} />)}
          </div>
        )}
      </div>

      {/* Components */}
      <div>
        <label className="text-xs text-faint block mb-1.5 flex items-center gap-1"><Boxes size={11} /> Components</label>
        <div className="flex flex-col gap-1.5">
          {compLinks.map((c, i) => (
            <div key={i} className="flex items-center gap-2 p-2 surface-card rounded border border-subtle">
              <div className="flex-1">
                <span className="text-sm text-default font-medium">{c.component_name}</span>
                {c.component_type && <span className="text-xs text-faint ml-2">({c.component_type})</span>}
                {c.component_recipe_id && (
                  <span className="text-xs text-blue-400 ml-2 flex items-center gap-1 inline-flex">
                    <BookOpen size={10} /> has recipe
                  </span>
                )}
              </div>
              {editing ? (
                <>
                  <select
                    value={c.role}
                    onChange={e => updateCompLink(i, "role", e.target.value)}
                    className="surface-raised border border-subtle rounded px-2 py-0.5 text-xs text-default"
                  >
                    {["main", "side", "sauce", "garnish", "other"].map(r => (
                      <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
                    ))}
                  </select>
                  <input
                    value={c.notes}
                    onChange={e => updateCompLink(i, "notes", e.target.value)}
                    placeholder="notes..."
                    className="surface-raised border border-subtle rounded px-2 py-0.5 text-xs text-default w-28"
                  />
                  <button onClick={() => deleteComp(i)} className="text-red-500 hover:text-red-400">
                    <Trash2 size={13} />
                  </button>
                </>
              ) : (
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  c.role === "main" ? "bg-blue-900/40 text-blue-300" :
                  c.role === "sauce" ? "bg-amber-900/40 text-amber-300" :
                  "surface-raised text-muted"
                }`}>
                  {c.role}
                </span>
              )}
            </div>
          ))}

          {editing && (
            <div className="relative">
              <input
                value={compSearch}
                onChange={e => { setCompSearch(e.target.value); setShowCompSearch(true); }}
                onFocus={() => setShowCompSearch(true)}
                placeholder="Add component..."
                className="w-full surface-card border border-dashed border-subtle rounded px-3 py-1.5 text-sm text-muted placeholder-zinc-600"
              />
              {showCompSearch && filteredComps.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 surface-card border border-subtle rounded shadow-lg z-10 max-h-40 overflow-y-auto">
                  {filteredComps.slice(0, 8).map(c => (
                    <div
                      key={c.id}
                      className="px-3 py-1.5 text-sm text-default hover:bg-[var(--ds-raised)] cursor-pointer"
                      onClick={() => addCompLink(c)}
                    >
                      {c.name} <span className="text-faint text-xs">({c.type})</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Notes */}
      <div>
        <label className="text-xs text-faint block mb-1">Notes</label>
        {editing ? (
          <textarea
            value={form.notes || ""}
            onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
            rows={3}
            placeholder="Any notes..."
            className="w-full surface-card border border-subtle rounded px-3 py-2 text-sm text-default resize-none"
          />
        ) : (
          meal.notes && <p className="text-sm text-default">{meal.notes}</p>
        )}
      </div>

      {/* Photos */}
      <div>
        <label className="text-xs text-faint block mb-2 flex items-center gap-1"><ImageIcon size={11} /> Photos</label>
        <MealPhotoStrip
          mealId={mealId}
          initialPhotos={meal.photos || []}
          userId={userId}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Meal Form
// ---------------------------------------------------------------------------

function AddMealForm({ onSave, onCancel }) {
  const [form, setForm] = useState({ name: "", effort: "medium", tags: [], description: "" });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      await onSave(form);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 surface-card rounded-lg border border-subtle">
      <div className="text-sm font-medium text-default mb-3">New Meal</div>
      <div className="flex flex-wrap gap-3">
        <input
          autoFocus
          value={form.name}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          placeholder="Meal name *"
          className="flex-1 min-w-48 surface-raised border border-subtle rounded px-3 py-1.5 text-sm text-default"
        />
        <div className="flex rounded overflow-hidden border border-subtle">
          {["low", "medium", "high"].map(e => (
            <button
              key={e}
              onClick={() => setForm(f => ({ ...f, effort: e }))}
              className={`px-2.5 py-1.5 text-xs transition-colors ${
                form.effort === e ? "surface-raised text-default" : "surface-raised text-muted hover:bg-[var(--ds-raised)]"
              }`}
            >
              {e.charAt(0).toUpperCase() + e.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-2 mt-3 justify-end">
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button
          onClick={save}
          disabled={!form.name.trim() || saving}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-on-accent rounded"
        >
          {saving ? "Adding..." : "Add Meal"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Components Tab
// ---------------------------------------------------------------------------

function ComponentsTab() {
  const [components, setComponents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState(null);

  const TYPES = ["protein", "starch", "vegetable", "sauce", "grain", "bread", "dairy", "fruit", "other"];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api(`/components?q=${encodeURIComponent(q)}&type=${typeFilter}`);
      setComponents(data.components || []);
    } finally {
      setLoading(false);
    }
  }, [q, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const deleteComp = async (id) => {
    if (!confirm("Delete this component? It will be removed from all meals.")) return;
    await api(`/components/${id}`, { method: "DELETE" });
    load();
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search components..."
            className="w-full surface-card border border-subtle rounded px-3 py-1.5 pl-8 text-sm text-default"
          />
        </div>
        <select
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
          className="surface-card border border-subtle rounded px-2 py-1.5 text-sm text-default"
        >
          <option value="">All types</option>
          {TYPES.map(t => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
        </select>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-600/70 hover:bg-blue-600 text-on-accent text-sm rounded transition-colors ml-auto"
        >
          <Plus size={14} /> New Component
        </button>
      </div>

      {showAdd && (
        <AddComponentForm
          onSave={async (data) => {
            await api("/components", { method: "POST", body: JSON.stringify(data) });
            setShowAdd(false);
            load();
          }}
          onCancel={() => setShowAdd(false)}
        />
      )}

      {loading ? (
        <div className="text-center text-faint py-8">Loading...</div>
      ) : components.length === 0 ? (
        <div className="text-center text-faint py-8">No components found.</div>
      ) : (
        <div className="grid gap-1.5">
          {components.map(c => (
            <div key={c.id} className="flex items-center gap-3 p-2.5 surface-card rounded border border-subtle hover:border-[var(--ds-border)] group">
              {editing === c.id ? (
                <EditComponentInline
                  component={c}
                  onSave={async (data) => {
                    await api(`/components/${c.id}`, { method: "PUT", body: JSON.stringify(data) });
                    setEditing(null);
                    load();
                  }}
                  onCancel={() => setEditing(null)}
                />
              ) : (
                <>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-default text-sm">{c.name}</span>
                      <span className="text-xs text-faint surface-raised px-1.5 py-0.5 rounded">{c.type}</span>
                      {c.recipe_id && (
                        <span className="text-xs text-blue-400 flex items-center gap-0.5">
                          <BookOpen size={10} /> recipe linked
                        </span>
                      )}
                    </div>
                    {c.tags?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {c.tags.map(t => <TagChip key={t} label={t} />)}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => setEditing(c.id)} className="p-1 text-faint hover:text-[var(--ds-text)]">
                      <Pencil size={13} />
                    </button>
                    <button onClick={() => deleteComp(c.id)} className="p-1 text-faint hover:text-red-400">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AddComponentForm({ onSave, onCancel }) {
  const TYPES = ["protein", "starch", "vegetable", "sauce", "grain", "bread", "dairy", "fruit", "other"];
  const [form, setForm] = useState({ name: "", type: "other", description: "", recipe_id: "" });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      await onSave({ ...form, recipe_id: form.recipe_id || null });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-3 surface-card rounded-lg border border-subtle">
      <div className="flex flex-wrap gap-2">
        <input
          autoFocus
          value={form.name}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          placeholder="Component name *"
          className="flex-1 min-w-48 surface-raised border border-subtle rounded px-3 py-1.5 text-sm text-default"
        />
        <select
          value={form.type}
          onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
          className="surface-raised border border-subtle rounded px-2 py-1.5 text-sm text-default"
        >
          {TYPES.map(t => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
        </select>
        <input
          value={form.recipe_id}
          onChange={e => setForm(f => ({ ...f, recipe_id: e.target.value }))}
          placeholder="Recipe ID (re-...)"
          className="surface-raised border border-subtle rounded px-3 py-1.5 text-sm text-default w-36"
        />
      </div>
      <div className="flex gap-2 mt-2 justify-end">
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button
          onClick={save}
          disabled={!form.name.trim() || saving}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-on-accent rounded"
        >
          {saving ? "Adding..." : "Add"}
        </button>
      </div>
    </div>
  );
}

function EditComponentInline({ component, onSave, onCancel }) {
  const TYPES = ["protein", "starch", "vegetable", "sauce", "grain", "bread", "dairy", "fruit", "other"];
  const [form, setForm] = useState({
    name: component.name,
    type: component.type,
    description: component.description,
    recipe_id: component.recipe_id || "",
  });

  return (
    <div className="flex flex-wrap gap-2 flex-1">
      <input
        value={form.name}
        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
        className="flex-1 min-w-32 surface-raised border border-subtle rounded px-2 py-1 text-sm text-default"
      />
      <select
        value={form.type}
        onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
        className="surface-raised border border-subtle rounded px-2 py-1 text-sm text-default"
      >
        {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
      </select>
      <input
        value={form.recipe_id}
        onChange={e => setForm(f => ({ ...f, recipe_id: e.target.value }))}
        placeholder="Recipe ID"
        className="surface-raised border border-subtle rounded px-2 py-1 text-sm text-default w-28"
      />
      <button onClick={() => onSave({ ...form, recipe_id: form.recipe_id || null })} className="text-green-400 hover:text-green-300">
        <Check size={14} />
      </button>
      <button onClick={onCancel} className="text-faint hover:text-[var(--ds-text)]">
        <X size={14} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manage Tab (Cuisines + Tags)
// ---------------------------------------------------------------------------

function ManageTab() {
  const [cuisines, setCuisines] = useState([]);
  const [tags, setTags] = useState([]);
  const [newCuisine, setNewCuisine] = useState("");
  const [newTag, setNewTag] = useState("");
  const [editingCuisine, setEditingCuisine] = useState(null);
  const [editCuisineName, setEditCuisineName] = useState("");

  const loadCuisines = () => api("/cuisines").then(d => setCuisines(d.cuisines || [])).catch(() => {});
  const loadTags = () => api("/tags?with_counts=true").then(d => setTags(d.tags || [])).catch(() => {});

  useEffect(() => { loadCuisines(); loadTags(); }, []);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {/* Cuisines */}
      <div>
        <h3 className="text-sm font-semibold text-default mb-3 flex items-center gap-1.5">
          <Globe size={14} /> Cuisines
        </h3>
        <div className="flex gap-2 mb-3">
          <input
            value={newCuisine}
            onChange={e => setNewCuisine(e.target.value)}
            placeholder="New cuisine..."
            className="flex-1 surface-card border border-subtle rounded px-2 py-1.5 text-sm text-default"
            onKeyDown={e => {
              if (e.key === "Enter" && newCuisine.trim()) {
                api("/cuisines", { method: "POST", body: JSON.stringify({ name: newCuisine.trim() }) })
                  .then(() => { setNewCuisine(""); loadCuisines(); });
              }
            }}
          />
          <button
            disabled={!newCuisine.trim()}
            onClick={() => {
              api("/cuisines", { method: "POST", body: JSON.stringify({ name: newCuisine.trim() }) })
                .then(() => { setNewCuisine(""); loadCuisines(); });
            }}
            className="px-2.5 py-1.5 bg-blue-600/70 hover:bg-blue-600 disabled:opacity-40 text-on-accent text-sm rounded"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="flex flex-col gap-1">
          {cuisines.map(c => (
            <div key={c.id} className="flex items-center gap-2 px-2.5 py-1.5 surface-card rounded border border-subtle group">
              {editingCuisine === c.id ? (
                <>
                  <input
                    value={editCuisineName}
                    onChange={e => setEditCuisineName(e.target.value)}
                    className="flex-1 surface-raised border border-subtle rounded px-2 py-0.5 text-sm text-default"
                  />
                  <button
                    onClick={() => {
                      api(`/cuisines/${c.id}`, { method: "PUT", body: JSON.stringify({ name: editCuisineName }) })
                        .then(() => { setEditingCuisine(null); loadCuisines(); });
                    }}
                    className="text-green-400 hover:text-green-300"
                  ><Check size={13} /></button>
                  <button onClick={() => setEditingCuisine(null)} className="text-faint hover:text-[var(--ds-text)]">
                    <X size={13} />
                  </button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-sm text-default">{c.name}</span>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => { setEditingCuisine(c.id); setEditCuisineName(c.name); }} className="text-faint hover:text-[var(--ds-text)]">
                      <Pencil size={12} />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete cuisine "${c.name}"?`))
                          api(`/cuisines/${c.id}`, { method: "DELETE" }).then(loadCuisines);
                      }}
                      className="text-faint hover:text-red-400"
                    ><Trash2 size={12} /></button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Tags */}
      <div>
        <h3 className="text-sm font-semibold text-default mb-3 flex items-center gap-1.5">
          <Tag size={14} /> Tags
        </h3>
        <div className="flex gap-2 mb-3">
          <input
            value={newTag}
            onChange={e => setNewTag(e.target.value)}
            placeholder="New tag..."
            className="flex-1 surface-card border border-subtle rounded px-2 py-1.5 text-sm text-default"
            onKeyDown={e => {
              if (e.key === "Enter" && newTag.trim()) {
                api("/tags", { method: "POST", body: JSON.stringify({ name: newTag.trim() }) })
                  .then(() => { setNewTag(""); loadTags(); });
              }
            }}
          />
          <button
            disabled={!newTag.trim()}
            onClick={() => {
              api("/tags", { method: "POST", body: JSON.stringify({ name: newTag.trim() }) })
                .then(() => { setNewTag(""); loadTags(); });
            }}
            className="px-2.5 py-1.5 bg-blue-600/70 hover:bg-blue-600 disabled:opacity-40 text-on-accent text-sm rounded"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {tags.map(t => (
            <div key={t.id} className="flex items-center gap-1 surface-card border border-subtle rounded-full px-2.5 py-0.5 group">
              <span className="text-xs text-default">{t.name}</span>
              {t.usage_count > 0 && <span className="text-xs text-faint">({t.usage_count})</span>}
              <button
                onClick={() => {
                  if (confirm(`Delete tag "${t.name}"?`))
                    api(`/tags/${t.id}`, { method: "DELETE" }).then(loadTags);
                }}
                className="opacity-0 group-hover:opacity-100 text-faint hover:text-red-400 transition-opacity ml-0.5"
              >
                <X size={10} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Meal Log Tab
// ---------------------------------------------------------------------------

const MEAL_TYPE_STYLES = {
  dinner:    "bg-indigo-900/50 text-indigo-300 border border-indigo-700/50",
  lunch:     "bg-amber-900/50  text-amber-300  border border-amber-700/50",
  breakfast: "bg-orange-900/50 text-orange-300 border border-orange-700/50",
  snack:     "bg-green-900/50  text-green-300  border border-green-700/50",
};

function MealLogTab() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [typeFilter, setTypeFilter] = useState("");

  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = `days=${days}${typeFilter ? `&meal_type=${typeFilter}` : ""}`;
      const data = await api(`/meal-log?${qs}`);
      setEntries(data.entries || []);
    } catch (e) {
      setError(e?.detail || e?.message || "Failed to load meal log");
    } finally {
      setLoading(false);
    }
  }, [days, typeFilter]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-default flex items-center gap-2">
          <CalendarDays size={15} className="text-indigo-400" />
          Meal Log
        </h2>
        <div className="flex items-center gap-2">
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="text-xs surface-card border border-subtle rounded px-2 py-1 text-default"
          >
            <option value="">All meals</option>
            <option value="dinner">Dinner</option>
            <option value="lunch">Lunch</option>
            <option value="breakfast">Breakfast</option>
            <option value="snack">Snack</option>
          </select>
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="text-xs surface-card border border-subtle rounded px-2 py-1 text-default"
          >
            {[14, 30, 60, 90].map(d => <option key={d} value={d}>{d} days</option>)}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-16 text-faint">
          <AlertCircle size={36} className="text-red-600 mb-3" />
          <p className="text-sm font-medium text-red-400">Could not load meal log</p>
          <p className="text-xs mt-1 text-faint">{error}</p>
        </div>
      ) : entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-faint">
          <CalendarDays size={36} className="text-default mb-3" />
          <p className="text-sm font-medium text-muted">No meals logged yet</p>
          <p className="text-xs mt-1 text-faint">Tell Skipper what you had for dinner or lunch to get started</p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map(e => <MealLogEntry key={e.id} entry={e} />)}
        </div>
      )}
    </div>
  );
}

function MealLogEntry({ entry }) {
  const date = new Date(entry.logged_date + "T12:00:00");
  const dateStr = date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  const typeCls = MEAL_TYPE_STYLES[entry.meal_type] || MEAL_TYPE_STYLES.dinner;

  return (
    <div className="surface-card border border-subtle rounded-lg p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-muted">{dateStr}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium capitalize ${typeCls}`}>
              {entry.meal_type}
            </span>
            {entry.meal_name && (
              <span className="text-xs surface-raised text-default rounded px-1.5 py-0.5">
                {entry.meal_name}
              </span>
            )}
          </div>
          <p className="text-sm text-default">{entry.description}</p>
          {entry.notes && (
            <p className="text-xs text-faint mt-1 italic">{entry.notes}</p>
          )}
        </div>
        <UtensilsCrossed size={14} className="text-faint shrink-0 mt-0.5" />
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Root App
// ---------------------------------------------------------------------------

export default function MealsApp({ userId }) {
  const [tab, setTab] = useState("browse");
  const [editingMealId, setEditingMealId] = useState(null);
  const [browseRefreshKey, setBrowseRefreshKey] = useState(0);

  useEffect(() => {
    const es = new EventSource(`${API}/events`);
    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        if (event.type === "meal_created") {
          setTab("browse");
          setBrowseRefreshKey(k => k + 1);
          setEditingMealId(event.id);
        }
      } catch {}
    };
    return () => es.close();
  }, []);

  const tabs = [
    { id: "browse",     label: "Browse" },
    { id: "meal-log",   label: "Meal Log" },
    { id: "discover",   label: "Discover" },
    { id: "components", label: "Components" },
    { id: "manage",     label: "Manage" },
  ];

  if (editingMealId) {
    return (
      <div className="flex flex-col h-full overflow-y-auto p-4">
        <MealDetailView
          mealId={editingMealId}
          onBack={() => setEditingMealId(null)}
          onSaved={() => setBrowseRefreshKey(k => k + 1)}
          userId={userId}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-subtle px-4 shrink-0">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-faint hover:text-[var(--ds-text)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4">
        {tab === "discover" && <DiscoverTab userId={userId} />}
        {tab === "browse" && (
          <BrowseTab
            onEditMeal={(id) => setEditingMealId(id)}
            refreshKey={browseRefreshKey}
          />
        )}
        {tab === "meal-log" && <MealLogTab />}
        {tab === "components" && <ComponentsTab />}
        {tab === "manage" && <ManageTab />}
      </div>
    </div>
  );
}
