import { useState, useEffect, useCallback } from "react";
import { Zap, Plus, Pencil, Trash2, ToggleLeft, ToggleRight, Globe, User, X, Check, ChevronDown, ChevronUp, Info } from "lucide-react";

const API = "/api/behaviors";

function BehaviorCard({ b, expandedId, editingId, showForm, handleToggle, startEdit, setExpandedId, deleteConfirm, setDeleteConfirm, handleDelete }) {
  const isExpanded = expandedId === b.id;

  return (
    <div className={`rounded-lg border transition-all ${
      b.enabled
        ? "border-zinc-700 bg-zinc-800/60"
        : "border-zinc-800 bg-zinc-900/40 opacity-60"
    }`}>
      {/* Header row */}
      <div className="flex items-start gap-3 p-4">
        {/* Toggle */}
        <button
          onClick={() => handleToggle(b.id)}
          className="mt-0.5 flex-shrink-0 text-zinc-400 hover:text-amber-400 transition-colors"
          title={b.enabled ? "Click to disable" : "Click to enable"}
        >
          {b.enabled
            ? <ToggleRight size={22} className="text-amber-400" />
            : <ToggleLeft size={22} />}
        </button>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
              b.scope === "system"
                ? "bg-purple-900/60 text-purple-300 border border-purple-700"
                : "bg-zinc-700 text-zinc-300 border border-zinc-600"
            }`}>
              {b.scope === "system" ? <Globe size={10} className="inline mr-1" /> : <User size={10} className="inline mr-1" />}
              {b.scope}
            </span>
            {!b.enabled && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500 border border-zinc-700">
                disabled
              </span>
            )}
            <span className="text-xs text-zinc-600 font-mono">{b.id}</span>
          </div>

          <div className="space-y-1">
            <div className="flex gap-1.5">
              <span className="text-xs text-amber-500 font-semibold uppercase tracking-wide mt-0.5 flex-shrink-0">IF</span>
              <p className="text-sm text-zinc-200 leading-snug">{b.trigger_description}</p>
            </div>
            <div className="flex gap-1.5">
              <span className="text-xs text-blue-400 font-semibold uppercase tracking-wide mt-0.5 flex-shrink-0">THEN</span>
              <p className="text-sm text-zinc-300 leading-snug">{b.action_description}</p>
            </div>
          </div>

          {isExpanded && b.notes && (
            <p className="mt-2 text-xs text-zinc-500 italic">{b.notes}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {b.notes && (
            <button
              onClick={() => setExpandedId(isExpanded ? null : b.id)}
              className="p-1.5 rounded text-zinc-500 hover:text-zinc-300 transition-colors"
              title="Show notes"
            >
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
          <button
            onClick={() => startEdit(b)}
            className="p-1.5 rounded text-zinc-500 hover:text-blue-400 transition-colors"
            title="Edit"
          >
            <Pencil size={14} />
          </button>
          {deleteConfirm === b.id ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => handleDelete(b.id)}
                className="p-1.5 rounded text-red-400 hover:text-red-300 transition-colors"
                title="Confirm delete"
              >
                <Check size={14} />
              </button>
              <button
                onClick={() => setDeleteConfirm(null)}
                className="p-1.5 rounded text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setDeleteConfirm(b.id)}
              className="p-1.5 rounded text-zinc-500 hover:text-red-400 transition-colors"
              title="Delete"
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function FormPanel({ editingId, form, setForm, error, saving, resetForm, handleSave }) {
  return (
    <div className="rounded-lg border border-amber-700/60 bg-amber-950/20 p-5 mb-6">
      <h3 className="text-sm font-semibold text-amber-400 mb-4">
        {editingId ? "Edit Behavior Rule" : "New Behavior Rule"}
      </h3>

      <div className="space-y-4">
        {/* Scope */}
        <div>
          <label className="block text-xs text-zinc-400 mb-1.5 font-medium">Scope</label>
          <div className="flex gap-2">
            {["user", "system"].map(s => (
              <button
                key={s}
                onClick={() => setForm(f => ({ ...f, scope: s }))}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
                  form.scope === s
                    ? s === "system"
                      ? "bg-purple-900/60 text-purple-300 border border-purple-600"
                      : "bg-amber-900/60 text-amber-300 border border-amber-600"
                    : "bg-zinc-800 text-zinc-400 border border-zinc-700 hover:border-zinc-500"
                }`}
              >
                {s === "system" ? <Globe size={13} /> : <User size={13} />}
                {s === "user" ? "Personal (just me)" : "System (all users)"}
              </button>
            ))}
          </div>
        </div>

        {/* Trigger */}
        <div>
          <label className="block text-xs text-zinc-400 mb-1.5 font-medium">
            <span className="text-amber-500 font-bold">IF</span> — Trigger condition
          </label>
          <textarea
            value={form.trigger_description}
            onChange={e => setForm(f => ({ ...f, trigger_description: e.target.value }))}
            rows={2}
            placeholder="e.g. When the user says they started their truck or mentions starting a vehicle"
            className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-amber-600 resize-none"
          />
        </div>

        {/* Action */}
        <div>
          <label className="block text-xs text-zinc-400 mb-1.5 font-medium">
            <span className="text-blue-400 font-bold">THEN</span> — Action to take
          </label>
          <textarea
            value={form.action_description}
            onChange={e => setForm(f => ({ ...f, action_description: e.target.value }))}
            rows={3}
            placeholder="e.g. Search the Auto app for a maintenance item matching the vehicle name and mark it as done"
            className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-blue-600 resize-none"
          />
        </div>

        {/* Notes */}
        <div>
          <label className="block text-xs text-zinc-400 mb-1.5 font-medium">Notes (optional)</label>
          <input
            type="text"
            value={form.notes}
            onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
            placeholder="Why this rule exists, context, etc."
            className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
          />
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex gap-2 justify-end">
          <button
            onClick={resetForm}
            className="px-4 py-2 rounded text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded text-sm bg-amber-600 hover:bg-amber-500 text-white font-medium transition-colors disabled:opacity-50"
          >
            {saving ? "Saving…" : editingId ? "Save Changes" : "Create Behavior"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function BehaviorsApp({ userId }) {
  const [behaviors, setBehaviors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [form, setForm] = useState({ trigger_description: "", action_description: "", scope: "user", notes: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}?user_id=${userId}`);
      const data = await res.json();
      setBehaviors(data.behaviors || []);
    } catch {
      setError("Failed to load behaviors.");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  const resetForm = () => {
    setForm({ trigger_description: "", action_description: "", scope: "user", notes: "" });
    setEditingId(null);
    setShowForm(false);
    setError("");
  };

  const startCreate = () => {
    resetForm();
    setShowForm(true);
  };

  const startEdit = (b) => {
    setForm({
      trigger_description: b.trigger_description,
      action_description: b.action_description,
      scope: b.scope,
      notes: b.notes || "",
    });
    setEditingId(b.id);
    setShowForm(true);
    setExpandedId(null);
  };

  const handleSave = async () => {
    if (!form.trigger_description.trim() || !form.action_description.trim()) {
      setError("Trigger and action are both required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editingId) {
        const res = await fetch(`${API}/${editingId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        });
        if (!res.ok) throw new Error("Update failed");
      } else {
        const res = await fetch(API, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...form, created_by: userId }),
        });
        if (!res.ok) throw new Error("Create failed");
      }
      await load();
      resetForm();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (id) => {
    try {
      await fetch(`${API}/${id}/toggle`, { method: "POST" });
      await load();
    } catch {
      setError("Failed to toggle behavior.");
    }
  };

  const handleDelete = async (id) => {
    try {
      await fetch(`${API}/${id}`, { method: "DELETE" });
      setDeleteConfirm(null);
      await load();
    } catch {
      setError("Failed to delete behavior.");
    }
  };

  const userBehaviors = behaviors.filter(b => b.scope === "user");
  const systemBehaviors = behaviors.filter(b => b.scope === "system");

  return (
    <div className="h-full overflow-y-auto bg-zinc-900 text-zinc-100">
      <div className="max-w-2xl mx-auto px-5 py-6">

        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Zap size={20} className="text-amber-400" />
            <h1 className="text-lg font-semibold">Behaviors</h1>
          </div>
          <button
            onClick={startCreate}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium transition-colors"
          >
            <Plus size={14} />
            New Behavior
          </button>
        </div>

        {/* Subtitle */}
        <p className="text-sm text-zinc-500 mb-6">
          Always-active if/then rules. Every behavior is injected into every chat turn — guaranteed to fire when the trigger matches.
        </p>

        {/* Info callout */}
        {behaviors.length === 0 && !loading && !showForm && (
          <div className="rounded-lg border border-zinc-700 bg-zinc-800/40 p-5 mb-6">
            <div className="flex gap-3">
              <Info size={18} className="text-amber-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-zinc-300 mb-1">No behaviors yet</p>
                <p className="text-sm text-zinc-500 mb-3">
                  Teach Skipper custom rules through chat or create one here. Example triggers:
                </p>
                <ul className="text-sm text-zinc-500 space-y-1 list-disc list-inside">
                  <li>"Whenever I say I did something, mark matching to-do items as done"</li>
                  <li>"If I say I started my truck, mark the matching auto maintenance item complete"</li>
                  <li>"When I mention a meal I made, log it to the home timeline"</li>
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Create/Edit form */}
        {showForm && <FormPanel
          editingId={editingId}
          form={form}
          setForm={setForm}
          error={error}
          saving={saving}
          resetForm={resetForm}
          handleSave={handleSave}
        />}

        {loading ? (
          <div className="text-center py-10 text-zinc-600">Loading…</div>
        ) : (
          <div className="space-y-6">
            {/* Personal behaviors */}
            {userBehaviors.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-3">
                  <User size={13} className="text-zinc-500" />
                  <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-widest">
                    Personal — {userId}
                  </h2>
                  <span className="text-xs text-zinc-600">({userBehaviors.length})</span>
                </div>
                <div className="space-y-2">
                  {userBehaviors.map(b => <BehaviorCard key={b.id} b={b}
                    expandedId={expandedId}
                    editingId={editingId}
                    showForm={showForm}
                    handleToggle={handleToggle}
                    startEdit={startEdit}
                    setExpandedId={setExpandedId}
                    deleteConfirm={deleteConfirm}
                    setDeleteConfirm={setDeleteConfirm}
                    handleDelete={handleDelete}
                  />)}
                </div>
              </section>
            )}

            {/* System behaviors */}
            {systemBehaviors.length > 0 && (
              <section>
                <div className="flex items-center gap-2 mb-3">
                  <Globe size={13} className="text-zinc-500" />
                  <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-widest">
                    System — All Users
                  </h2>
                  <span className="text-xs text-zinc-600">({systemBehaviors.length})</span>
                </div>
                <div className="space-y-2">
                  {systemBehaviors.map(b => <BehaviorCard key={b.id} b={b}
                    expandedId={expandedId}
                    editingId={editingId}
                    showForm={showForm}
                    handleToggle={handleToggle}
                    startEdit={startEdit}
                    setExpandedId={setExpandedId}
                    deleteConfirm={deleteConfirm}
                    setDeleteConfirm={setDeleteConfirm}
                    handleDelete={handleDelete}
                  />)}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
