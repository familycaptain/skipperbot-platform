import { useState, useEffect, useCallback } from "react";
import {
  Newspaper, Settings, Users, Play, FlaskConical, RefreshCw,
  Plus, Trash2, Check, X, ChevronDown, Loader2, AlertCircle,
  Mail, Crown, ToggleLeft, ToggleRight
} from "lucide-react";

const API = "/api/apps/newsletter";

function api(path, opts = {}) {
  return fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e)));
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  const map = {
    pending:    "bg-zinc-700/50 text-zinc-400",
    generating: "bg-blue-900/40 text-blue-300",
    generated:  "bg-amber-900/40 text-amber-300",
    sent:       "bg-green-900/40 text-green-300",
    error:      "bg-red-900/40 text-red-300",
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${map[status] || "bg-zinc-700/50 text-zinc-400"}`}>
      {status}
    </span>
  );
}

function LevelBadge({ level }) {
  return level === "paid"
    ? <span className="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-700/40"><Crown size={9} /> paid</span>
    : <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-700/50 text-zinc-400">free</span>;
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({ userId }) {
  const [editions, setEditions] = useState([]);
  const [runState, setRunState] = useState(null); // null | {job_id, label, polling}
  const [runStatus, setRunStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadEditions = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api("/editions?limit=15");
      setEditions(d.editions || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadEditions(); }, [loadEditions]);

  // Poll job status after triggering a run
  useEffect(() => {
    if (!runState?.job_id || runState.polling === false) return;
    const iv = setInterval(async () => {
      try {
        const job = await fetch(`/api/jobs/${runState.job_id}`).then(r => r.json());
        setRunStatus({ status: job.status, progress: job.progress_pct, msg: job.progress_msg });
        if (["completed", "failed", "cancelled"].includes(job.status)) {
          setRunState(s => ({ ...s, polling: false }));
          loadEditions();
        }
      } catch {}
    }, 2500);
    return () => clearInterval(iv);
  }, [runState, loadEditions]);

  async function handleRun(test = false) {
    setRunState({ label: test ? "Test Run" : "Full Run", polling: true, job_id: null });
    setRunStatus(null);
    try {
      const data = await api(test ? "/run-test" : "/run", {
        method: "POST",
        body: JSON.stringify({ created_by: userId || "ui" }),
      });
      setRunState(s => ({ ...s, job_id: data.job_id }));
    } catch (e) {
      setRunState(null);
      setRunStatus({ status: "error", msg: e?.detail || String(e) });
    }
  }

  const running = runState?.polling && runState?.job_id;

  return (
    <div className="p-4 space-y-5">
      {/* Run buttons */}
      <div className="flex gap-3">
        <button
          onClick={() => handleRun(false)}
          disabled={!!runState?.polling}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors"
        >
          {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          Run Now
        </button>
        <button
          onClick={() => handleRun(true)}
          disabled={!!runState?.polling}
          className="flex items-center gap-2 px-4 py-2 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors"
        >
          {running ? <Loader2 size={15} className="animate-spin" /> : <FlaskConical size={15} />}
          Test Run
        </button>
        <button
          onClick={loadEditions}
          className="p-2 text-zinc-500 hover:text-zinc-300 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Job status */}
      {runState && (
        <div className={`flex items-start gap-2 p-3 rounded-lg text-sm ${
          runStatus?.status === "error" ? "bg-red-900/20 border border-red-700/40 text-red-300" :
          runStatus?.status === "completed" ? "bg-green-900/20 border border-green-700/40 text-green-300" :
          "bg-zinc-800/50 border border-zinc-700/30 text-zinc-300"
        }`}>
          {running ? <Loader2 size={14} className="animate-spin mt-0.5 shrink-0 text-blue-400" /> :
           runStatus?.status === "error" ? <AlertCircle size={14} className="mt-0.5 shrink-0" /> :
           runStatus?.status === "completed" ? <Check size={14} className="mt-0.5 shrink-0" /> :
           <Check size={14} className="mt-0.5 shrink-0" />}
          <div className="flex-1 min-w-0">
            <span className="font-medium">{runState.label}</span>
            {runState.job_id && <span className="text-zinc-500 ml-2 font-mono text-xs">{runState.job_id}</span>}
            {runStatus?.msg && <div className="text-xs text-zinc-400 mt-0.5">{runStatus.msg}</div>}
            {running && runStatus?.progress != null && (
              <div className="mt-1.5 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500 transition-all" style={{ width: `${runStatus.progress}%` }} />
              </div>
            )}
          </div>
          <button onClick={() => { setRunState(null); setRunStatus(null); }} className="text-zinc-600 hover:text-zinc-400">
            <X size={13} />
          </button>
        </div>
      )}

      {/* Editions list */}
      <div>
        <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">Recent Editions</h2>
        {loading ? (
          <div className="flex items-center gap-2 text-zinc-500 text-sm py-4"><Loader2 size={14} className="animate-spin" /> Loading…</div>
        ) : editions.length === 0 ? (
          <p className="text-zinc-500 text-sm py-4">No editions yet.</p>
        ) : (
          <div className="space-y-1">
            {editions.map(e => (
              <div key={e.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-zinc-800/40 border border-zinc-700/30">
                <span className="font-mono text-sm text-zinc-200 w-28 shrink-0">{e.edition_date}</span>
                <StatusBadge status={e.status} />
                {e.regime_label && <span className="text-xs text-zinc-500 truncate">{e.regime_label}</span>}
                {e.best_bet_symbol && (
                  <span className="ml-auto text-xs text-amber-400 shrink-0">
                    {e.best_bet_symbol}
                  </span>
                )}
                {e.sent_at && (
                  <span className="text-xs text-zinc-600 shrink-0">
                    sent {new Date(e.sent_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config Tab
// ---------------------------------------------------------------------------

function ConfigTab() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api("/config").then(d => {
      setCfg(d);
      setForm({
        product_name: d.product_name || "",
        product_tagline: d.product_tagline || "",
        from_name: d.from_name || "",
        from_address: d.from_address || "",
        delivery_time_et: d.delivery_time_et || "",
        enabled: d.enabled ?? true,
        test_email: d.test_email || "",
        disclosure_short: d.disclosure_short || "",
        chart_output_dir: d.chart_output_dir || "",
        performance_lookback_days: d.performance_lookback_days ?? 30,
        primary_signal_label: d.primary_signal_label || "",
        outlook_label: d.outlook_label || "",
      });
    }).catch(() => {});
  }, []);

  async function save() {
    setSaving(true);
    try {
      const updated = await api("/config", {
        method: "PUT",
        body: JSON.stringify(form),
      });
      setCfg(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
    setSaving(false);
  }

  function field(label, key, type = "text", hint = "") {
    return (
      <div>
        <label className="text-xs text-zinc-500 block mb-1">{label}</label>
        {type === "textarea" ? (
          <textarea
            value={form[key] || ""}
            onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
            rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
          />
        ) : type === "toggle" ? (
          <button
            onClick={() => setForm(f => ({ ...f, [key]: !f[key] }))}
            className={`flex items-center gap-2 text-sm ${form[key] ? "text-green-400" : "text-zinc-500"}`}
          >
            {form[key] ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
            {form[key] ? "Enabled" : "Disabled"}
          </button>
        ) : (
          <input
            type={type}
            value={form[key] ?? ""}
            onChange={e => setForm(f => ({ ...f, [key]: type === "number" ? Number(e.target.value) : e.target.value }))}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
          />
        )}
        {hint && <p className="text-xs text-zinc-600 mt-0.5">{hint}</p>}
      </div>
    );
  }

  if (!cfg) return <div className="p-4 text-zinc-500 text-sm flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</div>;

  return (
    <div className="p-4 space-y-6 max-w-xl">
      {/* Identity */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">Identity</h2>
        {field("Product Name", "product_name")}
        {field("Tagline", "product_tagline")}
        {field("From Name", "from_name")}
        {field("From Address", "from_address", "email")}
        {field("Primary Signal Label", "primary_signal_label")}
        {field("Outlook Label", "outlook_label")}
        {field("Short Disclosure", "disclosure_short", "textarea")}
      </section>

      {/* Delivery */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">Delivery</h2>
        {field("Pipeline Enabled", "enabled", "toggle")}
        {field("Delivery Time (ET)", "delivery_time_et", "text", "HH:MM in Eastern Time, e.g. 08:00")}
        {field("Test Email", "test_email", "email", "Address used for Test Run — sends only here")}
      </section>

      {/* Charts */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">Charts</h2>
        {field("Chart Output Directory", "chart_output_dir")}
        {field("Performance Lookback Days", "performance_lookback_days", "number")}
      </section>

      <button
        onClick={save}
        disabled={saving}
        className="flex items-center gap-2 px-4 py-2 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors"
      >
        {saving ? <Loader2 size={14} className="animate-spin" /> : saved ? <Check size={14} /> : null}
        {saved ? "Saved!" : "Save Config"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subscribers Tab
// ---------------------------------------------------------------------------

function SubscribersTab() {
  const [subs, setSubs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addForm, setAddForm] = useState({ email: "", name: "", level: "free" });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api("/subscribers");
      setSubs(d.subscribers || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleAdd(e) {
    e.preventDefault();
    if (!addForm.email.trim()) return;
    setAdding(true);
    setAddError("");
    try {
      await api("/subscribers", {
        method: "POST",
        body: JSON.stringify(addForm),
      });
      setAddForm({ email: "", name: "", level: "free" });
      load();
    } catch (err) {
      setAddError(err?.detail || "Failed to add subscriber");
    }
    setAdding(false);
  }

  async function handleToggleActive(sub) {
    await api(`/subscribers/${sub.id}`, {
      method: "PATCH",
      body: JSON.stringify({ active: !sub.active }),
    });
    setSubs(s => s.map(x => x.id === sub.id ? { ...x, active: !x.active } : x));
  }

  async function handleToggleLevel(sub) {
    const newLevel = sub.level === "paid" ? "free" : "paid";
    await api(`/subscribers/${sub.id}`, {
      method: "PATCH",
      body: JSON.stringify({ level: newLevel }),
    });
    setSubs(s => s.map(x => x.id === sub.id ? { ...x, level: newLevel } : x));
  }

  async function handleDelete(sub) {
    if (!confirm(`Remove ${sub.email}?`)) return;
    await api(`/subscribers/${sub.id}`, { method: "DELETE" });
    setSubs(s => s.filter(x => x.id !== sub.id));
  }

  const active = subs.filter(s => s.active).length;
  const paid = subs.filter(s => s.level === "paid").length;

  return (
    <div className="p-4 space-y-4">
      {/* Stats row */}
      <div className="flex gap-4 text-sm text-zinc-400">
        <span><span className="text-zinc-100 font-semibold">{subs.length}</span> total</span>
        <span><span className="text-green-400 font-semibold">{active}</span> active</span>
        <span><span className="text-amber-400 font-semibold">{paid}</span> paid</span>
      </div>

      {/* Subscriber list */}
      {loading ? (
        <div className="flex items-center gap-2 text-zinc-500 text-sm py-4"><Loader2 size={14} className="animate-spin" /> Loading…</div>
      ) : subs.length === 0 ? (
        <p className="text-zinc-500 text-sm py-4">No subscribers yet.</p>
      ) : (
        <div className="space-y-1">
          {subs.map(sub => (
            <div
              key={sub.id}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors ${
                sub.active
                  ? "bg-zinc-800/40 border-zinc-700/30"
                  : "bg-zinc-900/40 border-zinc-800/30 opacity-60"
              }`}
            >
              <Mail size={13} className="text-zinc-600 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-zinc-200 truncate">{sub.email}</div>
                {sub.name && <div className="text-xs text-zinc-500">{sub.name}</div>}
              </div>
              <LevelBadge level={sub.level} />
              <button
                onClick={() => handleToggleLevel(sub)}
                className="text-zinc-600 hover:text-amber-400 transition-colors p-1"
                title={sub.level === "paid" ? "Downgrade to free" : "Upgrade to paid"}
              >
                <Crown size={13} />
              </button>
              <button
                onClick={() => handleToggleActive(sub)}
                className={`transition-colors p-1 ${sub.active ? "text-green-500 hover:text-zinc-400" : "text-zinc-600 hover:text-green-400"}`}
                title={sub.active ? "Deactivate" : "Activate"}
              >
                {sub.active ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
              </button>
              <button
                onClick={() => handleDelete(sub)}
                className="text-zinc-700 hover:text-red-400 transition-colors p-1"
                title="Delete"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add form */}
      <form onSubmit={handleAdd} className="pt-2 border-t border-zinc-800/60">
        <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-3">Add Subscriber</h3>
        <div className="flex gap-2 flex-wrap">
          <input
            type="email"
            placeholder="email@example.com"
            value={addForm.email}
            onChange={e => setAddForm(f => ({ ...f, email: e.target.value }))}
            required
            className="flex-1 min-w-40 bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
          />
          <input
            type="text"
            placeholder="Name (optional)"
            value={addForm.name}
            onChange={e => setAddForm(f => ({ ...f, name: e.target.value }))}
            className="w-40 bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
          />
          <select
            value={addForm.level}
            onChange={e => setAddForm(f => ({ ...f, level: e.target.value }))}
            className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none"
          >
            <option value="free">Free</option>
            <option value="paid">Paid</option>
          </select>
          <button
            type="submit"
            disabled={adding}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white rounded text-sm transition-colors"
          >
            {adding ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            Add
          </button>
        </div>
        {addError && <p className="text-red-400 text-xs mt-2">{addError}</p>}
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function NewsletterApp({ userId }) {
  const [tab, setTab] = useState("overview");

  const tabs = [
    { id: "overview",     label: "Overview",     icon: Newspaper },
    { id: "config",       label: "Config",        icon: Settings },
    { id: "subscribers",  label: "Subscribers",   icon: Users },
  ];

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-zinc-100">
      {/* Tab bar */}
      <div className="flex border-b border-zinc-800 shrink-0">
        {tabs.map(t => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm border-b-2 transition-colors ${
                tab === t.id
                  ? "border-blue-500 text-blue-400"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <Icon size={14} />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {tab === "overview"    && <OverviewTab userId={userId} />}
        {tab === "config"      && <ConfigTab />}
        {tab === "subscribers" && <SubscribersTab />}
      </div>
    </div>
  );
}
