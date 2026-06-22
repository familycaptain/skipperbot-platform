import { useState, useEffect, useCallback } from "react";
import {
  DollarSign, Trophy, LayoutList, FileText, Settings,
  Plus, Check, X, ChevronDown, ChevronUp, Clock, Award,
  Send, CreditCard, RefreshCw, Pencil, Trash2,
} from "lucide-react";
import { hasAnyRole } from "../../../web/src/utils/roles";

const API = "/api/apps/bounties";

const TABS = [
  { id: "board",       label: "Board",       icon: LayoutList },
  { id: "balance",     label: "My Balance",  icon: DollarSign },
  { id: "leaderboard", label: "Leaderboard", icon: Trophy },
  { id: "templates",   label: "Templates",   icon: FileText, parentOnly: true },
  { id: "settings",    label: "Settings",    icon: Settings, parentOnly: true },
];

const STATUS_COLORS = {
  open:      "bg-green-600/20 text-green-400 border-green-600/30",
  submitted: "bg-amber-600/20 text-amber-400 border-amber-600/30",
  approved:  "bg-blue-600/20 text-blue-400 border-blue-600/30",
  rejected:  "bg-red-600/20 text-red-400 border-red-600/30",
  expired:   "surface-raised text-muted border-subtle",
  cancelled: "surface-raised text-muted border-subtle",
};

function cents(v) { return `$${(v / 100).toFixed(2)}`; }

