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
  Settings as Cog, Loader2, Save, Check, X, Eye, EyeOff, AlertCircle, LayoutGrid,
  Users, UserPlus, Trash2, KeyRound, ShieldCheck, RotateCcw, Star,
} from "lucide-react";
import { getManageableApps } from "../../../web/src/apps/registry";

const API = "/api/apps/settings";

// ---------------------------------------------------------------------------
// Desktop visibility — show/hide launcher icons (writes /api/apps/disabled)
// ---------------------------------------------------------------------------

function DesktopVisibilityPanel() {
  const launcherApps = useMemo(() => getManageableApps(), []);
  const [disabled, setDisabled] = useState(null); // Set of hidden ids
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/apps/disabled");
        const data = res.ok ? await res.json() : { disabled: [] };
        setDisabled(new Set(data.disabled || []));
      } catch { setDisabled(new Set()); }
    })();
  }, []);

  const toggle = async (id) => {
    const next = new Set(disabled);
    next.has(id) ? next.delete(id) : next.add(id);
    setDisabled(next);
    setSaving(true);
    try {
      await fetch("/api/apps/disabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disabled: [...next] }),
      });
    } finally { setSaving(false); }
  };

  if (disabled === null) {
    return <div className="flex items-center gap-2 p-6 text-zinc-500"><Loader2 className="animate-spin" size={14} /> Loading…</div>;
  }

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-xl font-medium text-zinc-100 mb-1 inline-flex items-center gap-2">
        <LayoutGrid size={18} /> Desktop apps
      </h2>
      <p className="text-sm text-zinc-500 mb-5">
        Hide an app's icon from the desktop launcher. Hiding only removes the
        icon — the app keeps running and its chat tools stay available. Reload
        the desktop to see changes.
      </p>
      <ul className="divide-y divide-zinc-800 border border-zinc-800 rounded">
        {launcherApps.map((a) => {
          const Icon = a.icon;
          const hidden = disabled.has(a.id);
          return (
            <li key={a.id} className="flex items-center justify-between px-4 py-2.5">
              <span className="inline-flex items-center gap-2.5 text-sm text-zinc-300">
                {Icon && <Icon size={15} className={hidden ? "text-zinc-600" : "text-zinc-400"} />}
                <span className={hidden ? "text-zinc-500" : ""}>{a.name}</span>
              </span>
              <button
                onClick={() => toggle(a.id)}
                disabled={saving}
                className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded transition-colors ${
                  hidden
                    ? "bg-zinc-800 text-zinc-400 hover:text-zinc-200"
                    : "bg-emerald-900/30 text-emerald-300 hover:bg-emerald-900/50"
                }`}
              >
                {hidden ? <><EyeOff size={12} /> Hidden</> : <><Eye size={12} /> Shown</>}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

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
    // Choices may be plain strings (value === label) or {value, label} objects
    // (e.g. timezones, where the label shows the UTC offset but the stored
    // value is the bare IANA name).
    const opts = choices.map((c) =>
      c && typeof c === "object" ? { value: c.value, label: c.label ?? c.value } : { value: c, label: c },
    );
    const hasCurrent = opts.some((o) => String(o.value) === String(value ?? ""));
    return (
      <select
        className="w-full bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {!hasCurrent && <option value="" disabled>— Select —</option>}
        {opts.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>{String(o.label)}</option>
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
  // For an already-saved secret the server sends back "" (it never exposes the
  // value); show a placeholder so the user knows it's set and that leaving the
  // box blank keeps the current value.
  const secretPlaceholder = secret && field.set ? "•••••••• saved — type to replace" : "";
  return (
    <div className="flex items-center gap-2 w-full">
      <input
        type={showSecret ? "text" : "password"}
        className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100 font-mono"
        value={value ?? ""}
        placeholder={secretPlaceholder}
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
  // Labels of restart-required settings that changed on the last save; when
  // non-empty, a modal tells the user to restart the server.
  const [restartNotice, setRestartNotice] = useState([]);

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
      const res = await fetch(`${API}${app.is_panel ? "/panels" : "/apps"}/${app.id}`, {
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
      // If any changed key only takes effect at startup, prompt for a restart.
      const needRestart = (app.schema || [])
        .filter((f) => f.requires_restart && Object.prototype.hasOwnProperty.call(changed, f.key))
        .map((f) => f.label || f.key);
      if (needRestart.length) setRestartNotice(needRestart);
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
        {!app.is_panel && <span className="text-xs text-zinc-500">v{app.version || "?"}</span>}
      </div>
      <p className="text-sm text-zinc-500 mb-6">{app.description}</p>

      <div className="space-y-5">
        {app.schema.map((field) => (
          <div key={field.key}>
            <div className="flex items-baseline justify-between mb-1">
              <label className="text-sm text-zinc-300 font-medium">
                {field.label || field.key}
                <span className="ml-2 text-zinc-600 font-mono text-xs">{field.key}</span>
                {field.requires_restart && (
                  <span
                    className="ml-2 inline-flex items-center gap-1 text-[10px] text-amber-400/90 align-middle"
                    title="Takes effect after a server restart"
                  >
                    <RotateCcw size={10} /> restart
                  </span>
                )}
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

      {restartNotice.length > 0 && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setRestartNotice([])}
        >
          <div
            className="max-w-md w-full rounded-lg border border-amber-700/60 bg-zinc-900 p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3 text-amber-400">
              <RotateCcw size={18} />
              <h3 className="text-base font-semibold">Restart required</h3>
            </div>
            <p className="text-sm text-zinc-300">
              Your changes were saved, but {restartNotice.length === 1 ? "this setting" : "these settings"} only
              take effect after you restart the server:
            </p>
            <ul className="mt-2 mb-4 list-disc list-inside text-sm text-zinc-200">
              {restartNotice.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
            <div className="flex justify-end">
              <button
                className="px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium"
                onClick={() => setRestartNotice([])}
              >
                Got it
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar + top-level shell
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Members panel — household member management + self-service password change.
// Admins see the full roster (add / remove / change roles / reset password);
// every user sees the "Change my password" card.
// ---------------------------------------------------------------------------

const ROLE_OPTIONS = ["member", "parent", "admin"];

function hasRole(roleStr, role) {
  return (roleStr || "").split(",").map((r) => r.trim()).includes(role);
}

function MembersPanel({ userId }) {
  const [users, setUsers] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ username: "", display_name: "", roles: ["member"], password: "" });
  const [pw, setPw] = useState({ current: "", next: "" });
  const [pwMsg, setPwMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/users");
      setUsers(res.ok ? await res.json() : []);
    } catch {
      setUsers([]);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const me = (users || []).find((u) => u.name === userId);
  const isAdmin = !!me && hasRole(me.role, "admin");
  // Never let the household end up with zero admins — guard the controls that
  // could strip the last one (backend enforces this too; this is just UX).
  const adminCount = (users || []).filter((u) => hasRole(u.role, "admin")).length;

  const call = useCallback(async (url, opts = {}) => {
    setErr("");
    setBusy(true);
    try {
      const res = await fetch(url, opts);
      const j = await res.json().catch(() => ({}));
      if (!j.ok) { setErr(j.error || `Request failed (${res.status}).`); return false; }
      return true;
    } catch {
      setErr("Network error.");
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const json = (method, body) => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  async function addMember(e) {
    e.preventDefault();
    const ok = await call("/api/users", json("POST", {
      actor: userId,
      username: form.username,
      display_name: form.display_name,
      role: form.roles.join(",") || "member",
      password: form.password,
    }));
    if (ok) { setForm({ username: "", display_name: "", roles: ["member"], password: "" }); load(); }
  }

  async function removeMember(name) {
    if (!window.confirm(`Remove ${name}? This permanently deletes their account.`)) return;
    if (await call(`/api/users/${encodeURIComponent(name)}?actor=${encodeURIComponent(userId)}`, { method: "DELETE" })) load();
  }

  async function setRole(name, roleStr) {
    if (await call(`/api/users/${encodeURIComponent(name)}/role`, json("PATCH", { actor: userId, role: roleStr }))) load();
  }

  async function resetPassword(name) {
    const np = window.prompt(`New temporary password for ${name}.\nThey can change it after logging in (min 8 characters):`);
    if (np == null) return;
    if (await call(`/api/users/${encodeURIComponent(name)}/reset-password`, json("POST", { actor: userId, new_password: np }))) {
      window.alert(`Temporary password set for ${name}.`);
      load();
    }
  }

  async function changeMyPassword(e) {
    e.preventDefault();
    setPwMsg("");
    try {
      const res = await fetch("/api/auth/change-password", json("POST", {
        username: userId, current_password: pw.current, new_password: pw.next,
      }));
      const j = await res.json().catch(() => ({}));
      if (j.ok) { setPwMsg("Password changed."); setPw({ current: "", next: "" }); }
      else setPwMsg(j.error || "Could not change password.");
    } catch { setPwMsg("Network error."); }
  }

  const toggleFormRole = (role) =>
    setForm((f) => ({
      ...f,
      roles: f.roles.includes(role) ? f.roles.filter((r) => r !== role) : [...f.roles, role],
    }));

  if (users === null) {
    return <div className="flex items-center gap-2 p-6 text-zinc-500"><Loader2 className="animate-spin" size={14} /> Loading members…</div>;
  }

  const inputCls = "w-full rounded bg-zinc-900 border border-zinc-700 px-2.5 py-1.5 text-sm text-zinc-200 focus:border-indigo-500 focus:outline-none";

  return (
    <div className="p-6 max-w-2xl space-y-8">
      <div>
        <h2 className="text-base font-semibold text-zinc-200 inline-flex items-center gap-2"><Users size={16} /> Members</h2>
        <p className="text-xs text-zinc-500 mt-1">
          {isAdmin
            ? "Add or remove household members and set their roles. New members get a temporary password — they change it themselves after their first login."
            : "Change your own password below. Ask an admin to add or remove members."}
        </p>
      </div>

      {err && (
        <div className="flex items-center gap-2 rounded bg-red-950/50 border border-red-900 px-3 py-2 text-sm text-red-300">
          <AlertCircle size={14} /> {err}
        </div>
      )}

      {isAdmin && (
        <>
          {/* Roster */}
          <div className="rounded-lg border border-zinc-800 divide-y divide-zinc-800">
            {users.map((u) => (
              <div key={u.name} className="flex items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-zinc-200 truncate">
                    {u.display_name || u.name}
                    {u.name === userId && <span className="ml-1.5 text-[10px] text-zinc-500">(you)</span>}
                  </div>
                  <div className="text-[11px] text-zinc-500 truncate">
                    @{u.name}{!u.has_password && " · no password set"}
                  </div>
                </div>
                {/* Role pickers */}
                <div className="flex items-center gap-1.5">
                  {/* Read-only badges for roles that aren't user-togglable here
                      (e.g. `primary` — the single owner — or `kid`/`bot`). */}
                  {(u.role || "")
                    .split(",")
                    .map((r) => r.trim())
                    .filter((r) => r && !ROLE_OPTIONS.includes(r))
                    .map((role) => (
                      <span
                        key={role}
                        title={role === "primary" ? "Primary user (owner) — set in the database" : `${role} (not editable here)`}
                        className="px-2 py-0.5 rounded text-[11px] border border-amber-700/60 bg-amber-900/20 text-amber-300"
                      >
                        {role === "primary" && <Star size={10} className="inline mr-0.5 -mt-0.5" />}{role}
                      </span>
                    ))}
                  {ROLE_OPTIONS.map((role) => {
                    const on = hasRole(u.role, role);
                    // Can't un-toggle admin off the last remaining admin.
                    const lastAdmin = role === "admin" && on && adminCount <= 1;
                    return (
                      <button
                        key={role}
                        disabled={busy || lastAdmin}
                        onClick={() => {
                          const roles = u.role.split(",").map((r) => r.trim()).filter(Boolean);
                          const next = on ? roles.filter((r) => r !== role) : [...roles, role];
                          setRole(u.name, next.join(",") || "member");
                        }}
                        className={`px-2 py-0.5 rounded text-[11px] border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                          on
                            ? "bg-indigo-600/30 border-indigo-600 text-indigo-200"
                            : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                        }`}
                        title={lastAdmin ? "At least one admin is required" : on ? `Remove ${role}` : `Grant ${role}`}
                      >
                        {role === "admin" && <ShieldCheck size={10} className="inline mr-0.5 -mt-0.5" />}{role}
                      </button>
                    );
                  })}
                </div>
                <button onClick={() => resetPassword(u.name)} disabled={busy}
                  title="Set a temporary password" className="text-zinc-500 hover:text-amber-400 p-1">
                  <KeyRound size={14} />
                </button>
                <button onClick={() => removeMember(u.name)}
                  disabled={busy || u.name === userId || (hasRole(u.role, "admin") && adminCount <= 1)}
                  title={
                    u.name === userId
                      ? "You can't remove yourself"
                      : hasRole(u.role, "admin") && adminCount <= 1
                        ? "Can't remove the last admin"
                        : "Remove member"
                  }
                  className="text-zinc-500 hover:text-red-400 p-1 disabled:opacity-30 disabled:hover:text-zinc-500">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>

          {/* Add member */}
          <form onSubmit={addMember} className="rounded-lg border border-zinc-800 p-4 space-y-3">
            <h3 className="text-sm font-medium text-zinc-300 inline-flex items-center gap-2"><UserPlus size={14} /> Add a member</h3>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-[11px] text-zinc-500">Username (login)</span>
                <input className={inputCls} value={form.username} required
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  placeholder="e.g. alex" autoComplete="off" />
              </label>
              <label className="block">
                <span className="text-[11px] text-zinc-500">Display name</span>
                <input className={inputCls} value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  placeholder="e.g. Alex" autoComplete="off" />
              </label>
            </div>
            <label className="block">
              <span className="text-[11px] text-zinc-500">Temporary password (min 8 characters)</span>
              <input className={inputCls} value={form.password} required minLength={8} type="text"
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="at least 8 characters — they can change it later" autoComplete="new-password" />
            </label>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-zinc-500 mr-1">Roles:</span>
              {ROLE_OPTIONS.map((role) => (
                <label key={role} className="inline-flex items-center gap-1 text-xs text-zinc-400">
                  <input type="checkbox" checked={form.roles.includes(role)} onChange={() => toggleFormRole(role)} />
                  {role}
                </label>
              ))}
            </div>
            <button type="submit" disabled={busy}
              className="rounded bg-indigo-600 hover:bg-indigo-500 px-3 py-1.5 text-sm font-medium text-white inline-flex items-center gap-1.5 disabled:opacity-50">
              <UserPlus size={14} /> Add member
            </button>
          </form>
        </>
      )}

      {/* Change my own password — everyone */}
      <form onSubmit={changeMyPassword} className="rounded-lg border border-zinc-800 p-4 space-y-3">
        <h3 className="text-sm font-medium text-zinc-300 inline-flex items-center gap-2"><KeyRound size={14} /> Change my password</h3>
        <p className="text-[11px] text-zinc-500 -mt-1">Signed in as @{userId}.</p>
        <label className="block">
          <span className="text-[11px] text-zinc-500">Current password</span>
          <input className={inputCls} type="password" value={pw.current} autoComplete="current-password"
            onChange={(e) => setPw({ ...pw, current: e.target.value })} />
        </label>
        <label className="block">
          <span className="text-[11px] text-zinc-500">New password (min 8 characters)</span>
          <input className={inputCls} type="password" value={pw.next} required minLength={8} autoComplete="new-password"
            onChange={(e) => setPw({ ...pw, next: e.target.value })} />
        </label>
        {pwMsg && <div className="text-xs text-zinc-400">{pwMsg}</div>}
        <button type="submit"
          className="rounded bg-zinc-700 hover:bg-zinc-600 px-3 py-1.5 text-sm font-medium text-white inline-flex items-center gap-1.5">
          <Save size={14} /> Update password
        </button>
      </form>
    </div>
  );
}

export default function SettingsApp({ userId }) {
  const [apps, setApps] = useState([]);
  const [panels, setPanels] = useState([]);   // platform panels: System, Integrations
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState("__desktop__");

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [appsRes, panelsRes] = await Promise.all([
        fetch(`${API}/apps`),
        fetch(`${API}/panels`),
      ]);
      if (appsRes.ok) setApps((await appsRes.json()).apps || []);
      if (panelsRes.ok) setPanels((await panelsRes.json()).panels || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onSaved = (fresh) => {
    // Replace the cached app/panel with the server's authoritative version.
    setApps((prev) => prev.map((a) => (a.id === fresh.id ? { ...a, ...fresh } : a)));
    setPanels((prev) => prev.map((p) => (p.id === fresh.id ? { ...p, ...fresh } : p)));
  };

  const current = useMemo(
    // Platform panels are selected under a "panel:" key so a panel can never be
    // shadowed by an app sharing its id (e.g. the "system" app vs the System panel).
    () => apps.find((a) => a.id === selected) || panels.find((p) => `panel:${p.id}` === selected),
    [apps, panels, selected],
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
          <li>
            <button
              className={`w-full text-left px-4 py-2 text-sm transition-colors inline-flex items-center gap-2 ${
                selected === "__desktop__" ? "bg-zinc-800 text-zinc-100" : "text-zinc-300 hover:bg-zinc-900"
              }`}
              onClick={() => setSelected("__desktop__")}
            >
              <LayoutGrid size={14} /> Desktop apps
            </button>
          </li>
          <li>
            <button
              className={`w-full text-left px-4 py-2 text-sm transition-colors inline-flex items-center gap-2 ${
                selected === "__members__" ? "bg-zinc-800 text-zinc-100" : "text-zinc-300 hover:bg-zinc-900"
              }`}
              onClick={() => setSelected("__members__")}
            >
              <Users size={14} /> Members
            </button>
          </li>
          {panels.map((p) => (
            <li key={p.id}>
              <button
                className={`w-full text-left px-4 py-2 text-sm transition-colors inline-flex items-center gap-2 ${
                  selected === `panel:${p.id}` ? "bg-zinc-800 text-zinc-100" : "text-zinc-300 hover:bg-zinc-900"
                }`}
                onClick={() => setSelected(`panel:${p.id}`)}
              >
                <Cog size={14} /> {p.name}
              </button>
            </li>
          ))}
          {/* Only apps that actually have configurable settings. Apps with an
              empty config: schema (e.g. the System app, and the Settings app
              itself) would render a blank "no settings" page, so we hide them
              here. The platform-level panels (System/Integrations) above are a
              separate list and are unaffected. */}
          {(() => {
            const configurable = apps.filter((a) => a.has_settings);
            if (configurable.length === 0) return null;
            return (
              <>
                <li className="px-4 pt-2 pb-1 text-[10px] uppercase tracking-wide text-zinc-600">App settings</li>
                {configurable.map((a) => {
                  const isCurrent = a.id === selected;
                  return (
                    <li key={a.id}>
                      <button
                        className={`w-full text-left px-4 py-2 text-sm transition-colors flex items-baseline justify-between gap-2 ${
                          isCurrent ? "bg-zinc-800 text-zinc-100" : "text-zinc-300 hover:bg-zinc-900"
                        }`}
                        onClick={() => setSelected(a.id)}
                      >
                        <span className="truncate">{a.name || a.id}</span>
                        <span className="text-xs text-zinc-600">{a.schema.length}</span>
                      </button>
                    </li>
                  );
                })}
              </>
            );
          })()}
        </ul>
      </aside>
      <main className="flex-1 overflow-y-auto">
        {selected === "__desktop__" ? (
          <DesktopVisibilityPanel />
        ) : selected === "__members__" ? (
          <MembersPanel userId={userId} />
        ) : current ? (
          <AppDetail key={selected} app={current} onSaved={onSaved} />
        ) : (
          <div className="p-6 text-zinc-500">Select an app to view its settings.</div>
        )}
      </main>
    </div>
  );
}
