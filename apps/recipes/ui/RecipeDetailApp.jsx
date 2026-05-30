import { useState, useEffect, useCallback, useRef } from "react";
import {
  Star, Clock, Users, Edit3, Save, Trash2, ArrowLeft, Plus, X,
  Camera, ChefHat, Loader2, RotateCcw, Eye, Minus, Image as ImageIcon,
  ChevronUp, ChevronDown, Printer,
} from "lucide-react";

/**
 * Recipe Detail App — singleton for viewing/editing a single recipe.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 * Context: { recipeId, editing? }
 */

const SCALE_OPTIONS = [0.5, 1, 1.5, 2, 3, 4];

function ChefCommentsField({ value, onSave, onChange }) {
  const [local, setLocal] = useState(value);
  const [saved, setSaved] = useState(false);
  const dirty = local !== value;

  useEffect(() => { setLocal(value); }, [value]);

  async function handleSave() {
    await onSave(local);
    onChange(local);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-white flex items-center gap-1">
          <ChefHat size={14} /> Chef Comments
        </h2>
        {saved && <span className="text-xs text-emerald-400">Saved ✓</span>}
        {dirty && !saved && (
          <button onClick={handleSave}
            className="flex items-center gap-1 px-2 py-0.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded">
            <Save size={11} /> Save
          </button>
        )}
      </div>
      <textarea
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        rows={3}
        placeholder="Observations, proposed changes for next time..."
        className="w-full bg-slate-800/50 text-sm text-slate-300 px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500 resize-none"
      />
    </div>
  );
}