export default function BountiesApp({ appId, userId, userRole, context = {}, onTitle, refreshKey, isActive }) {
  const [activeTab, setActiveTab] = useState(context.tab || "board");
  const isParentUser = hasAnyRole(userRole, ["admin", "parent"]);
  const visibleTabs = TABS.filter((tab) => !tab.parentOnly || isParentUser);

  useEffect(() => {
    if (!visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab("board");
    }
  }, [activeTab, visibleTabs]);

  return (
    <div className="flex flex-col h-full w-full">
      <div className="flex items-center gap-1 px-3 h-10 surface-panel border-b border-subtle shrink-0 overflow-x-auto">
        {visibleTabs.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md whitespace-nowrap transition-colors ${
                active ? "bg-indigo-600 text-on-accent" : "text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-card)]"
              }`}
            >
              <Icon size={13} />
              {tab.label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-y-auto">
        {activeTab === "board"       && <BoardTab userId={userId} userRole={userRole} refreshKey={refreshKey} />}
        {activeTab === "balance"     && <BalanceTab userId={userId} userRole={userRole} refreshKey={refreshKey} />}
        {activeTab === "leaderboard" && <LeaderboardTab refreshKey={refreshKey} />}
        {activeTab === "templates"   && <TemplatesTab userId={userId} userRole={userRole} refreshKey={refreshKey} />}
        {activeTab === "settings"    && <SettingsTab userId={userId} userRole={userRole} refreshKey={refreshKey} />}
      </div>
    </div>
  );
}


// ==========================================================================
// Board Tab
// ==========================================================================

function BoardTab({ userId, userRole, refreshKey }) {
  const [bounties, setBounties] = useState([]);
  const [summary, setSummary] = useState({ open: 0, submitted: 0, approved: 0 });
  const [categories, setCategories] = useState([]);
  const [filterCat, setFilterCat] = useState("All");
  const [filterStatus, setFilterStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filterStatus) params.set("status", filterStatus);
    if (filterCat !== "All") params.set("category", filterCat);
    try {
      const [bRes, allRes, cRes] = await Promise.all([
        fetch(`${API}?${params}`),
        fetch(`${API}`),
        fetch(`${API}/categories`),
      ]);
      const bData = await bRes.json();
      const allData = await allRes.json();
      const cData = await cRes.json();
      setBounties(bData.bounties || []);
      setCategories(cData.categories || []);
      const all = allData.bounties || [];
      setSummary({
        open:      all.filter(b => b.status === "open").reduce((s, b) => s + b.value_cents, 0),
        submitted: all.filter(b => b.status === "submitted").reduce((s, b) => s + b.value_cents, 0),
        approved:  all.filter(b => b.status === "approved").reduce((s, b) => s + b.value_cents, 0),
      });
    } catch (e) { console.error("Load bounties failed:", e); }
    setLoading(false);
  }, [filterCat, filterStatus]);

  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <div className="p-4 space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "Open",      value: summary.open,      color: "text-green-400",  bg: "bg-green-600/10 border-green-600/20" },
          { label: "Submitted", value: summary.submitted,  color: "text-amber-400",  bg: "bg-amber-600/10 border-amber-600/20" },
          { label: "Approved",  value: summary.approved,   color: "text-blue-400",   bg: "bg-blue-600/10  border-blue-600/20" },
        ].map(({ label, value, color, bg }) => (
          <div key={label} className={`rounded-lg border px-3 py-2 text-center ${bg}`}>
            <div className={`text-base font-bold ${color}`}>{cents(value)}</div>
            <div className="text-[10px] text-faint mt-0.5">{label}</div>
          </div>
        ))}
      </div>
      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          className="surface-card text-xs text-default rounded px-2 py-1.5 border border-subtle">
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="submitted">Submitted</option>
          <option value="approved">Approved</option>
        </select>
        <div className="flex items-center gap-1 overflow-x-auto flex-1 min-w-0">
          {["All", ...categories.map(c => c.name)].map(cat => (
            <button key={cat} onClick={() => setFilterCat(cat)}
              className={`px-2 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
                filterCat === cat ? "bg-indigo-600 text-on-accent" : "surface-card text-muted hover:text-[var(--ds-text)]"
              }`}>{cat}</button>
          ))}
        </div>
        {isParent && (
          <button onClick={() => setShowCreate(!showCreate)}
            className="flex items-center gap-1 px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500 shrink-0"
            title="New Bounty">
            <Plus size={13} /> <span className="hidden sm:inline">New Bounty</span>
          </button>
        )}
        <button onClick={load} className="p-1.5 text-muted hover:text-[var(--ds-text)] rounded-md hover:bg-[var(--ds-card)] shrink-0"
          title="Refresh">
          <RefreshCw size={14} />
        </button>
      </div>

      {showCreate && <CreateBountyForm categories={categories} userId={userId}
        onCreated={() => { setShowCreate(false); load(); }} onCancel={() => setShowCreate(false)} />}

      {loading ? (
        <div className="text-faint text-sm">Loading...</div>
      ) : bounties.length === 0 ? (
        <div className="text-faint text-sm">No bounties found.</div>
      ) : (
        <div className="space-y-2">
          {bounties.map(b => (
            <BountyCard key={b.id} bounty={b} userId={userId} userRole={userRole} categories={categories} onRefresh={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function CreateBountyForm({ categories, userId, onCreated, onCancel }) {
  const [form, setForm] = useState({ title: "", value: "", category: "", description: "" });
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title.trim() || !form.value) return;
    setSaving(true);
    try {
      await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: form.title.trim(),
          value_cents: Math.round(parseFloat(form.value) * 100),
          created_by: userId || "",
          category: form.category,
          description: form.description.trim(),
        }),
      });
      onCreated();
    } catch (e) { console.error("Create bounty failed:", e); }
    setSaving(false);
  }

  return (
    <form onSubmit={handleSubmit} className="surface-card rounded-lg p-3 space-y-2 border border-subtle">
      <div className="flex gap-2">
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Bounty title" className="flex-1 min-w-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
        <input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })}
          placeholder="$ value" type="number" step="0.01" min="0.01"
          className="w-20 sm:w-24 shrink-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex flex-wrap gap-2">
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
          className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle max-w-full">
          <option value="">No category</option>
          {categories.map(c => <option key={c.id} value={c.name}>{c.icon} {c.name}</option>)}
        </select>
        <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Description (optional)" className="flex-1 min-w-[10rem] surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button type="submit" disabled={saving || !form.title.trim() || !form.value}
          className="px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500 disabled:opacity-50">
          {saving ? "Creating..." : "Create"}
        </button>
      </div>
    </form>
  );
}

function BountyCard({ bounty: b, userId, userRole, categories = [], onRefresh }) {
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  async function deleteBounty() {
    setBusy(true);
    try {
      const params = new URLSearchParams({ acted_by: userId || "" });
      await fetch(`${API}/bounty/${b.id}?${params}`, { method: "DELETE" });
      onRefresh();
    } catch (e) { console.error("Delete bounty failed:", e); }
    setBusy(false);
  }

  async function doAction(action) {
    setBusy(true);
    try {
      let body;
      if (action === "submit") body = { submitted_by: userId || "", note };
      else if (action === "skip") body = { skipped_by: userId || "" };
      else body = { reviewed_by: userId || "", note };
      await fetch(`${API}/bounty/${b.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setNote("");
      onRefresh();
    } catch (e) { console.error(`${action} failed:`, e); }
    setBusy(false);
  }

  return (
    <div className="surface-card rounded-lg border border-subtle overflow-hidden">
      <div className="flex items-center gap-2 sm:gap-3 px-3 py-2.5 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <span className={`px-2 py-0.5 text-[10px] rounded border shrink-0 ${STATUS_COLORS[b.status] || ""}`}>
          {b.status.toUpperCase()}
        </span>
        <span className="text-sm text-default font-medium flex-1 min-w-0 break-words">{b.title}</span>
        {b.category && <span className="hidden sm:inline text-[10px] text-faint shrink-0">{b.category}</span>}
        <span className="text-sm font-bold text-emerald-400 shrink-0">{cents(b.value_cents)}</span>
        {expanded ? <ChevronUp size={14} className="text-faint shrink-0" /> : <ChevronDown size={14} className="text-faint shrink-0" />}
      </div>
      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-subtle space-y-2">
          {editing ? (
            <EditBountyForm bounty={b} categories={categories} userId={userId}
              onSaved={() => { setEditing(false); onRefresh(); }}
              onCancel={() => setEditing(false)} />
          ) : (
          <>
          {isParent && (
            <div className="flex justify-end gap-1">
              <button onClick={(e) => { e.stopPropagation(); setEditing(true); setConfirmDelete(false); }}
                className="flex items-center gap-1 px-2 py-1 text-[10px] text-muted hover:text-[var(--ds-text)] surface-raised hover:bg-[var(--ds-raised)] rounded">
                <Pencil size={10} /> Edit
              </button>
              {b.status !== "approved" && (
                confirmDelete ? (
                  <div className="flex items-center gap-1">
                    <span className="text-[10px] text-red-400">Delete?</span>
                    <button onClick={(e) => { e.stopPropagation(); deleteBounty(); }} disabled={busy}
                      className="px-2 py-1 text-[10px] bg-red-600 text-on-accent rounded hover:bg-red-500 disabled:opacity-50">Yes</button>
                    <button onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}
                      className="px-2 py-1 text-[10px] text-muted hover:text-[var(--ds-text)] surface-raised hover:bg-[var(--ds-raised)] rounded">No</button>
                  </div>
                ) : (
                  <button onClick={(e) => { e.stopPropagation(); setConfirmDelete(true); }}
                    className="flex items-center gap-1 px-2 py-1 text-[10px] text-muted hover:text-red-400 surface-raised hover:bg-[var(--ds-raised)] rounded">
                    <Trash2 size={10} /> Delete
                  </button>
                )
              )}
            </div>
          )}
          {b.description && <p className="text-xs text-muted">{b.description}</p>}
          <div className="text-[10px] text-faint space-y-0.5">
            {b.submitted_by && <div>Submitted by {b.submitted_by} {b.submitted_at && `• ${new Date(b.submitted_at).toLocaleDateString()}`}</div>}
            {b.submission_note && <div>Note: {b.submission_note}</div>}
            {b.reviewed_by && <div>Reviewed by {b.reviewed_by} {b.reviewed_at && `• ${new Date(b.reviewed_at).toLocaleDateString()}`}</div>}
            {b.review_note && <div>Feedback: {b.review_note}</div>}
            {b.expires_at && <div className="flex items-center gap-1"><Clock size={10} /> Expires: {new Date(b.expires_at).toLocaleDateString()}</div>}
            <div>ID: {b.id}</div>
          </div>
          {(b.status === "open" || b.status === "submitted") && (
            <div className="flex flex-col sm:flex-row sm:items-center gap-2 pt-1">
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)"
                className="w-full sm:flex-1 surface-panel text-xs text-default px-2 py-1.5 rounded border border-subtle" />
              <div className="flex items-center gap-2 flex-wrap">
                {b.status === "open" && (
                  <>
                    <button onClick={() => doAction("submit")} disabled={busy}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs bg-amber-600 text-on-accent rounded hover:bg-amber-500 disabled:opacity-50">
                      <Send size={11} /> I Did It
                    </button>
                    {isParent && (
                      <button onClick={() => doAction("skip")} disabled={busy} title="Parent did this — skip and cool down"
                        className="flex items-center gap-1 px-3 py-1.5 text-xs surface-raised text-default rounded hover:bg-[var(--ds-raised)] disabled:opacity-50">
                        <X size={11} /> Skip
                      </button>
                    )}
                  </>
                )}
                {b.status === "submitted" && isParent && (
                  <>
                    <button onClick={() => doAction("approve")} disabled={busy}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs bg-green-600 text-on-accent rounded hover:bg-green-500 disabled:opacity-50">
                      <Check size={11} /> Approve
                    </button>
                    <button onClick={() => doAction("reject")} disabled={busy}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs bg-red-600 text-on-accent rounded hover:bg-red-500 disabled:opacity-50">
                      <X size={11} /> Reject
                    </button>
                  </>
                )}
                {b.status === "submitted" && !isParent && (
                  <span className="text-xs text-amber-400 italic">Awaiting parent approval</span>
                )}
              </div>
            </div>
          )}
          </>
          )}
        </div>
      )}
    </div>
  );
}

