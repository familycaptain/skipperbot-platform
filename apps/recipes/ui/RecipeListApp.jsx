import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search, Plus, Star, Clock, ChefHat, Tag, X, Edit3, Loader2, Filter,
} from "lucide-react";

/**
 * Recipe List App — singleton for browsing, searching, and creating recipes.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 */
export default function RecipeListApp({ appId, userId, context = {}, onOpenApp, refreshKey, isActive }) {
  const [recipes, setRecipes] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState("");
  const [showCategoryEditor, setShowCategoryEditor] = useState(false);
  const [newCatName, setNewCatName] = useState("");

  const loadRecipes = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery.trim()) params.set("q", searchQuery.trim());
      else if (activeCategory) params.set("category", activeCategory);
      const res = await fetch(`/api/apps/recipes?${params}`);
      if (res.ok) {
        const data = await res.json();
        setRecipes(data.recipes || []);
      }
    } catch {}
    setLoading(false);
  }, [searchQuery, activeCategory]);

  const loadCategories = useCallback(async () => {
    try {
      const res = await fetch("/api/apps/recipes/categories");
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories || []);
      }
    } catch {}
  }, []);

  useEffect(() => { loadRecipes(); }, [loadRecipes]);
  useEffect(() => { loadCategories(); }, []);

  // Auto-refresh from chat mutations
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadRecipes();
    loadCategories();
  }, [refreshKey]);

  // Reload when tab becomes active (e.g. after saving a recipe in detail view)
  const wasActive = useRef(isActive);
  useEffect(() => {
    if (isActive && !wasActive.current) {
      loadRecipes();
      loadCategories();
    }
    wasActive.current = isActive;
  }, [isActive, loadRecipes, loadCategories]);

  function openRecipe(recipe) {
    onOpenApp?.("recipe", { recipeId: recipe.id, title: recipe.title });
  }

  async function handleCreateRecipe() {
    try {
      const res = await fetch("/api/apps/recipes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New Recipe", created_by: userId }),
      });
      if (res.ok) {
        const recipe = await res.json();
        onOpenApp?.("recipe", { recipeId: recipe.id, title: recipe.title, editing: true });
        loadRecipes();
      }
    } catch {}
  }

  async function handleCreateCategory(e) {
    e.preventDefault();
    if (!newCatName.trim()) return;
    try {
      await fetch("/api/apps/recipes/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newCatName.trim() }),
      });
      setNewCatName("");
      loadCategories();
    } catch {}
  }

  async function handleDeleteCategory(catId) {
    try {
      await fetch(`/api/apps/recipes/categories/${catId}`, { method: "DELETE" });
      if (activeCategory === categories.find(c => c.id === catId)?.name) {
        setActiveCategory("");
      }
      loadCategories();
    } catch {}
  }

  function formatTime(mins) {
    if (!mins) return null;
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m > 0 ? `${h}h ${m}m` : `${h}h`;
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
              placeholder="Search recipes..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setActiveCategory(""); }}
              className="w-full bg-slate-800/60 text-sm text-white pl-7 pr-2 py-1 rounded border border-slate-700 outline-none focus:border-indigo-500"
            />
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowCategoryEditor(!showCategoryEditor)}
            className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
              showCategoryEditor ? "bg-indigo-600 text-white" : "text-slate-400 hover:bg-slate-700 hover:text-white"
            }`}
          >
            <Tag size={12} /> Categories
          </button>
          <button
            onClick={handleCreateRecipe}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded transition-colors"
          >
            <Plus size={12} /> New
          </button>
        </div>
      </div>

      {/* Category filter bar — always visible */}
      {!showCategoryEditor && (
        <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 bg-slate-900/20 border-b border-slate-800/50 shrink-0">
          <button
            onClick={() => setActiveCategory("")}
            className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
              !activeCategory ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            All
          </button>
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => { setActiveCategory(cat.name); setSearchQuery(""); }}
              className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors flex items-center gap-1 ${
                activeCategory === cat.name
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
              }`}
            >
              {cat.name}
              {activeCategory === cat.name && (
                <X size={10} className="opacity-70 hover:opacity-100" onClick={(e) => { e.stopPropagation(); setActiveCategory(""); }} />
              )}
            </button>
          ))}
          {categories.length === 0 && (
            <span className="text-xs text-slate-600 italic">No categories yet</span>
          )}
        </div>
      )}

      {/* Category editor */}
      {showCategoryEditor && (
        <div className="px-3 py-2 bg-slate-900/40 border-b border-slate-800 space-y-2">
          <div className="flex flex-wrap gap-1">
            {categories.map((cat) => (
              <span key={cat.id} className="flex items-center gap-1 px-2 py-0.5 bg-slate-800 rounded-full text-xs text-slate-300">
                {cat.name}
                <button onClick={() => handleDeleteCategory(cat.id)} className="hover:text-red-400 transition-colors">
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
          <form onSubmit={handleCreateCategory} className="flex items-center gap-1">
            <input
              value={newCatName}
              onChange={(e) => setNewCatName(e.target.value)}
              placeholder="New category..."
              className="bg-slate-800 text-white text-xs px-2 py-1 rounded border border-slate-700 outline-none flex-1 max-w-[200px]"
            />
            <button type="submit" className="px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded">Add</button>
          </form>
        </div>
      )}

      {/* Recipe list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading && recipes.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-400">
            <Loader2 size={18} className="animate-spin mr-2" /> Loading recipes...
          </div>
        ) : recipes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500 text-sm">
            <ChefHat size={32} className="mb-2 opacity-40" />
            {searchQuery ? "No recipes match your search." : "No recipes yet. Click + New to create one!"}
          </div>
        ) : (
          recipes.map((recipe) => (
            <button
              key={recipe.id}
              onClick={() => openRecipe(recipe)}
              className="w-full text-left bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/50 hover:border-slate-600 rounded-lg p-3 transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-medium text-white truncate group-hover:text-indigo-300 transition-colors">
                    {recipe.title || "Untitled"}
                  </h3>
                  {recipe.description && (
                    <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{recipe.description}</p>
                  )}
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500">
                    {recipe.prep_time_min != null && recipe.cook_time_min != null && (
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
                        {formatTime((recipe.prep_time_min || 0) + (recipe.cook_time_min || 0))}
                      </span>
                    )}
                    {recipe.servings > 0 && (
                      <span>{recipe.servings} serving{recipe.servings !== 1 ? "s" : ""}</span>
                    )}
                    {recipe.categories?.length > 0 && (
                      <span className="flex items-center gap-1">
                        {recipe.categories.slice(0, 3).map((c) => (
                          <span key={c} className="px-1.5 py-0 bg-slate-700/50 rounded text-[10px]">{c}</span>
                        ))}
                      </span>
                    )}
                  </div>
                </div>
                {recipe.rating && (
                  <div className="flex items-center gap-0.5 shrink-0">
                    {[1, 2, 3, 4, 5].map((s) => (
                      <Star
                        key={s}
                        size={12}
                        className={s <= recipe.rating ? "text-amber-400 fill-amber-400" : "text-slate-600"}
                      />
                    ))}
                  </div>
                )}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
