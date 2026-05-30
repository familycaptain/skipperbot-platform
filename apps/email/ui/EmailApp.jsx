import { useState, useEffect, useCallback } from "react";
import {
  Mail, Plus, Trash2, RefreshCw, Loader2, CheckCircle, XCircle,
  ChevronDown, ChevronUp, PenLine, GripVertical, ToggleLeft, ToggleRight,
  Tag, Archive, MailOpen, X, Link2, ArrowRight, Filter,
} from "lucide-react";

const TABS = ["Activity", "Rules", "Labels", "Accounts"];

export default function EmailApp({ appId, userId, isActive }) {
  const [tab, setTab] = useState("Activity");
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [ruleTemplate, setRuleTemplate] = useState(null);

  const refresh = useCallback(() => setRefreshKey(k => k + 1), []);

  useEffect(() => {
    if (accounts.length === 0) setLoading(true);
    fetch(`/api/apps/email/accounts?user=${userId}`)
      .then(r => r.json())
      .then(d => { setAccounts(d.accounts || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [userId, refreshKey]);

  // Auto-switch to Rules or Activity once accounts exist
  useEffect(() => {
    if (accounts.length > 0 && tab === "Accounts") {
      // stay on Accounts if user navigated there
    }
  }, [accounts]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500">
        <Loader2 size={20} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-900 text-white">
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-4 pt-3 pb-2 border-b border-slate-800">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === t ? "bg-slate-700 text-white" : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
            }`}>
            {t}
            {t === "Accounts" && <span className="ml-1 text-[10px] text-slate-600">({accounts.length})</span>}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {tab === "Accounts" && (
          <AccountsTab accounts={accounts} userId={userId} onRefresh={refresh} />
        )}
        {tab === "Rules" && (
          <RulesTab accounts={accounts} userId={userId} onRefresh={refresh}
            ruleTemplate={ruleTemplate} onTemplateClear={() => setRuleTemplate(null)} />
        )}
        {tab === "Activity" && (
          <ActivityTab accounts={accounts} userId={userId}
            onCreateRule={(template) => { setRuleTemplate(template); setTab("Rules"); }} />
        )}
        {tab === "Labels" && (
          <LabelsTab accounts={accounts} userId={userId} />
        )}
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   Accounts Tab
   ═══════════════════════════════════════════════════════════════════════════ */

function AccountsTab({ accounts, userId, onRefresh }) {
  const [connecting, setConnecting] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [confirmDel, setConfirmDel] = useState(null);

  async function handleConnect() {
    setConnecting(true);
    try {
      const dn = displayName.trim() || "";
      const r = await fetch(`/api/apps/email/oauth/start?user=${userId}&display_name=${encodeURIComponent(dn)}`);
      const d = await r.json();
      if (d.url) {
        window.open(d.url, "_blank", "width=600,height=700");
        setDisplayName("");
        // Poll for new account appearing (stops once count changes)
        const startCount = accounts.length;
        const poll = setInterval(async () => {
          const r2 = await fetch(`/api/apps/email/accounts?user=${userId}`);
          const d2 = await r2.json();
          if ((d2.accounts || []).length !== startCount) {
            clearInterval(poll);
            onRefresh();
          }
        }, 3000);
        setTimeout(() => clearInterval(poll), 90000);
      }
    } catch (e) {
      console.error("OAuth start failed:", e);
    }
    setConnecting(false);
  }

  async function handleDelete(accountId) {
    await fetch(`/api/apps/email/accounts/${accountId}`, { method: "DELETE" });
    setConfirmDel(null);
    onRefresh();
  }

  async function handleToggle(account) {
    await fetch(`/api/apps/email/accounts/${account.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: !account.active }),
    });
    onRefresh();
  }

  return (
    <div className="space-y-4 max-w-xl">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-400">Connected Gmail Accounts</h3>
      </div>

      {accounts.length === 0 ? (
        <div className="text-center py-12">
          <Mail size={40} className="mx-auto text-slate-700 mb-3" />
          <p className="text-slate-500 text-sm mb-1">No Gmail accounts connected yet.</p>
          <p className="text-slate-600 text-xs mb-4">Connect your Gmail to start setting up email rules.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {accounts.map(a => (
            <div key={a.id} className="bg-slate-800/40 border border-slate-700/30 rounded-lg p-3 group">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Mail size={16} className={a.active ? "text-indigo-400" : "text-slate-600"} />
                  <div>
                    <div className="text-sm font-medium">{a.email_address}</div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-500">
                      {a.display_name && <span>{a.display_name}</span>}
                      {a.last_synced_at && (
                        <span>Last synced: {new Date(a.last_synced_at).toLocaleString()}</span>
                      )}
                      {!a.last_synced_at && <span>Never synced</span>}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleToggle(a)} title={a.active ? "Disable" : "Enable"}
                    className="text-slate-500 hover:text-white">
                    {a.active ? <ToggleRight size={18} className="text-emerald-400" /> : <ToggleLeft size={18} />}
                  </button>
                  {confirmDel === a.id ? (
                    <div className="flex items-center gap-1">
                      <button onClick={() => handleDelete(a.id)} className="px-1.5 py-0.5 text-[10px] bg-red-600 hover:bg-red-500 text-white rounded">Yes</button>
                      <button onClick={() => setConfirmDel(null)} className="px-1.5 py-0.5 text-[10px] bg-slate-700 text-white rounded">No</button>
                    </div>
                  ) : (
                    <button onClick={() => setConfirmDel(a.id)}
                      className="opacity-0 group-hover:opacity-100 text-slate-600 hover:text-red-400">
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Connect form */}
      <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3 space-y-2">
        <div className="text-xs text-slate-500 uppercase tracking-wider font-medium">Connect Gmail Account</div>
        <div className="flex items-center gap-2">
          <input
            value={displayName}
            onChange={e => setDisplayName(e.target.value)}
            placeholder="Display name (e.g. Personal, Work)"
            className="flex-1 bg-slate-800 text-white text-xs px-3 py-2 rounded border border-slate-700 outline-none focus:border-indigo-500"
          />
          <button onClick={handleConnect} disabled={connecting}
            className="flex items-center gap-1.5 px-4 py-2 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded font-medium">
            {connecting ? <Loader2 size={12} className="animate-spin" /> : <Link2 size={12} />}
            Connect Gmail
          </button>
        </div>
        <p className="text-[10px] text-slate-600">
          Opens Google sign-in in a new tab. You'll be asked to grant SkipperBot access to read and modify your Gmail labels.
        </p>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   Rules Tab
   ═══════════════════════════════════════════════════════════════════════════ */

function RulesTab({ accounts, userId, onRefresh, ruleTemplate, onTemplateClear }) {
  const [selectedAccount, setSelectedAccount] = useState("");
  const [rules, setRules] = useState([]);
  const [loadingRules, setLoadingRules] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [refreshRules, setRefreshRules] = useState(0);

  // Auto-select first account
  useEffect(() => {
    if (accounts.length > 0 && !selectedAccount) {
      setSelectedAccount(accounts[0].id);
    }
  }, [accounts]);

  // When a template arrives from Activity tab, open the form
  useEffect(() => {
    if (ruleTemplate) {
      if (ruleTemplate.account_id) setSelectedAccount(ruleTemplate.account_id);
      setShowAdd(true);
      setEditingId(null);
    }
  }, [ruleTemplate]);

  // Load rules when account changes
  useEffect(() => {
    if (!selectedAccount) return;
    setLoadingRules(true);
    fetch(`/api/apps/email/rules?account_id=${selectedAccount}`)
      .then(r => r.json())
      .then(d => { setRules(d.rules || []); setLoadingRules(false); })
      .catch(() => setLoadingRules(false));
  }, [selectedAccount, refreshRules]);

  const refreshR = () => setRefreshRules(k => k + 1);

  if (accounts.length === 0) {
    return <p className="text-sm text-slate-600 italic">Connect a Gmail account first on the Accounts tab.</p>;
  }

  return (
    <div className="space-y-3 max-w-2xl">
      {/* Account selector */}
      {accounts.length > 1 && (
        <select value={selectedAccount} onChange={e => setSelectedAccount(e.target.value)}
          className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none">
          {accounts.map(a => <option key={a.id} value={a.id}>{a.email_address}</option>)}
        </select>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-xs text-slate-500 uppercase tracking-wider">
          Rules ({rules.length})
          {accounts.length === 1 && <span className="ml-2 normal-case text-slate-600">for {accounts[0].email_address}</span>}
        </h3>
        <button onClick={() => { setShowAdd(!showAdd); setEditingId(null); }}
          className="flex items-center gap-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded">
          <Plus size={12} /> Add Rule
        </button>
      </div>

      {showAdd && (
        <RuleForm accountId={selectedAccount} template={ruleTemplate}
          onSave={() => { setShowAdd(false); onTemplateClear(); refreshR(); }}
          onCancel={() => { setShowAdd(false); onTemplateClear(); }} />
      )}

      {loadingRules ? (
        <div className="text-slate-500 text-sm flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading rules...</div>
      ) : rules.length === 0 ? (
        <p className="text-sm text-slate-600 italic">No rules yet. Add one to start auto-processing your inbox.</p>
      ) : (
        <div className="space-y-2">
          {rules.map((rule, i) => (
            <RuleCard key={rule.id} rule={rule} isEditing={editingId === rule.id}
              onEdit={() => setEditingId(editingId === rule.id ? null : rule.id)}
              onRefresh={refreshR} />
          ))}
        </div>
      )}
    </div>
  );
}


function RuleForm({ accountId, rule, template, onSave, onCancel }) {
  const isEdit = !!rule;
  const effectiveAccountId = isEdit ? rule.account_id : accountId;
  const tpl = template || {};

  // Derive a suggested rule name from template
  const suggestName = () => {
    if (rule?.name) return rule.name;
    if (tpl.sender) {
      // Extract domain or display name
      const match = tpl.sender.match(/@([\w.-]+)/);
      if (match) return match[1].replace(/\.\w+$/, "");
      return tpl.sender.split("<")[0].trim().slice(0, 30);
    }
    return "";
  };

  const [name, setName] = useState(suggestName());
  const [fromContains, setFromContains] = useState(rule?.conditions?.from_contains || tpl.from_contains || "");
  const [subjectContains, setSubjectContains] = useState(rule?.conditions?.subject_contains || tpl.subject_contains || "");
  const [bodyContains, setBodyContains] = useState(rule?.conditions?.body_contains || tpl.body_contains || "");
  const [hasLabel, setHasLabel] = useState(rule?.conditions?.has_label || "");
  const [isUnread, setIsUnread] = useState(rule?.conditions?.is_unread || false);
  const [markRead, setMarkRead] = useState(rule?.actions?.mark_read || false);
  const [archive, setArchive] = useState(rule?.actions?.archive || false);
  const [saving, setSaving] = useState(false);
  const [availableLabels, setAvailableLabels] = useState([]);
  const [labelsLoading, setLabelsLoading] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Quick-move: "Move from INBOX to [label]"
  const existingAdd = rule?.actions?.add_labels || [];
  const existingRem = rule?.actions?.remove_labels || [];
  const hasQuickMove = existingAdd.length === 1 && existingRem.length === 1 && existingRem[0] === "INBOX";
  const [quickMoveTarget, setQuickMoveTarget] = useState(hasQuickMove ? existingAdd[0] : "");

  // Advanced pickers (only used when showAdvanced is true)
  const [addLabels, setAddLabels] = useState(new Set(hasQuickMove ? [] : existingAdd));
  const [removeLabels, setRemoveLabels] = useState(new Set(hasQuickMove ? [] : existingRem));

  useEffect(() => {
    if (!effectiveAccountId) return;
    setLabelsLoading(true);
    fetch(`/api/apps/email/labels?account_id=${effectiveAccountId}`)
      .then(r => r.json())
      .then(d => { setAvailableLabels(d.labels || []); setLabelsLoading(false); })
      .catch(() => setLabelsLoading(false));
  }, [effectiveAccountId]);

  // If editing a rule with advanced label config (not simple quick-move), show advanced
  useEffect(() => {
    if (isEdit && !hasQuickMove && (existingAdd.length > 0 || existingRem.length > 0)) {
      setShowAdvanced(true);
    }
  }, []);

  function toggleLabel(set, setFn, labelName) {
    const next = new Set(set);
    if (next.has(labelName)) next.delete(labelName);
    else next.add(labelName);
    setFn(next);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);

    const conditions = {};
    if (fromContains.trim()) conditions.from_contains = fromContains.trim();
    if (subjectContains.trim()) conditions.subject_contains = subjectContains.trim();
    if (bodyContains.trim()) conditions.body_contains = bodyContains.trim();
    if (hasLabel) conditions.has_label = hasLabel;
    if (isUnread) conditions.is_unread = true;

    const actions = {};

    // Build labels from quick-move or advanced pickers
    if (showAdvanced) {
      const al = [...addLabels];
      const rl = [...removeLabels];
      if (al.length) actions.add_labels = al;
      if (rl.length) actions.remove_labels = rl;
    } else if (quickMoveTarget) {
      actions.add_labels = [quickMoveTarget];
      actions.remove_labels = ["INBOX"];
    }
    if (markRead) actions.mark_read = true;
    if (archive) actions.archive = true;

    if (isEdit) {
      await fetch(`/api/apps/email/rules/${rule.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), conditions, actions }),
      });
    } else {
      await fetch("/api/apps/email/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId, name: name.trim(), conditions, actions }),
      });
    }
    setSaving(false);
    onSave();
  }

  const sortedLabels = [...availableLabels].sort((a, b) => {
    if (a.type !== b.type) return a.type === "user" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  // Labels suitable for quick-move target (exclude system inbox/spam/trash)
  const moveTargets = sortedLabels.filter(l =>
    !["INBOX", "SPAM", "TRASH", "SENT", "DRAFT", "UNREAD", "STARRED", "IMPORTANT"].includes(l.name)
  );

  return (
    <form onSubmit={handleSubmit} className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-3 space-y-3">
      <div className="text-[10px] text-indigo-400 uppercase tracking-wider font-medium">
        {isEdit ? "Edit Rule" : tpl.sender ? `New Rule from "${tpl.sender.split("<")[0].trim()}"` : "New Rule"}
      </div>

      <input value={name} onChange={e => setName(e.target.value)} placeholder="Rule name *"
        className="w-full bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500" />

      <div className="text-[10px] text-slate-500 uppercase tracking-wider">Conditions (match all non-empty)</div>
      <div className="grid grid-cols-3 gap-2">
        <input value={fromContains} onChange={e => setFromContains(e.target.value)} placeholder="From contains..."
          className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500" />
        <input value={subjectContains} onChange={e => setSubjectContains(e.target.value)} placeholder="Subject contains..."
          className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500" />
        <input value={bodyContains} onChange={e => setBodyContains(e.target.value)} placeholder="Body contains..."
          className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500" />
      </div>
      <div className="flex items-center gap-3">
        {labelsLoading ? (
          <Loader2 size={12} className="animate-spin text-slate-500" />
        ) : (
          <select value={hasLabel} onChange={e => setHasLabel(e.target.value)}
            className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500">
            <option value="">In any label</option>
            {sortedLabels.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={isUnread} onChange={e => setIsUnread(e.target.checked)}
            className="rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500" />
          Only unread
        </label>
      </div>

      <div className="text-[10px] text-slate-500 uppercase tracking-wider">Actions</div>

      {/* Quick move: Inbox → Label */}
      {!showAdvanced && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 shrink-0">Move from</span>
          <span className="text-xs text-white bg-slate-700 px-2 py-1 rounded">INBOX</span>
          <ArrowRight size={12} className="text-slate-600 shrink-0" />
          {labelsLoading ? (
            <Loader2 size={12} className="animate-spin text-slate-500" />
          ) : (
            <select value={quickMoveTarget} onChange={e => setQuickMoveTarget(e.target.value)}
              className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500 flex-1">
              <option value="">-- Select label --</option>
              {moveTargets.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
            </select>
          )}
        </div>
      )}

      {/* Advanced label pickers */}
      {showAdvanced && !labelsLoading && (
        <div className="grid grid-cols-2 gap-3">
          <LabelPicker title="Add labels" labels={sortedLabels} selected={addLabels}
            onToggle={n => toggleLabel(addLabels, setAddLabels, n)} accent="emerald" />
          <LabelPicker title="Remove labels" labels={sortedLabels} selected={removeLabels}
            onToggle={n => toggleLabel(removeLabels, setRemoveLabels, n)} accent="red" />
        </div>
      )}
      {showAdvanced && labelsLoading && (
        <div className="text-slate-500 text-xs flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Loading labels...</div>
      )}

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={markRead} onChange={e => setMarkRead(e.target.checked)}
            className="rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500" />
          Mark as read
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={archive} onChange={e => setArchive(e.target.checked)}
            className="rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500" />
          Archive
        </label>
        <button type="button" onClick={() => { setShowAdvanced(!showAdvanced); if (!showAdvanced) setQuickMoveTarget(""); }}
          className="text-[10px] text-indigo-400 hover:text-indigo-300 ml-auto">
          {showAdvanced ? "Simple mode" : "Advanced labels"}
        </button>
      </div>

      <div className="flex justify-end gap-1">
        <button type="button" onClick={onCancel} className="px-2 py-1 text-xs text-slate-400">Cancel</button>
        <button type="submit" disabled={saving || !name.trim()}
          className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded">
          {saving ? "Saving..." : isEdit ? "Save Changes" : "Create Rule"}
        </button>
      </div>
    </form>
  );
}


function LabelPicker({ title, labels, selected, onToggle, accent }) {
  const [expanded, setExpanded] = useState(false);
  const accentColor = accent === "emerald" ? "text-emerald-400" : "text-red-400";
  const accentBg = accent === "emerald" ? "bg-emerald-500" : "bg-red-500";
  const count = selected.size;
  const visible = expanded ? labels : labels.slice(0, 6);

  return (
    <div className="bg-slate-800/50 border border-slate-700/40 rounded p-2 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className={`text-[10px] uppercase tracking-wider font-medium ${accentColor}`}>
          {title} {count > 0 && `(${count})`}
        </span>
      </div>
      <div className="space-y-0.5 max-h-40 overflow-y-auto">
        {visible.map(label => (
          <label key={label.id} className="flex items-center gap-1.5 py-0.5 cursor-pointer hover:bg-slate-700/30 px-1 rounded text-xs">
            <input
              type="checkbox"
              checked={selected.has(label.name)}
              onChange={() => onToggle(label.name)}
              className={`rounded border-slate-600 bg-slate-800 ${accent === "emerald" ? "text-emerald-500 focus:ring-emerald-500" : "text-red-500 focus:ring-red-500"}`}
            />
            <span className={`truncate ${selected.has(label.name) ? "text-white" : "text-slate-400"}`}>{label.name}</span>
            {label.type === "system" && <span className="text-[8px] text-slate-600 shrink-0">sys</span>}
          </label>
        ))}
      </div>
      {labels.length > 6 && (
        <button type="button" onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-slate-500 hover:text-slate-300 w-full text-center">
          {expanded ? "Show less" : `Show all ${labels.length} labels`}
        </button>
      )}
    </div>
  );
}


function RuleCard({ rule, isEditing, onEdit, onRefresh }) {
  const [confirmDel, setConfirmDel] = useState(false);

  async function handleDelete() {
    await fetch(`/api/apps/email/rules/${rule.id}`, { method: "DELETE" });
    setConfirmDel(false);
    onRefresh();
  }

  async function handleToggle() {
    await fetch(`/api/apps/email/rules/${rule.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: !rule.active }),
    });
    onRefresh();
  }

  const conds = rule.conditions || {};
  const acts = rule.actions || {};
  const condParts = [];
  if (conds.from_contains) condParts.push(`from: "${conds.from_contains}"`);
  if (conds.subject_contains) condParts.push(`subj: "${conds.subject_contains}"`);
  if (conds.body_contains) condParts.push(`body: "${conds.body_contains}"`);

  const actParts = [];
  if (acts.add_labels?.length) actParts.push(`+${acts.add_labels.join(", +")}`);
  if (acts.remove_labels?.length) actParts.push(`-${acts.remove_labels.join(", -")}`);
  if (acts.mark_read) actParts.push("read");
  if (acts.archive) actParts.push("archive");

  return (
    <div className={`bg-slate-800/30 border rounded-lg group ${rule.active ? "border-slate-700/30" : "border-slate-700/20 opacity-60"}`}>
      <div className="flex items-center justify-between p-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Tag size={13} className="text-indigo-400 shrink-0" />
            <span className="text-sm font-medium">{rule.name}</span>
            <span className="text-[10px] text-slate-600">{rule.match_count}× matched</span>
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
            <span>IF {condParts.join(" AND ") || "—"}</span>
            <span className="text-slate-600">→</span>
            <span className="text-emerald-500/70">{actParts.join(", ") || "—"}</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button onClick={onEdit}
            className={`px-2 py-1 text-xs rounded ${isEditing ? "bg-indigo-700 text-white" : "text-slate-500 hover:text-indigo-400 hover:bg-slate-700 opacity-0 group-hover:opacity-100"}`}>
            <PenLine size={12} />
          </button>
          <button onClick={handleToggle} title={rule.active ? "Disable" : "Enable"}
            className="text-slate-500 hover:text-white opacity-0 group-hover:opacity-100">
            {rule.active ? <ToggleRight size={16} className="text-emerald-400" /> : <ToggleLeft size={16} />}
          </button>
          {confirmDel ? (
            <div className="flex items-center gap-0.5">
              <button onClick={handleDelete} className="px-1.5 py-0.5 text-[10px] bg-red-600 hover:bg-red-500 text-white rounded">Yes</button>
              <button onClick={() => setConfirmDel(false)} className="px-1.5 py-0.5 text-[10px] bg-slate-700 text-white rounded">No</button>
            </div>
          ) : (
            <button onClick={() => setConfirmDel(true)}
              className="text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100">
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {isEditing && (
        <div className="border-t border-slate-700/50 p-3">
          <RuleForm rule={rule} onSave={() => { onEdit(); onRefresh(); }} onCancel={onEdit} />
        </div>
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   Labels Tab
   ═══════════════════════════════════════════════════════════════════════════ */

function LabelsTab({ accounts, userId }) {
  const [selectedAccount, setSelectedAccount] = useState("");
  const [labels, setLabels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all"); // all, user, system

  useEffect(() => {
    if (accounts.length > 0 && !selectedAccount) {
      setSelectedAccount(accounts[0].id);
    }
  }, [accounts]);

  useEffect(() => {
    if (!selectedAccount) return;
    setLoading(true);
    fetch(`/api/apps/email/labels?account_id=${selectedAccount}`)
      .then(r => r.json())
      .then(d => { setLabels(d.labels || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedAccount]);

  if (accounts.length === 0) {
    return <p className="text-sm text-slate-600 italic">Connect a Gmail account first on the Accounts tab.</p>;
  }

  const filtered = labels.filter(l => {
    if (filter === "user") return l.type === "user";
    if (filter === "system") return l.type === "system";
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    // User labels first, then system
    if (a.type !== b.type) return a.type === "user" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="space-y-3 max-w-2xl">
      {accounts.length > 1 && (
        <select value={selectedAccount} onChange={e => setSelectedAccount(e.target.value)}
          className="bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none">
          {accounts.map(a => <option key={a.id} value={a.id}>{a.email_address}</option>)}
        </select>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-xs text-slate-500 uppercase tracking-wider">
          Labels ({filtered.length})
          {accounts.length === 1 && <span className="ml-2 normal-case text-slate-600">for {accounts[0].email_address}</span>}
        </h3>
        <div className="flex items-center gap-1">
          {["all", "user", "system"].map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-2 py-1 text-[10px] rounded ${filter === f ? "bg-slate-700 text-white" : "text-slate-500 hover:text-slate-300"}`}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-slate-500 text-sm flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading labels...</div>
      ) : sorted.length === 0 ? (
        <p className="text-sm text-slate-600 italic">No labels found.</p>
      ) : (
        <div className="space-y-1">
          {sorted.map(label => (
            <div key={label.id} className="flex items-center justify-between px-3 py-2 rounded hover:bg-slate-800/30 group">
              <div className="flex items-center gap-2 min-w-0">
                <Tag size={13} className={label.type === "user" ? "text-indigo-400" : "text-slate-600"} />
                <span className="text-sm truncate">{label.name}</span>
                {label.type === "system" && (
                  <span className="text-[9px] text-slate-600 bg-slate-800 px-1.5 py-0.5 rounded">system</span>
                )}
              </div>
              <div className="flex items-center gap-4 text-[11px] text-slate-500 shrink-0">
                {label.messages_unread > 0 && (
                  <span className="text-amber-400 font-medium">{label.messages_unread} unread</span>
                )}
                <span>{label.messages_total} msg{label.messages_total !== 1 ? "s" : ""}</span>
                <span className="text-slate-600">{label.threads_total} thread{label.threads_total !== 1 ? "s" : ""}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   Activity Tab
   ═══════════════════════════════════════════════════════════════════════════ */

function ActivityTab({ accounts, userId, onCreateRule }) {
  const [log, setLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(null);
  const [showUnhandledOnly, setShowUnhandledOnly] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchLog = useCallback(async (showSpinner) => {
    if (showSpinner) setRefreshing(true);
    else setLoading(true);
    try {
      const r = await fetch(`/api/apps/email/log?user=${userId}&limit=100`);
      const d = await r.json();
      setLog(d.log || []);
    } catch (_) {}
    setLoading(false);
    setRefreshing(false);
  }, [userId]);

  useEffect(() => { fetchLog(false); }, [fetchLog]);

  async function handleSync(accountId) {
    setSyncing(accountId);
    try {
      const r = await fetch(`/api/apps/email/sync?account_id=${accountId}`, { method: "POST" });
      const d = await r.json();
      if (d.ok) {
        await fetchLog(false);
      }
    } catch (e) {
      console.error("Sync failed:", e);
    }
    setSyncing(null);
  }

  if (accounts.length === 0) {
    return <p className="text-sm text-slate-600 italic">Connect a Gmail account first on the Accounts tab.</p>;
  }

  if (loading) {
    return <div className="text-slate-500 text-sm flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading activity...</div>;
  }

  const filtered = showUnhandledOnly ? log.filter(e => !e.rule_id) : log;

  // Group by date
  const grouped = {};
  for (const entry of filtered) {
    const date = entry.received_at ? entry.received_at.slice(0, 10) : "Unknown";
    if (!grouped[date]) grouped[date] = [];
    grouped[date].push(entry);
  }
  const dates = Object.keys(grouped).sort().reverse();
  const unhandledCount = log.filter(e => !e.rule_id).length;

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-xs text-slate-500 uppercase tracking-wider">
            {showUnhandledOnly ? `Unhandled (${unhandledCount})` : `Processed Emails (${log.length})`}
          </h3>
          <button onClick={() => setShowUnhandledOnly(!showUnhandledOnly)}
            className={`flex items-center gap-1 px-2 py-1 text-[10px] rounded transition-colors ${
              showUnhandledOnly
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                : "text-slate-500 hover:text-slate-300 hover:bg-slate-800 border border-slate-700/30"
            }`}
            title="Show only emails with no rule match">
            <Filter size={10} />
            {showUnhandledOnly ? "Showing unhandled" : "No rule"}
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => fetchLog(true)} disabled={refreshing}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-400 rounded"
            title="Refresh log">
            {refreshing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
            Refresh
          </button>
          {accounts.map(a => (
            <button key={a.id} onClick={() => handleSync(a.id)} disabled={syncing === a.id}
              className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-400 rounded"
              title={`Sync ${a.email_address}`}>
              {syncing === a.id ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
              Sync {a.display_name || a.email_address.split("@")[0]}
            </button>
          ))}
        </div>
      </div>

      {log.length === 0 ? (
        <div className="text-center py-8">
          <MailOpen size={32} className="mx-auto text-slate-700 mb-2" />
          <p className="text-sm text-slate-600">No emails processed yet.</p>
          <p className="text-xs text-slate-700">Hit Sync to process your inbox, or wait for the scheduled job.</p>
        </div>
      ) : (
        dates.map(date => (
          <div key={date}>
            <div className="text-[10px] text-slate-600 uppercase tracking-wider mb-1 sticky top-0 bg-slate-900 py-1">
              {date}
              <span className="ml-2 text-slate-700">({grouped[date].length})</span>
            </div>
            <div className="space-y-1">
              {grouped[date].map(entry => (
                <LogEntry key={entry.id} entry={entry} onCreateRule={onCreateRule} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}


function LogEntry({ entry, onCreateRule }) {
  const [expanded, setExpanded] = useState(false);
  const acts = entry.actions_taken || [];
  const hasActions = acts.length > 0;

  const actSummary = acts.map(a => {
    if (a.action === "add_labels") return `+${(a.labels || []).join(", +")}`;
    if (a.action === "remove_labels") return `-${(a.labels || []).join(", -")}`;
    if (a.action === "mark_read") return "read";
    if (a.action === "archive") return "archive";
    return a.action;
  }).join(", ");

  return (
    <div>
      <div
        className={`flex items-center gap-3 px-2 py-1.5 rounded hover:bg-slate-800/30 group text-xs ${!hasActions ? "cursor-pointer" : ""}`}
        onClick={() => { if (!hasActions) setExpanded(!expanded); }}
        title={!hasActions ? "Click to expand and create a rule" : undefined}
      >
        {hasActions ? (
          <CheckCircle size={12} className="text-emerald-500/60 shrink-0" />
        ) : (
          <Mail size={12} className="text-slate-600 shrink-0" />
        )}
        <span className="text-slate-400 w-32 truncate shrink-0" title={entry.sender}>{entry.sender}</span>
        <span className="text-slate-300 flex-1 truncate">{entry.subject}</span>
        {entry.rule_name && (
          <span className="text-[10px] text-indigo-400/70 shrink-0">{entry.rule_name}</span>
        )}
        {actSummary && (
          <span className="text-[10px] text-emerald-500/60 shrink-0">{actSummary}</span>
        )}
        {!hasActions && (
          expanded
            ? <ChevronUp size={12} className="text-indigo-400 shrink-0" />
            : <Plus size={12} className="text-slate-700 group-hover:text-indigo-400 shrink-0 transition-colors" />
        )}
      </div>
      {expanded && !hasActions && (
        <EmailPreview entry={entry} onCreateRule={(tpl) => { setExpanded(false); onCreateRule(tpl); }} />
      )}
    </div>
  );
}


function EmailPreview({ entry, onCreateRule }) {
  const [body, setBody] = useState(null);
  const [loadingBody, setLoadingBody] = useState(true);
  const [selections, setSelections] = useState({ from_contains: "", subject_contains: "", body_contains: "" });

  const fromRef = useCallback(node => { if (node) node.dataset.field = "from_contains"; }, []);
  const subjectRef = useCallback(node => { if (node) node.dataset.field = "subject_contains"; }, []);
  const bodyRef = useCallback(node => { if (node) node.dataset.field = "body_contains"; }, []);

  useEffect(() => {
    if (!entry.account_id || !entry.gmail_msg_id) { setLoadingBody(false); return; }
    setLoadingBody(true);
    fetch(`/api/apps/email/message?account_id=${entry.account_id}&gmail_msg_id=${entry.gmail_msg_id}`)
      .then(r => r.json())
      .then(d => { setBody(d.body || ""); setLoadingBody(false); })
      .catch(() => { setBody(""); setLoadingBody(false); });
  }, [entry.account_id, entry.gmail_msg_id]);

  function handleMouseUp() {
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text) return;

    // Walk up from the selection anchor to find which field container it's in
    let node = sel.anchorNode;
    let field = null;
    while (node && node !== document.body) {
      if (node.dataset?.field) { field = node.dataset.field; break; }
      node = node.parentElement || node.parentNode;
    }
    if (!field) return;

    setSelections(prev => ({ ...prev, [field]: text }));
    sel.removeAllRanges();
  }

  function clearSelection(field) {
    setSelections(prev => ({ ...prev, [field]: "" }));
  }

  function handleCreateRule() {
    const tpl = {
      sender: entry.sender || "",
      from_contains: selections.from_contains,
      subject_contains: selections.subject_contains,
      body_contains: selections.body_contains,
      account_id: entry.account_id,
    };
    onCreateRule(tpl);
  }

  const hasAnySelection = selections.from_contains || selections.subject_contains || selections.body_contains;

  return (
    <div className="ml-6 mr-2 mb-2 mt-1 bg-slate-800/60 border border-slate-700/50 rounded-lg p-3 space-y-3 text-xs"
         onMouseUp={handleMouseUp}>

      <div className="text-[10px] text-indigo-400 uppercase tracking-wider font-medium flex items-center gap-2">
        <PenLine size={10} />
        Highlight text to build rule conditions
      </div>

      {/* From field */}
      <div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">From</div>
        <div ref={fromRef} data-field="from_contains"
          className="text-slate-300 bg-slate-900/50 px-2 py-1.5 rounded select-text cursor-text break-all">
          {entry.sender || "(unknown)"}
        </div>
        {selections.from_contains && (
          <SelectionChip label="From" value={selections.from_contains} onClear={() => clearSelection("from_contains")} />
        )}
      </div>

      {/* Subject field */}
      <div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Subject</div>
        <div ref={subjectRef} data-field="subject_contains"
          className="text-slate-300 bg-slate-900/50 px-2 py-1.5 rounded select-text cursor-text">
          {entry.subject || "(no subject)"}
        </div>
        {selections.subject_contains && (
          <SelectionChip label="Subject" value={selections.subject_contains} onClear={() => clearSelection("subject_contains")} />
        )}
      </div>

      {/* Body field */}
      <div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Body</div>
        {loadingBody ? (
          <div className="text-slate-500 flex items-center gap-1 py-2">
            <Loader2 size={12} className="animate-spin" /> Loading body...
          </div>
        ) : (
          <div ref={bodyRef} data-field="body_contains"
            className="text-slate-400 bg-slate-900/50 px-2 py-1.5 rounded select-text cursor-text max-h-48 overflow-y-auto whitespace-pre-wrap text-[11px] leading-relaxed">
            {body || "(empty body)"}
          </div>
        )}
        {selections.body_contains && (
          <SelectionChip label="Body" value={selections.body_contains} onClear={() => clearSelection("body_contains")} />
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-1 border-t border-slate-700/30">
        <div className="text-[10px] text-slate-600">
          {hasAnySelection
            ? "Selections captured — click Create Rule to continue"
            : "Select text above to set match conditions"}
        </div>
        <button
          onClick={handleCreateRule}
          disabled={!hasAnySelection}
          className="flex items-center gap-1 px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed text-white rounded transition-colors"
        >
          Create Rule <ArrowRight size={12} />
        </button>
      </div>
    </div>
  );
}


function SelectionChip({ label, value, onClear }) {
  return (
    <div className="flex items-center gap-1.5 mt-1 ml-1">
      <span className="text-[10px] text-indigo-400 font-medium">{label}:</span>
      <span className="text-[10px] bg-indigo-500/20 text-indigo-300 px-1.5 py-0.5 rounded max-w-xs truncate">
        "{value}"
      </span>
      <button onClick={onClear} className="text-slate-600 hover:text-red-400 transition-colors">
        <X size={10} />
      </button>
    </div>
  );
}