function EditBountyForm({ bounty, categories, userId, onSaved, onCancel }) {
  const [form, setForm] = useState({
    title: bounty.title || "",
    value: ((bounty.value_cents || 0) / 100).toFixed(2),
    category: bounty.category || "",
    description: bounty.description || "",
  });
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title.trim() || !form.value) return;
    setSaving(true);
    try {
      await fetch(`${API}/bounty/${bounty.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          updated_by: userId || "",
          title: form.title.trim(),
          value_cents: Math.round(parseFloat(form.value) * 100),
          category: form.category,
          description: form.description.trim(),
        }),
      });
      onSaved();
    } catch (e) { console.error("Edit bounty failed:", e); }
    setSaving(false);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <div className="flex gap-2">
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Bounty title" className="flex-1 min-w-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
        <input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })}
          placeholder="$ value" type="number" step="0.01" min="0.01"
          className="w-20 sm:w-24 shrink-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex flex-wrap gap-2">
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
          className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle max-w-full">
          <option value="">No category</option>
          {categories.map(c => <option key={c.id} value={c.name}>{c.icon} {c.name}</option>)}
        </select>
        <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Description (optional)" className="flex-1 min-w-[10rem] surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
        <button type="submit" disabled={saving || !form.title.trim() || !form.value}
          className="px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500 disabled:opacity-50">
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </form>
  );
}


// ==========================================================================
// Balance Tab
// ==========================================================================

function BalanceTab({ userId, userRole, refreshKey }) {
  const [balance, setBalance] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [allBalances, setAllBalances] = useState([]);
  const [showPay, setShowPay] = useState(null);
  const [loading, setLoading] = useState(true);
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [bRes, allRes] = await Promise.all([
        userId ? fetch(`${API}/balances/${userId}`) : Promise.resolve(null),
        fetch(`${API}/balances`),
      ]);
      if (bRes) {
        const bData = await bRes.json();
        setBalance(bData.balance || null);
        setTransactions(bData.recent_transactions || []);
      }
      const allData = await allRes.json();
      setAllBalances(allData.balances || []);
    } catch (e) { console.error("Load balance failed:", e); }
    setLoading(false);
  }, [userId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (loading) return <div className="p-4 text-faint text-sm">Loading...</div>;

  return (
    <div className="p-4 space-y-4">
      {/* My balance */}
      {balance && (
        <div className="bg-gradient-to-br from-emerald-900/30 to-[var(--ds-card)] rounded-lg p-4 border border-emerald-700/30">
          <div className="text-muted text-xs mb-1">Your Balance</div>
          <div className="text-3xl font-bold text-emerald-400">{cents(balance.balance_cents)}</div>
          <div className="flex gap-4 mt-2 text-xs text-muted">
            <span>Earned: {cents(balance.lifetime_earned_cents)}</span>
            <span>Paid out: {cents(balance.lifetime_paid_out_cents)}</span>
          </div>
        </div>
      )}

      {/* All balances (parent view) */}
      {isParent && allBalances.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-muted uppercase mb-2">Family Balances</h3>
          <div className="space-y-1">
            {allBalances.map(b => (
              <div key={b.user_id} className="flex items-center gap-2 sm:gap-3 surface-card rounded px-3 py-2 border border-subtle">
                <span className="text-sm text-default font-medium flex-1 min-w-0 truncate">{b.user_id}</span>
                <span className="text-sm font-bold text-emerald-400 shrink-0">{cents(b.balance_cents)}</span>
                <span className="hidden sm:inline text-[10px] text-faint shrink-0">earned {cents(b.lifetime_earned_cents)}</span>
                <button onClick={() => setShowPay(showPay === b.user_id ? null : b.user_id)}
                  className="px-2 py-1 text-[10px] bg-indigo-600/50 text-indigo-300 rounded hover:bg-indigo-600 shrink-0"
                  title="Record payment">
                  <CreditCard size={11} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {showPay && <RecordPaymentForm userId={showPay} recordedBy={userId}
        onDone={() => { setShowPay(null); load(); }} onCancel={() => setShowPay(null)} />}

      {/* Recent transactions */}
      {transactions.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-muted uppercase mb-2">Recent Transactions</h3>
          <div className="space-y-1">
            {transactions.map(t => (
              <div key={t.id} className="flex items-center gap-2 text-xs px-3 py-1.5 surface-card rounded border border-subtle">
                <span className={`font-mono font-bold shrink-0 ${t.amount_cents >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {t.amount_cents >= 0 ? "+" : ""}{cents(t.amount_cents)}
                </span>
                <span className="text-muted flex-1 min-w-0 truncate">{t.note || t.type}</span>
                {t.payment_method && <span className="hidden sm:inline text-[10px] text-faint shrink-0">{t.payment_method}</span>}
                <span className="text-[10px] text-faint shrink-0">{new Date(t.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RecordPaymentForm({ userId: payeeId, recordedBy, onDone, onCancel }) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!amount) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API}/balances/${payeeId}/pay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount_cents: Math.round(parseFloat(amount) * 100),
          recorded_by: recordedBy || "",
          payment_method: method,
          note: note.trim(),
        }),
      });
      if (!res.ok) {
        const d = await res.json();
        setError(d.detail || "Payment failed");
        setSaving(false);
        return;
      }
      onDone();
    } catch (e) { setError("Network error"); }
    setSaving(false);
  }

  return (
    <form onSubmit={handleSubmit} className="surface-card rounded-lg p-3 space-y-2 border border-indigo-700/30">
      <div className="text-xs text-default font-medium">Record Payment to {payeeId}</div>
      {error && <div className="text-xs text-red-400">{error}</div>}
      <div className="flex flex-wrap gap-2">
        <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="$ amount"
          type="number" step="0.01" min="0.01"
          className="w-24 sm:w-28 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
        <select value={method} onChange={(e) => setMethod(e.target.value)}
          className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle">
          <option value="cash">Cash</option>
          <option value="venmo">Venmo</option>
          <option value="zelle">Zelle</option>
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note"
          className="flex-1 min-w-[8rem] surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted">Cancel</button>
        <button type="submit" disabled={saving || !amount}
          className="px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500 disabled:opacity-50">
          {saving ? "Recording..." : "Record Payment"}
        </button>
      </div>
    </form>
  );
}


