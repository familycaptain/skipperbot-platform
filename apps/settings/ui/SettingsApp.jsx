// =============================================================================
// Settings — central app settings panel
// =============================================================================
// Reads every loaded app's config schema from /api/apps/settings/apps and
// renders schema-driven inputs (string / integer / boolean / select). Apps
// with no `config:` block are listed in the sidebar greyed out so the user
// can see they're installed but intentionally not configurable.
//
// The platform scope (timezone, model names, etc.) sits at the top of the
// sidebar — separate endpoint, no schema, raw key/value pairs.

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Settings as Cog, Loader2, Save, Check, X, Eye, EyeOff, AlertCircle,
} from "lucide-react";

const API = "/api/apps/settings";

function isObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function valuesEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (isObject(a) && isObject(b)) {
    const ak = Object.keys(a), bk = Object.keys(b);
    if (ak.length !== bk.length) return false;
    return ak.every(k => valuesEqual(a[k], b[k]));
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((x, i) => valuesEqual(x, b[i]));
  }
  return false;
}

// ---------------------------------------------------------------------------
// One schema-driven input row
// ---------------------------------------------------------------------------

function ConfigInput({ field, value, onChange }) {
  const { type, choices, secret } = field;
  const [revealed, setRevealed] = useState(false);

  if (choices && choices.length > 0) {
    return (
      <select
        className="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {choices.map((c) => (
          <option key={String(c)} value={String(c)}>{String(c)}</option>
        ))}
      </select>
    );
  }

  if (type === "boolean") {
    return (
      <label className="inline-flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-zinc-700 bg-zinc-900"
        />
        <span className="text-sm text-zinc-300">{value ? "Enabled" : "Disabled"}</span>
      </label>
    );
  }

  if (type === "integer") {
    return (
      <input
        type="number"
        className="w-32 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100"
        value={value ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? null : Number.parseInt(raw, 10));
        }}
      />
    );
  }

  // string (default) — with optional secret reveal
  const showSecret = !secret || revealed;
  return (
    <div className="flex items-center gap-2 w-full">
      <input
        type={showSecret ? "text" : "password"}
        className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100 font-mono"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {secret && (
        <button
          type="button"
          className="text-zinc-500 hover:text-zinc-300"
          onClick={() => setRevealed((r) => !r)}
          title={revealed ? "Hide" : "Reveal"}
        >
          {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail panel for the selected app
// ---------------------------------------------------------------------------

function AppDetail({ app, onSaved }) {
  const [draft, setDraft] = useState(app.values || {});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => { setDraft(app.values || {}); setError(""); }, [app.id, app.values]);

  const dirty = useMemo(
    () => !valuesEqual(draft, app.values || {}),
    [draft, app.values],
  );

  const onChange = (key, value) => {
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const onSave = async () => {
    setSaving(true);
    setError("");
    try {
      // Send only the changed keys.
      const changed = {};
      for (const k of Object.keys(draft)) {
        if (!valuesEqual(draft[k], app.values?.[k])) {
          changed[k] = draft[k];
        }
      }
      const res = await fetch(`${API}/apps/${app.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: changed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const fresh = await res.json();
      setSavedAt(Date.now());
      onSaved(fresh);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  };

  if (!app.has_settings) {
    return (
      <div className="p-6 text-zinc-400">
        <h2 className="text-xl font-medium text-zinc-200 mb-2">{app.name}</h2>
        <p className="text-sm">This app has no configurable settings.</p>
        <p className="text-xs mt-4 text-zinc-600">{app.description}</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-baseline justify-between mb-1">
        <h2 className="text-xl font-medium text-zinc-100">{app.name}</h2>
        <span className="text-xs text-zinc-500">v{app.version || "?"}</span>
      </div>
      <p className="text-sm text-zinc-500 mb-6">{app.description}</p>

      <div className="space-y-5">
        {app.schema.map((field) => (
          <div key={field.key}>
            <div className="flex items-baseline justify-between mb-1">
              <label className="text-sm text-zinc-300 font-medium">
                {field.label || field.key}
                <span className="ml-2 text-zinc-600 font-mono text-xs">{field.key}</span>
              </label>
              <span className="text-xs text-zinc-600">{field.type}</span>
            </div>
            <ConfigInput
              field={field}
              value={draft[field.key]}
              onChange={(v) => onChange(field.key, v)}
            />
            {field.description && (
              <p className="text-xs text-zinc-500 mt-1">{field.description}</p>
            )}
          </div>
        ))}
      </div>

      {error && (
        <div className="mt-6 flex items-start gap-2 text-rose-400 text-sm">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-8 flex items-center gap-3">
        <button
          className="px-4 py-2 rounded bg-emerald-600 text-white text-sm disabled:opacity-40 inline-flex items-center gap-2 disabled:cursor-not-allowed"
          onClick={onSave}
          disabled={!dirty || saving}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? "Saving…" : "Save"}
        </button>
        {!dirty && savedAt > 0 && (
          <span className="text-emerald-500 text-sm inline-flex items-center gap-1">
            <Check size={14} /> Saved
          </span>
        )}
        {dirty && (
          <button
            type="button"
            className="text-zinc-400 text-sm inline-flex items-center gap-1 hover:text-zinc-200"
            onClick={() => setDraft(app.values || {})}
          >
            <X size={14} /> Revert
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar + top-level shell
// ---------------------------------------------------------------------------

export default function SettingsApp() {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/apps`);
      if (res.ok) {
        const data = await res.json();
        setApps(data.apps || []);
        if (!selected && data.apps?.length) {
          // Default to the first app with settings.
          const first = (data.apps || []).find((a) => a.has_settings)
            || data.apps[0];
          setSelected(first?.id || null);
        }
      }
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { fetchAll(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onSaved = (fresh) => {
    // Replace the cached app with the server's authoritative version.
    setApps((prev) => prev.map((a) => (a.id === fresh.id ? { ...a, ...fresh } : a)));
  };

  const current = useMemo(
    () => apps.find((a) => a.id === selected),
    [apps, selected],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-6 text-zinc-500">
        <Loader2 className="animate-spin" size={14} /> Loading settings…
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <aside className="w-64 border-r border-zinc-800 bg-zinc-950 overflow-y-auto">
        <div className="px-4 py-3 border-b border-zinc-800">
          <h1 className="text-sm font-semibold text-zinc-300 inline-flex items-center gap-2">
            <Cog size={14} /> Settings
          </h1>
        </div>
        <ul className="py-1">
          {apps.map((a) => {
            const isCurrent = a.id === selected;
            const muted = !a.has_settings;
            return (
              <li key={a.id}>
                <button
                  className={`w-full text-left px-4 py-2 text-sm transition-colors flex items-baseline justify-between gap-2 ${
                    isCurrent
                      ? "bg-zinc-800 text-zinc-100"
                      : muted
                      ? "text-zinc-600 hover:text-zinc-400"
                      : "text-zinc-300 hover:bg-zinc-900"
                  }`}
                  onClick={() => setSelected(a.id)}
                >
                  <span className="truncate">{a.name || a.id}</span>
                  {muted && <span className="text-xs text-zinc-700">—</span>}
                  {!muted && (
                    <span className="text-xs text-zinc-600">{a.schema.length}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </aside>
      <main className="flex-1 overflow-y-auto">
        {current ? (
          <AppDetail key={current.id} app={current} onSaved={onSaved} />
        ) : (
          <div className="p-6 text-zinc-500">Select an app to view its settings.</div>
        )}
      </main>
    </div>
  );
}