export default function RecipeDetailApp({ appId, userId, context = {}, onTitle, onOpenApp, refreshKey }) {
  const [recipe, setRecipe] = useState(null);
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(!!context.editing);
  const [scale, setScale] = useState(1);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [categories, setCategories] = useState([]);

  // Edit form state
  const [form, setForm] = useState({});
  const fileInputRef = useRef(null);

  const recipeId = context.recipeId || null;

  const loadRecipe = useCallback(async (id) => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/apps/recipes/${id}`);
      if (res.ok) {
        let data = await res.json();

        // Auto-reset checked items if last checked > 24 hours ago (each list independently)
        const isStale = (ts) => !ts || (Date.now() - new Date(ts).getTime()) > 24 * 60 * 60 * 1000;
        const stalePatch = {};
        if (data.checked_ingredients?.length > 0 && isStale(data.checked_ingredients_at))
          stalePatch.checked_ingredients = [];
        if (data.checked_steps?.length > 0 && isStale(data.checked_steps_at))
          stalePatch.checked_steps = [];
        if (Object.keys(stalePatch).length > 0) {
          await fetch(`/api/apps/recipes/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(stalePatch),
          });
          data = { ...data, ...stalePatch };
        }

        setRecipe(data);
        setImages(data.images || []);
        onTitle?.(data.title || "Recipe");
        setForm(buildForm(data));
      }
    } catch {}
    setLoading(false);
  }, [onTitle]);

  const loadCategories = useCallback(async () => {
    try {
      const res = await fetch("/api/apps/recipes/categories");
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories || []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (recipeId) {
      loadRecipe(recipeId);
      loadCategories();
      setScale(1);
      setEditing(!!context.editing);
      setDirty(false);
    }
  }, [recipeId]);

  // Auto-refresh
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (recipeId && !dirty) loadRecipe(recipeId);
  }, [refreshKey]);

  function buildForm(r) {
    return {
      title: r.title || "",
      description: r.description || "",
      ingredients: (r.ingredients || []).map(i => ({ ...i })),
      steps: [...(r.steps || [])],
      prep_time_min: r.prep_time_min ?? "",
      cook_time_min: r.cook_time_min ?? "",
      servings: r.servings || 1,
      categories: [...(r.categories || [])],
      source_url: r.source_url || "",
      chef_comments: r.chef_comments || "",
      notes: r.notes || "",
    };
  }

  function updateForm(key, value) {
    setForm(prev => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  // --- Save ---
  async function handleSave() {
    if (!recipeId) return;
    setSaving(true);
    try {
      const payload = {
        ...form,
        prep_time_min: form.prep_time_min === "" ? null : Number(form.prep_time_min),
        cook_time_min: form.cook_time_min === "" ? null : Number(form.cook_time_min),
        servings: Number(form.servings) || 1,
      };
      const res = await fetch(`/api/apps/recipes/${recipeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const updated = await res.json();
        setRecipe(updated);
        setForm(buildForm(updated));
        onTitle?.(updated.title || "Recipe");
        setDirty(false);
        setEditing(false);
      }
    } catch {}
    setSaving(false);
  }

  // --- Delete ---
  async function handleDelete() {
    if (!recipeId) return;
    try {
      await fetch(`/api/apps/recipes/${recipeId}`, { method: "DELETE" });
      onOpenApp?.("recipes");
    } catch {}
  }

  // --- Rating ---
  async function handleRate(stars) {
    if (!recipeId) return;
    try {
      await fetch(`/api/apps/recipes/${recipeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: stars }),
      });
      setRecipe(prev => ({ ...prev, rating: stars }));
    } catch {}
  }

  // --- Cooking mode: toggle step ---
  async function toggleStep(idx) {
    if (!recipe) return;
    const checkedSet = new Set(recipe.checked_steps || []);
    if (checkedSet.has(idx)) checkedSet.delete(idx); else checkedSet.add(idx);
    const arr = [...checkedSet];
    try {
      await fetch(`/api/apps/recipes/${recipeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked_steps: arr }),
      });
      setRecipe(prev => ({ ...prev, checked_steps: arr }));
    } catch {}
  }

  // --- Cooking mode: toggle ingredient ---
  async function toggleIngredient(idx) {
    if (!recipe) return;
    const checked = new Set(recipe.checked_ingredients || []);
    if (checked.has(idx)) checked.delete(idx); else checked.add(idx);
    const arr = [...checked];
    try {
      await fetch(`/api/apps/recipes/${recipeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked_ingredients: arr }),
      });
      setRecipe(prev => ({ ...prev, checked_ingredients: arr }));
    } catch {}
  }

  async function handleStartOver() {
    try {
      await fetch(`/api/apps/recipes/${recipeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked_ingredients: [], checked_steps: [] }),
      });
      setRecipe(prev => ({ ...prev, checked_ingredients: [], checked_steps: [] }));
    } catch {}
  }

  // --- Chef Comments (inline save) ---
  async function saveChefComments(text) {
    try {
      await fetch(`/api/apps/recipes/${recipeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chef_comments: text }),
      });
    } catch {}
  }

  // --- Image upload ---
  async function handleImageUpload(e) {
    const file = e.target.files?.[0];
    if (!file || !recipeId) return;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("uploaded_by", userId);
    formData.append("recipe_id", recipeId);
    try {
      const res = await fetch("/api/apps/images/upload", { method: "POST", body: formData });
      if (res.ok) {
        loadRecipe(recipeId);
      }
    } catch {}
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // --- Print ---
  function handlePrint() {
    if (!recipe) return;
    const r = recipe;
    const metaParts = [];
    if (r.prep_time_min != null) metaParts.push(`Prep: ${r.prep_time_min} min`);
    if (r.cook_time_min != null) metaParts.push(`Cook: ${r.cook_time_min} min`);
    const total = (r.prep_time_min || 0) + (r.cook_time_min || 0);
    if (total) metaParts.push(`Total: ${total} min`);
    if (r.servings) metaParts.push(`Servings: ${r.servings}`);

    const ingredients = (r.ingredients || []).map((ing) => {
      const parts = [];
      if (ing.quantity) parts.push(String(ing.quantity));
      if (ing.unit) parts.push(ing.unit);
      parts.push(ing.item);
      return `<li>${parts.join(" ")}</li>`;
    }).join("\n");

    const steps = (r.steps || []).map((s, i) => `<li>${s}</li>`).join("\n");

    const cats = (r.categories || []).length > 0
      ? `<p class="cats">${r.categories.join(", ")}</p>` : "";

    const chef = r.chef_comments
      ? `<h2>Chef Comments</h2><p>${r.chef_comments.replace(/\n/g, "<br>")}</p>` : "";

    const source = r.source_url
      ? `<p class="source">Source: ${r.source_url}</p>` : "";

    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(`<!DOCTYPE html><html><head><title>${r.title || "Recipe"}</title>
      <style>
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
          font-size:12pt;line-height:1.6;color:#222;max-width:6.5in;margin:0 auto;padding:0.75in 0.75in;}
        h1{font-size:20pt;margin-bottom:0.2em;border-bottom:2px solid #333;padding-bottom:0.2em;}
        h2{font-size:14pt;margin-top:1.2em;border-bottom:1px solid #aaa;padding-bottom:0.1em;}
        .meta{font-size:10pt;color:#555;margin-bottom:0.5em;}
        .cats{font-size:10pt;color:#666;font-style:italic;}
        ul{padding-left:1.5em;} li{margin-bottom:0.15em;}
        ol li{margin-bottom:0.4em;}
        .source{font-size:9pt;color:#888;margin-top:1.5em;border-top:1px solid #ddd;padding-top:0.5em;}
        @media print{body{max-width:none;padding:0.5in 0.6in;}}
      </style></head><body>
      <h1>${r.title || "Recipe"}</h1>
      ${r.description ? `<p><em>${r.description}</em></p>` : ""}
      ${metaParts.length ? `<p class="meta">${metaParts.join(" &nbsp;|&nbsp; ")}</p>` : ""}
      ${cats}
      ${ingredients ? `<h2>Ingredients</h2><ul>${ingredients}</ul>` : ""}
      ${steps ? `<h2>Instructions</h2><ol>${steps}</ol>` : ""}
      ${chef}
      ${source}
      </body></html>`);
    win.document.close();
    win.print();
  }

  // --- Smart scaling with fraction display & unit conversion ---
  // Volume units in teaspoons (base unit)
  const VOLUME_TSP = { tsp: 1, Tbsp: 3, cup: 48, pint: 96, quart: 192, gallon: 768 };
  // Largest → smallest for step-down search
  const VOLUME_DOWN = ["gallon", "quart", "pint", "cup", "Tbsp", "tsp"];
  // Normalize user-entered unit strings to canonical form
  const UNIT_ALIASES = {
    tsp: "tsp", teaspoon: "tsp", teaspoons: "tsp",
    tbsp: "Tbsp", tablespoon: "Tbsp", tablespoons: "Tbsp",
    cup: "cup", cups: "cup", c: "cup",
    pint: "pint", pints: "pint", pt: "pint",
    quart: "quart", quarts: "quart", qt: "quart",
    gallon: "gallon", gallons: "gallon", gal: "gallon",
  };

  function canonicalUnit(unit) {
    return UNIT_ALIASES[(unit || "").trim().toLowerCase()] || null;
  }

  function parseFraction(str) {
    if (str == null || str === "") return NaN;
    const s = String(str).trim();
    if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
    const fracMatch = s.match(/^(-?\d+)\s*\/\s*(\d+)$/);
    if (fracMatch) return Number(fracMatch[1]) / Number(fracMatch[2]);
    const mixedMatch = s.match(/^(-?\d+)\s+(\d+)\s*\/\s*(\d+)$/);
    if (mixedMatch) {
      const whole = Number(mixedMatch[1]);
      const frac = Number(mixedMatch[2]) / Number(mixedMatch[3]);
      return whole < 0 ? whole - frac : whole + frac;
    }
    return NaN;
  }

  // Try to express value as whole + fraction with denominator in {1,2,3,4,8}
  function friendlyFraction(value) {
    if (value < 0) return null;
    const TOL = 0.01;
    const DENOMS = [1, 2, 3, 4, 8];
    for (const d of DENOMS) {
      const total = Math.round(value * d);
      if (Math.abs(value - total / d) < TOL) {
        const whole = Math.floor(total / d);
        const num = total - whole * d;
        return { whole, num, den: d };
      }
    }
    return null;
  }

  function formatFrac({ whole, num, den }) {
    if (num === 0) return whole > 0 ? String(whole) : "0";
    const f = `${num}/${den}`;
    return whole > 0 ? `${whole} ${f}` : f;
  }

  // Format any number as a friendly fraction or clean decimal fallback
  function formatQty(value) {
    if (value <= 0) return "";
    const frac = friendlyFraction(value);
    if (frac) return formatFrac(frac);
    if (value === Math.floor(value)) return String(value);
    return value.toFixed(2).replace(/\.?0+$/, "");
  }

  // Check if a value is practical to display in the given unit
  function isDisplayable(value, canonUnit) {
    const frac = friendlyFraction(value);
    if (!frac) return false;
    // Fractional Tbsp (< 1) → prefer tsp instead
    if (canonUnit === "Tbsp" && value < 0.99) return false;
    // Cups+: only allow denominators 2, 3, 4 (standard measuring cups)
    if (["cup", "pint", "quart", "gallon"].includes(canonUnit) && frac.num > 0 && frac.den === 8) return false;
    return true;
  }

  // Scale an ingredient, returning { qty, unit } with smart unit conversion
  function scaleIngredient(rawQty, rawUnit) {
    if (rawQty == null || rawQty === "") return { qty: "", unit: rawUnit || "" };
    const n = parseFraction(rawQty);
    if (isNaN(n)) return { qty: String(rawQty), unit: rawUnit || "" };
    const scaled = n * scale;
    if (scaled <= 0) return { qty: "", unit: rawUnit || "" };

    const canon = canonicalUnit(rawUnit);
    // Non-volume unit — just format the number as a fraction
    if (!canon) return { qty: formatQty(scaled), unit: rawUnit || "" };

    // Volume unit — find the best practical representation
    const baseTsp = scaled * VOLUME_TSP[canon];
    const startIdx = VOLUME_DOWN.indexOf(canon);

    for (let i = startIdx; i < VOLUME_DOWN.length; i++) {
      const tryUnit = VOLUME_DOWN[i];
      const val = baseTsp / VOLUME_TSP[tryUnit];
      if (isDisplayable(val, tryUnit)) {
        const displayUnit = tryUnit === canon ? (rawUnit || tryUnit) : tryUnit;
        return { qty: formatQty(val), unit: displayUnit };
      }
    }
    // Fallback: original unit with best formatting
    return { qty: formatQty(scaled), unit: rawUnit || "" };
  }

  function addIngredient() {
    updateForm("ingredients", [...form.ingredients, { item: "", quantity: "", unit: "" }]);
  }

  function removeIngredient(idx) {
    updateForm("ingredients", form.ingredients.filter((_, i) => i !== idx));
  }

  function updateIngredient(idx, key, value) {
    const arr = [...form.ingredients];
    arr[idx] = { ...arr[idx], [key]: value };
    updateForm("ingredients", arr);
  }

  function moveIngredient(idx, dir) {
    const arr = [...form.ingredients];
    const target = idx + dir;
    if (target < 0 || target >= arr.length) return;
    [arr[idx], arr[target]] = [arr[target], arr[idx]];
    updateForm("ingredients", arr);
  }

  function addStep() {
    updateForm("steps", [...form.steps, ""]);
  }

  function removeStep(idx) {
    updateForm("steps", form.steps.filter((_, i) => i !== idx));
  }

  function updateStep(idx, value) {
    const arr = [...form.steps];
    arr[idx] = value;
    updateForm("steps", arr);
  }

  function moveStep(idx, dir) {
    const arr = [...form.steps];
    const target = idx + dir;
    if (target < 0 || target >= arr.length) return;
    [arr[idx], arr[target]] = [arr[target], arr[idx]];
    updateForm("steps", arr);
  }

  // --- No recipe loaded ---
  if (!recipeId) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        <ChefHat size={32} className="mr-2 opacity-40" />
        Select a recipe from the list to view it.
      </div>
    );
  }

  if (loading && !recipe) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={18} className="animate-spin mr-2" /> Loading recipe...
      </div>
    );
  }

  if (!recipe) return null;

  const checked = new Set(recipe.checked_ingredients || []);
  const checkedSteps = new Set(recipe.checked_steps || []);

  // ============================================================
  // EDIT MODE
  // ============================================================
  if (editing) {
    return (
      <div className="flex flex-col h-full w-full">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <button onClick={() => { setEditing(false); setForm(buildForm(recipe)); setDirty(false); }} className="p-1 text-slate-500 hover:text-white">
              <ArrowLeft size={14} />
            </button>
            <Edit3 size={14} className="text-slate-500" />
            <span className="font-medium">Edit Recipe</span>
            {dirty && <span className="text-xs text-amber-400">unsaved</span>}
          </div>
          <div className="flex items-center gap-1">
            <button onClick={handleSave} disabled={saving} className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded disabled:opacity-50">
              <Save size={12} /> {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>

        {/* Edit form */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Title</label>
            <input
              value={form.title}
              onChange={(e) => updateForm("title", e.target.value)}
              className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => updateForm("description", e.target.value)}
              rows={2}
              className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500 resize-none"
            />
          </div>

          {/* Times + Servings row */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Prep (min)</label>
              <input type="number" value={form.prep_time_min} onChange={(e) => updateForm("prep_time_min", e.target.value)}
                className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none" />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Cook (min)</label>
              <input type="number" value={form.cook_time_min} onChange={(e) => updateForm("cook_time_min", e.target.value)}
                className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none" />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Servings</label>
              <input type="number" value={form.servings} onChange={(e) => updateForm("servings", e.target.value)}
                className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none" />
            </div>
          </div>

          {/* Categories */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Categories</label>
            <div className="flex flex-wrap gap-1 mb-1">
              {form.categories.map((c, i) => (
                <span key={i} className="flex items-center gap-1 px-2 py-0.5 bg-indigo-600/30 rounded-full text-xs text-indigo-300">
                  {c}
                  <button onClick={() => updateForm("categories", form.categories.filter((_, j) => j !== i))} className="hover:text-red-400"><X size={10} /></button>
                </span>
              ))}
            </div>
            <div className="flex flex-wrap gap-1 items-center">
              {categories.filter(c => !form.categories.includes(c.name)).map(c => (
                <button key={c.id} onClick={() => updateForm("categories", [...form.categories, c.name])}
                  className="px-2 py-0.5 bg-slate-800 text-xs text-slate-400 rounded-full hover:text-white hover:bg-slate-700">
                  + {c.name}
                </button>
              ))}
              <form onSubmit={(e) => {
                e.preventDefault();
                const input = e.target.elements.newCat;
                const val = input.value.trim();
                if (val && !form.categories.includes(val)) {
                  updateForm("categories", [...form.categories, val]);
                  input.value = "";
                }
              }} className="flex items-center gap-1">
                <input name="newCat" placeholder="New category..."
                  className="w-28 bg-slate-800 text-white text-xs px-2 py-1 rounded border border-slate-700 outline-none focus:border-indigo-500" />
                <button type="submit" className="px-1.5 py-0.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded">+</button>
              </form>
            </div>
          </div>

          {/* Ingredients */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Ingredients</label>
            <div className="space-y-1">
              {form.ingredients.map((ing, i) => (
                <div key={i} className="flex items-center gap-1">
                  <div className="flex flex-col">
                    <button onClick={() => moveIngredient(i, -1)} disabled={i === 0}
                      className="p-0.5 text-slate-600 hover:text-white disabled:opacity-20 disabled:cursor-default"><ChevronUp size={10} /></button>
                    <button onClick={() => moveIngredient(i, 1)} disabled={i === form.ingredients.length - 1}
                      className="p-0.5 text-slate-600 hover:text-white disabled:opacity-20 disabled:cursor-default"><ChevronDown size={10} /></button>
                  </div>
                  <input value={ing.quantity || ""} onChange={(e) => updateIngredient(i, "quantity", e.target.value)}
                    placeholder="Qty" className="w-16 bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none" />
                  <input value={ing.unit || ""} onChange={(e) => updateIngredient(i, "unit", e.target.value)}
                    placeholder="Unit" className="w-16 bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none" />
                  <input value={ing.item || ""} onChange={(e) => updateIngredient(i, "item", e.target.value)}
                    placeholder="Ingredient" className="flex-1 bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none" />
                  <button onClick={() => removeIngredient(i)} className="p-1 text-slate-500 hover:text-red-400"><X size={12} /></button>
                </div>
              ))}
            </div>
            <button onClick={addIngredient} className="mt-1 flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
              <Plus size={12} /> Add ingredient
            </button>
          </div>

          {/* Steps */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Steps</label>
            <div className="space-y-1">
              {form.steps.map((step, i) => (
                <div key={i} className="flex items-start gap-1">
                  <div className="flex flex-col mt-1">
                    <button onClick={() => moveStep(i, -1)} disabled={i === 0}
                      className="p-0.5 text-slate-600 hover:text-white disabled:opacity-20 disabled:cursor-default"><ChevronUp size={10} /></button>
                    <button onClick={() => moveStep(i, 1)} disabled={i === form.steps.length - 1}
                      className="p-0.5 text-slate-600 hover:text-white disabled:opacity-20 disabled:cursor-default"><ChevronDown size={10} /></button>
                  </div>
                  <span className="text-xs text-slate-500 mt-2 w-5 shrink-0 text-right">{i + 1}.</span>
                  <textarea value={step} onChange={(e) => updateStep(i, e.target.value)}
                    rows={2} className="flex-1 bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none resize-none" />
                  <button onClick={() => removeStep(i)} className="p-1 mt-1 text-slate-500 hover:text-red-400"><X size={12} /></button>
                </div>
              ))}
            </div>
            <button onClick={addStep} className="mt-1 flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
              <Plus size={12} /> Add step
            </button>
          </div>

          {/* Source URL */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Source URL</label>
            <input value={form.source_url} onChange={(e) => updateForm("source_url", e.target.value)}
              placeholder="https://..." className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none" />
          </div>

          {/* Chef Comments */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Chef Comments</label>
            <textarea value={form.chef_comments} onChange={(e) => updateForm("chef_comments", e.target.value)}
              rows={3} placeholder="Observations, proposed changes for next time..."
              className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none resize-none" />
          </div>

          {/* Delete */}
          <div className="pt-4 border-t border-slate-800">
            {confirmDelete ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-red-400">Delete this recipe?</span>
                <button onClick={handleDelete} className="px-2 py-1 text-xs bg-red-600 text-white rounded">Yes, delete</button>
                <button onClick={() => setConfirmDelete(false)} className="px-2 py-1 text-xs bg-slate-700 text-white rounded">Cancel</button>
              </div>
            ) : (
              <button onClick={() => setConfirmDelete(true)} className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300">
                <Trash2 size={12} /> Delete recipe
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ============================================================
  // VIEW MODE
  // ============================================================
  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 text-sm text-slate-300 min-w-0">
          <button onClick={() => onOpenApp?.("recipes")} className="p-1 text-slate-500 hover:text-white" title="Back to recipes">
            <ArrowLeft size={14} />
          </button>
          <ChefHat size={14} className="text-slate-500 shrink-0" />
          <span className="truncate font-medium">{recipe.title}</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={handlePrint} className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors" title="Print recipe">
            <Printer size={14} />
          </button>
          <button onClick={() => { setEditing(true); setForm(buildForm(recipe)); }}
            className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:bg-slate-700 hover:text-white rounded">
            <Edit3 size={12} /> Edit
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto p-4 space-y-5">
          {/* Title + Rating */}
          <div>
            <h1 className="text-xl font-bold text-white">{recipe.title}</h1>
            {recipe.description && <p className="text-sm text-slate-400 mt-1">{recipe.description}</p>}
            <div className="flex items-center gap-1 mt-2">
              {[1, 2, 3, 4, 5].map((s) => (
                <button key={s} onClick={() => handleRate(s)} className="p-0.5 transition-colors">
                  <Star size={18} className={s <= (recipe.rating || 0) ? "text-amber-400 fill-amber-400" : "text-slate-600 hover:text-amber-300"} />
                </button>
              ))}
              {recipe.rating && <span className="text-xs text-slate-500 ml-1">{recipe.rating}/5</span>}
            </div>
          </div>

          {/* Meta */}
          <div className="flex items-center gap-4 text-xs text-slate-400">
            {recipe.prep_time_min != null && (
              <span className="flex items-center gap-1"><Clock size={12} /> Prep: {recipe.prep_time_min}m</span>
            )}
            {recipe.cook_time_min != null && (
              <span className="flex items-center gap-1"><Clock size={12} /> Cook: {recipe.cook_time_min}m</span>
            )}
            {recipe.servings > 0 && (
              <span className="flex items-center gap-1"><Users size={12} /> {recipe.servings} serving{recipe.servings !== 1 ? "s" : ""}</span>
            )}
          </div>

          {/* Categories */}
          {recipe.categories?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {recipe.categories.map((c) => (
                <span key={c} className="px-2 py-0.5 bg-indigo-600/20 text-indigo-300 rounded-full text-xs">{c}</span>
              ))}
            </div>
          )}

          {/* Image Carousel */}
          {images.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 overflow-x-auto pb-1">
                {images.map((img) => (
                  <button key={img.id} onClick={() => onOpenApp?.("image", { imageId: img.id, title: img.title || img.filename })}
                    className="shrink-0 w-24 h-24 rounded-lg overflow-hidden border border-slate-700 hover:border-indigo-500 transition-colors">
                    <img src={`/${img.storage_path}`} alt={img.title || img.filename}
                      className="w-full h-full object-cover" />
                  </button>
                ))}
                <button onClick={() => fileInputRef.current?.click()}
                  className="shrink-0 w-24 h-24 rounded-lg border border-dashed border-slate-600 flex flex-col items-center justify-center text-slate-500 hover:border-indigo-500 hover:text-indigo-400 transition-colors">
                  <Camera size={20} />
                  <span className="text-[10px] mt-1">Add photo</span>
                </button>
              </div>
            </div>
          )}

          {images.length === 0 && (
            <button onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-2 px-3 py-2 border border-dashed border-slate-700 rounded-lg text-xs text-slate-500 hover:border-indigo-500 hover:text-indigo-400 transition-colors">
              <Camera size={14} /> Add photos
            </button>
          )}

          <input ref={fileInputRef} type="file" accept="image/*" capture="environment"
            onChange={handleImageUpload} className="hidden" />

          {/* Scale buttons */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Scale:</span>
            {SCALE_OPTIONS.map((s) => (
              <button key={s} onClick={() => setScale(s)}
                className={`px-2 py-0.5 text-xs rounded transition-colors ${
                  scale === s ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white"
                }`}>
                {s}×
              </button>
            ))}
          </div>

          {/* Ingredients */}
          {recipe.ingredients?.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-sm font-semibold text-white">Ingredients</h2>
                {(checked.size > 0 || checkedSteps.size > 0) && (
                  <button onClick={handleStartOver} className="flex items-center gap-1 text-xs text-slate-500 hover:text-white">
                    <RotateCcw size={11} /> Start Over
                  </button>
                )}
              </div>
              <ul className="space-y-1">
                {recipe.ingredients.map((ing, i) => {
                  const si = scaleIngredient(ing.quantity, ing.unit);
                  return (
                  <li key={i}>
                    <button onClick={() => toggleIngredient(i)}
                      className={`w-full text-left px-3 py-1.5 rounded text-sm transition-colors ${
                        checked.has(i)
                          ? "bg-slate-800/30 text-slate-600 line-through"
                          : "bg-slate-800/50 text-slate-200 hover:bg-slate-800/70"
                      }`}>
                      {si.qty && (
                        <span className="font-medium text-indigo-300">{si.qty}</span>
                      )}
                      {si.unit && <span className="text-slate-400"> {si.unit}</span>}
                      {ing.item && <span> {ing.item}</span>}
                    </button>
                  </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Steps */}
          {recipe.steps?.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-white mb-2">Steps</h2>
              <ol className="space-y-2">
                {recipe.steps.map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <button onClick={() => toggleStep(i)}
                      className={`shrink-0 w-6 h-6 rounded-full text-xs flex items-center justify-center font-medium transition-colors ${
                        checkedSteps.has(i)
                          ? "bg-slate-700/40 text-slate-600"
                          : "bg-indigo-600/30 text-indigo-300 hover:bg-indigo-600/50"
                      }`}>{i + 1}</button>
                    <button onClick={() => toggleStep(i)}
                      className={`text-sm leading-relaxed pt-0.5 text-left transition-colors ${
                        checkedSteps.has(i)
                          ? "text-slate-600 line-through"
                          : "text-slate-300 hover:text-slate-100"
                      }`}>{step}</button>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Chef Comments */}
          <ChefCommentsField
            value={recipe.chef_comments || ""}
            onSave={saveChefComments}
            onChange={(v) => setRecipe(prev => ({ ...prev, chef_comments: v }))}
          />

          {/* Source URL */}
          {recipe.source_url && (
            <div className="text-xs text-slate-500">
              Source: <a href={recipe.source_url} target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:underline">{recipe.source_url}</a>
            </div>
          )}

          {/* Last opened */}
          {recipe.last_opened_at && (
            <div className="text-xs text-slate-600">
              Last viewed: {new Date(recipe.last_opened_at).toLocaleString()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