// ==========================================================================
// Leaderboard Tab
// ==========================================================================

function LeaderboardTab({ refreshKey }) {
  const [leaders, setLeaders] = useState([]);
  const [period, setPeriod] = useState("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/leaderboard?period=${period}`);
      const data = await res.json();
      setLeaders(data.leaderboard || []);
    } catch (e) { console.error("Load leaderboard:", e); }
    setLoading(false);
  }, [period]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const medals = ["🥇", "🥈", "🥉"];
  const podiumStyles = [
    "bg-yellow-900/30 border-yellow-500/60 shadow-yellow-900/20 shadow-md",
    "surface-raised border-subtle shadow-slate-800/20 shadow-sm",
    "bg-amber-900/20 border-amber-700/50",
  ];
  const valueStyles = ["text-yellow-300", "text-default", "text-amber-400"];

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        {["all", "month", "week"].map(p => (
          <button key={p} onClick={() => setPeriod(p)}
            className={`px-3 py-1 text-xs rounded-full ${
              period === p ? "bg-indigo-600 text-on-accent" : "surface-card text-muted hover:text-[var(--ds-text)]"
            }`}>{p === "all" ? "All Time" : p === "month" ? "This Month" : "This Week"}</button>
        ))}
      </div>
      {loading ? (
        <div className="text-faint text-sm">Loading...</div>
      ) : leaders.length === 0 ? (
        <div className="text-faint text-sm">No completions yet.</div>
      ) : (
        <div className="space-y-2">
          {leaders.map((entry, i) => (
            <div key={entry.user_id}
              className={`flex items-center gap-3 rounded-lg px-4 py-3 border ${
                i < 3
                  ? podiumStyles[i]
                  : "surface-card border-subtle"
              }`}>
              <span className={`w-8 text-center ${i < 3 ? "text-2xl" : "text-sm text-faint"}`}>
                {medals[i] || `${i + 1}.`}
              </span>
              <span className={`text-sm font-medium flex-1 ${i < 3 ? "text-default" : "text-default"}`}>
                {entry.user_id}
              </span>
              <div className="text-right">
                <div className={`text-sm font-bold ${i < 3 ? valueStyles[i] : "text-emerald-400"}`}>
                  {cents(entry.total_earned_cents)}
                </div>
                <div className="text-[10px] text-faint">{entry.bounties_completed} bounties</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ==========================================================================
// Templates Tab
// ==========================================================================

function TemplatesTab({ userId, userRole, refreshKey }) {
  const [templates, setTemplates] = useState([]);
  const [categories, setCategories] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, cRes] = await Promise.all([
        fetch(`${API}/templates?active_only=false`),
        fetch(`${API}/categories`),
      ]);
      const tData = await tRes.json();
      const cData = await cRes.json();
      setTemplates(tData.templates || []);
      setCategories(cData.categories || []);
    } catch (e) { console.error("Load templates:", e); }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (!isParent) {
    return <div className="p-4 text-faint text-sm">Only parents can manage bounty templates.</div>;
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold text-muted uppercase flex-1">Bounty Templates (Recurring)</h3>
        <button onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500">
          <Plus size={13} /> New Template
        </button>
      </div>

      {showCreate && <CreateTemplateForm categories={categories} userId={userId}
        onCreated={() => { setShowCreate(false); load(); }} onCancel={() => setShowCreate(false)} />}

      {loading ? (
        <div className="text-faint text-sm">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="text-faint text-sm">No templates yet.</div>
      ) : (
        <div className="space-y-2">
          {templates.map(t => (
            <TemplateCard key={t.id} template={t} categories={categories} userId={userId} onRefresh={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function CreateTemplateForm({ categories, userId, onCreated, onCancel }) {
  const [form, setForm] = useState({ title: "", value: "", category: "", description: "", recurrence_days: "7" });
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title.trim() || !form.value) return;
    setSaving(true);
    try {
      await fetch(`${API}/templates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: form.title.trim(),
          value_cents: Math.round(parseFloat(form.value) * 100),
          created_by: userId || "",
          category: form.category,
          description: form.description.trim(),
          recurrence_days: parseInt(form.recurrence_days) || 7,
        }),
      });
      onCreated();
    } catch (e) { console.error("Create template failed:", e); }
    setSaving(false);
  }

  return (
    <form onSubmit={handleSubmit} className="surface-card rounded-lg p-3 space-y-2 border border-subtle">
      <div className="flex gap-2">
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Template title" className="flex-1 min-w-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
        <input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })}
          placeholder="$ value" type="number" step="0.01" min="0.01"
          className="w-20 sm:w-24 shrink-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex flex-wrap gap-2">
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
          className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle max-w-full">
          <option value="">No category</option>
          {categories.map(c => <option key={c.id} value={c.name}>{c.icon} {c.name}</option>)}
        </select>
        <select value={form.recurrence_days} onChange={(e) => setForm({ ...form, recurrence_days: e.target.value })}
          className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle">
          <option value="1">Daily</option>
          <option value="7">Weekly</option>
          <option value="14">Biweekly</option>
          <option value="30">Monthly</option>
        </select>
        <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Description (optional)" className="flex-1 min-w-[10rem] surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} className="px-3 py-1.5 text-xs text-muted">Cancel</button>
        <button type="submit" disabled={saving || !form.title.trim() || !form.value}
          className="px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500 disabled:opacity-50">
          {saving ? "Creating..." : "Create Template"}
        </button>
      </div>
    </form>
  );
}

function TemplateCard({ template: t, categories = [], userId, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    title: t.title, value: (t.value_cents / 100).toFixed(2),
    category: t.category, description: t.description,
    recurrence_days: String(t.recurrence_days),
  });
  const [saving, setSaving] = useState(false);

  const interval = { 1: "Daily", 7: "Weekly", 14: "Biweekly", 30: "Monthly" }[t.recurrence_days] || `Every ${t.recurrence_days}d`;

  async function handleGenerate() {
    setBusy(true);
    const params = new URLSearchParams({ acted_by: userId || "" });
    await fetch(`${API}/templates/${t.id}/generate?${params}`, { method: "POST" });
    onRefresh();
    setBusy(false);
  }

  async function handleToggle() {
    setBusy(true);
    await fetch(`${API}/templates/${t.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updated_by: userId || "", is_active: !t.is_active }),
    });
    onRefresh();
    setBusy(false);
  }

  async function handleDelete() {
    if (!confirm(`Delete template "${t.title}"?`)) return;
    const params = new URLSearchParams({ acted_by: userId || "" });
    await fetch(`${API}/templates/${t.id}?${params}`, { method: "DELETE" });
    onRefresh();
  }

  async function handleSave(e) {
    e.preventDefault();
    if (!form.title.trim() || !form.value) return;
    setSaving(true);
    await fetch(`${API}/templates/${t.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        updated_by: userId || "",
        title: form.title.trim(),
        value_cents: Math.round(parseFloat(form.value) * 100),
        category: form.category,
        description: form.description.trim(),
        recurrence_days: parseInt(form.recurrence_days) || 7,
      }),
    });
    setEditing(false);
    onRefresh();
    setSaving(false);
  }

  if (editing) {
    return (
      <form onSubmit={handleSave} className="surface-card rounded-lg p-3 space-y-2 border border-indigo-700/30">
        <div className="flex gap-2">
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Template title" className="flex-1 min-w-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
          <input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })}
            placeholder="$ value" type="number" step="0.01" min="0.01"
            className="w-20 sm:w-24 shrink-0 surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
        </div>
        <div className="flex flex-wrap gap-2">
          <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
            className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle max-w-full">
            <option value="">No category</option>
            {categories.map(c => <option key={c.id} value={c.name}>{c.icon} {c.name}</option>)}
          </select>
          <select value={form.recurrence_days} onChange={(e) => setForm({ ...form, recurrence_days: e.target.value })}
            className="surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle">
            <option value="1">Daily</option>
            <option value="7">Weekly</option>
            <option value="14">Biweekly</option>
            <option value="30">Monthly</option>
          </select>
          <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Description (optional)" className="flex-1 min-w-[10rem] surface-panel text-sm text-default px-2 py-1.5 rounded border border-subtle" />
        </div>
        <div className="flex flex-wrap gap-2 justify-end text-[10px]">
          <span className="text-faint flex-1 self-center min-w-[8rem]">Changes propagate to open bounties</span>
          <button type="button" onClick={() => setEditing(false)} className="px-3 py-1.5 text-muted">Cancel</button>
          <button type="submit" disabled={saving || !form.title.trim() || !form.value}
            className="px-3 py-1.5 bg-indigo-600 text-on-accent rounded-md hover:bg-indigo-500 disabled:opacity-50">
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 sm:gap-3 px-3 py-2.5 rounded-lg border ${
      t.is_active ? "surface-card border-subtle" : "surface-panel border-subtle opacity-60"
    }`}>
      <div className="flex-1 min-w-[10rem] cursor-pointer" onClick={() => setEditing(true)} title="Click to edit">
        <div className="text-sm text-default font-medium break-words">{t.title}</div>
        <div className="text-[10px] text-faint">
          {interval} • {t.category || "no category"} • {t.is_active ? "Active" : "Paused"}
        </div>
      </div>
      <span className="text-sm font-bold text-emerald-400 shrink-0">{cents(t.value_cents)}</span>
      <div className="flex items-center gap-1.5 shrink-0">
        <button onClick={handleGenerate} disabled={busy || !t.is_active} title="Generate bounty now"
          className="px-2 py-1 text-[10px] bg-green-600/50 text-green-300 rounded hover:bg-green-600 disabled:opacity-50">
          <Plus size={11} />
        </button>
        <button onClick={handleToggle} disabled={busy}
          className="px-2 py-1 text-[10px] surface-raised text-default rounded hover:bg-[var(--ds-raised)]">
          {t.is_active ? "Pause" : "Resume"}
        </button>
        <button onClick={handleDelete}
          className="px-2 py-1 text-[10px] bg-red-900/50 text-red-400 rounded hover:bg-red-900"
          title="Delete template">
          <X size={11} />
        </button>
      </div>
    </div>
  );
}


// ==========================================================================
// Settings Tab
// ==========================================================================

function SettingsTab({ userId, userRole, refreshKey }) {
  const [config, setConfig] = useState(null);
  const [categories, setCategories] = useState([]);
  const [newCat, setNewCat] = useState("");
  const [minPayout, setMinPayout] = useState("");
  const [saving, setSaving] = useState(false);
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);

  const load = useCallback(async () => {
    try {
      const [cfgRes, catRes] = await Promise.all([
        fetch(`${API}/config`),
        fetch(`${API}/categories`),
      ]);
      const cfg = await cfgRes.json();
      const cats = await catRes.json();
      setConfig(cfg);
      setMinPayout((cfg.min_payout_cents / 100).toFixed(2));
      setCategories(cats.categories || []);
    } catch (e) { console.error("Load settings:", e); }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (!isParent) {
    return <div className="p-4 text-faint text-sm">Only parents can change bounty settings.</div>;
  }

  async function saveMinPayout() {
    setSaving(true);
    await fetch(`${API}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        updated_by: userId || "",
        min_payout_cents: Math.round(parseFloat(minPayout) * 100),
      }),
    });
    await load();
    setSaving(false);
  }

  async function addCategory() {
    if (!newCat.trim()) return;
    await fetch(`${API}/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newCat.trim(), created_by: userId || "" }),
    });
    setNewCat("");
    load();
  }

  async function deleteCategory(catId, name) {
    if (!confirm(`Delete category "${name}"?`)) return;
    const params = new URLSearchParams({ acted_by: userId || "" });
    await fetch(`${API}/categories/${catId}?${params}`, { method: "DELETE" });
    load();
  }

  return (
    <div className="p-4 space-y-6 max-w-lg">
      <div>
        <h3 className="text-xs font-semibold text-muted uppercase mb-2">Minimum Payout Amount</h3>
        <div className="flex items-center gap-2">
          <span className="text-muted text-sm">$</span>
          <input value={minPayout} onChange={(e) => setMinPayout(e.target.value)}
            type="number" step="0.01" min="0"
            className="w-28 surface-card text-sm text-default px-2 py-1.5 rounded border border-subtle" />
          <button onClick={saveMinPayout} disabled={saving}
            className="px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded hover:bg-indigo-500 disabled:opacity-50">
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
        <p className="text-[10px] text-faint mt-1">Balance must meet this threshold before a payment can be recorded.</p>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-muted uppercase mb-2">Categories</h3>
        <div className="space-y-1 mb-2">
          {categories.map(c => (
            <div key={c.id} className="flex items-center gap-2 text-sm text-default surface-card rounded px-3 py-1.5 border border-subtle">
              <span>{c.icon}</span>
              <span className="flex-1">{c.name}</span>
              <button onClick={() => deleteCategory(c.id, c.name)}
                className="text-red-400 hover:text-red-300"><X size={12} /></button>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="New category name"
            className="flex-1 surface-card text-sm text-default px-2 py-1.5 rounded border border-subtle"
            onKeyDown={(e) => e.key === "Enter" && addCategory()} />
          <button onClick={addCategory} disabled={!newCat.trim()}
            className="px-3 py-1.5 text-xs bg-indigo-600 text-on-accent rounded hover:bg-indigo-500 disabled:opacity-50">
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
