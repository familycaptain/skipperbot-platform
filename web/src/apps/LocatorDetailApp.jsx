import { useState, useEffect, useCallback } from "react";
import {
  Edit3, Save, Trash2, Plus, X, MapPin, Tag, Package,
  Loader2, RotateCcw,
} from "lucide-react";

/**
 * Item Locator Detail App — view/edit a single located item.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 * Context: { locatorItemId, editing? }
 */
export default function LocatorDetailApp({ appId, userId, context = {}, onTitle, onOpenApp, onClose, refreshKey }) {
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(!!context.editing);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [locations, setLocations] = useState([]);

  const [form, setForm] = useState({});

  const itemId = context.locatorItemId || null;

  const loadItem = useCallback(async (id) => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/apps/home/${id}`);
      if (res.ok) {
        const data = await res.json();
        setItem(data);
        onTitle?.(data.name || "Item");
        setForm(buildForm(data));
      }
    } catch {}
    setLoading(false);
  }, [onTitle]);

  const loadLocations = useCallback(async () => {
    try {
      const res = await fetch("/api/apps/home/locations");
      if (res.ok) {
        const data = await res.json();
        setLocations(data.locations || []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (itemId) {
      loadItem(itemId);
      loadLocations();
      setEditing(!!context.editing);
      setDirty(false);
    }
  }, [itemId]);

  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (itemId && !dirty) loadItem(itemId);
  }, [refreshKey]);

  function buildForm(i) {
    return {
      name: i.name || "",
      description: i.description || "",
      location: i.location || "",
      sub_location: i.sub_location || "",
      category: i.category || "",
      tags: [...(i.tags || [])],
      quantity: i.quantity ?? "",
      notes: i.notes || "",
    };
  }

  function updateForm(key, value) {
    setForm(prev => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  async function handleSave() {
    if (!itemId) return;
    setSaving(true);
    try {
      const body = {
        name: form.name || null,
        description: form.description || null,
        location: form.location || null,
        sub_location: form.sub_location || null,
        category: form.category || null,
        tags: form.tags.length > 0 ? form.tags : null,
        quantity: form.quantity ? parseInt(form.quantity, 10) || null : null,
        notes: form.notes || null,
      };
      const res = await fetch(`/api/apps/home/${itemId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const updated = await res.json();
        setItem(updated);
        setForm(buildForm(updated));
        onTitle?.(updated.name || "Item");
        setEditing(false);
        setDirty(false);
      }
    } catch {}
    setSaving(false);
  }

  async function handleDelete() {
    if (!itemId) return;
    try {
      const res = await fetch(`/api/apps/home/${itemId}`, { method: "DELETE" });
      if (res.ok) {
        onClose?.();
      }
    } catch {}
  }

  function handleCancel() {
    if (item) setForm(buildForm(item));
    setEditing(false);
    setDirty(false);
  }

  if (!itemId) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        No item selected.
      </div>
    );
  }

  if (loading || !item) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={18} className="animate-spin mr-2" /> Loading item...
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-sm font-medium text-white truncate">
            {editing ? "Editing" : ""} {item.name || "Untitled"}
          </h2>
        </div>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <button onClick={handleCancel} className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-white hover:bg-slate-700 rounded transition-colors">
                <RotateCcw size={12} /> Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded transition-colors disabled:opacity-50"
              >
                <Save size={12} /> {saving ? "Saving..." : "Save"}
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)} className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-white hover:bg-slate-700 rounded transition-colors">
                <Edit3 size={12} /> Edit
              </button>
              {confirmDelete ? (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-red-400">Delete?</span>
                  <button onClick={handleDelete} className="px-2 py-0.5 text-xs bg-red-600 hover:bg-red-500 text-white rounded">Yes</button>
                  <button onClick={() => setConfirmDelete(false)} className="px-2 py-0.5 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded">No</button>
                </div>
              ) : (
                <button onClick={() => setConfirmDelete(true)} className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded transition-colors">
                  <Trash2 size={12} />
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {editing ? (
          /* ── Edit Mode ── */
          <div className="space-y-4 max-w-lg">
            {/* Name */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Name</label>
              <input value={form.name} onChange={(e) => updateForm("name", e.target.value)}
                className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500" />
            </div>

            {/* Description */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Description</label>
              <textarea value={form.description} onChange={(e) => updateForm("description", e.target.value)} rows={3}
                className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500 resize-none" />
            </div>

            {/* Location + Sub-location */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Location</label>
                <input value={form.location} onChange={(e) => updateForm("location", e.target.value)}
                  list="location-suggestions" placeholder="e.g. Garage, Attic"
                  className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500" />
                <datalist id="location-suggestions">
                  {locations.map(l => <option key={l.id} value={l.name} />)}
                </datalist>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Sub-location</label>
                <input value={form.sub_location} onChange={(e) => updateForm("sub_location", e.target.value)}
                  placeholder="e.g. Top shelf, Bin #3"
                  className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500" />
              </div>
            </div>

            {/* Category + Quantity */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Category</label>
                <input value={form.category} onChange={(e) => updateForm("category", e.target.value)}
                  placeholder="e.g. Tools, Seasonal"
                  className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Quantity</label>
                <input type="number" value={form.quantity} onChange={(e) => updateForm("quantity", e.target.value)}
                  placeholder="Optional"
                  className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500" />
              </div>
            </div>

            {/* Tags */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Tags</label>
              <div className="flex flex-wrap gap-1 mb-1">
                {form.tags.map((tag, i) => (
                  <span key={i} className="flex items-center gap-1 px-2 py-0.5 bg-indigo-600/30 rounded-full text-xs text-indigo-300">
                    {tag}
                    <button onClick={() => updateForm("tags", form.tags.filter((_, j) => j !== i))} className="hover:text-red-400"><X size={10} /></button>
                  </span>
                ))}
              </div>
              <form onSubmit={(e) => {
                e.preventDefault();
                const input = e.target.elements.newTag;
                const val = input.value.trim();
                if (val && !form.tags.includes(val)) {
                  updateForm("tags", [...form.tags, val]);
                  input.value = "";
                }
              }} className="flex items-center gap-1">
                <input name="newTag" placeholder="Add tag..."
                  className="w-32 bg-slate-800 text-white text-xs px-2 py-1 rounded border border-slate-700 outline-none focus:border-indigo-500" />
                <button type="submit" className="px-1.5 py-0.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded">+</button>
              </form>
            </div>

            {/* Notes */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Notes</label>
              <textarea value={form.notes} onChange={(e) => updateForm("notes", e.target.value)} rows={4}
                className="w-full bg-slate-800 text-white text-sm px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500 resize-none" />
            </div>
          </div>
        ) : (
          /* ── View Mode ── */
          <div className="space-y-4 max-w-lg">
            {/* Location card */}
            <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-4">
              <div className="flex items-center gap-2 text-indigo-300 mb-2">
                <MapPin size={16} />
                <span className="text-sm font-medium">
                  {item.location || "No location set"}
                  {item.sub_location && <span className="text-slate-400"> &gt; {item.sub_location}</span>}
                </span>
              </div>
              {item.category && (
                <div className="flex items-center gap-2 text-xs text-slate-400 mt-1">
                  <Package size={12} />
                  {item.category}
                </div>
              )}
              {item.quantity && (
                <div className="text-xs text-slate-400 mt-1">
                  Quantity: {item.quantity}
                </div>
              )}
            </div>

            {/* Description */}
            {item.description && (
              <div>
                <h4 className="text-xs text-slate-500 uppercase tracking-wider mb-1">Description</h4>
                <p className="text-sm text-slate-300 whitespace-pre-wrap">{item.description}</p>
              </div>
            )}

            {/* Tags */}
            {item.tags?.length > 0 && (
              <div>
                <h4 className="text-xs text-slate-500 uppercase tracking-wider mb-1">Tags</h4>
                <div className="flex flex-wrap gap-1">
                  {item.tags.map((tag) => (
                    <span key={tag} className="px-2 py-0.5 bg-slate-800 rounded-full text-xs text-slate-300">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Notes */}
            {item.notes && (
              <div>
                <h4 className="text-xs text-slate-500 uppercase tracking-wider mb-1">Notes</h4>
                <p className="text-sm text-slate-300 whitespace-pre-wrap">{item.notes}</p>
              </div>
            )}

            {/* Meta */}
            <div className="text-xs text-slate-600 pt-2 border-t border-slate-800">
              Created by {item.created_by || "unknown"} &middot; {item.created_at ? new Date(item.created_at).toLocaleDateString() : ""}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
