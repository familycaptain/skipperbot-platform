import { useState, useEffect, useCallback } from "react";
import {
  Trello, ArrowLeft, Plus, Trash2, Loader2, Eye, EyeOff,
  Save, AlertCircle, Key, Link, RefreshCw, Check,
} from "lucide-react";

const BASE = "/api/apps/lists";

export default function TrelloSettings({ onBack }) {
  const [accounts, setAccounts] = useState([]);
  const [boards, setBoards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [accRes, boardRes] = await Promise.all([
        fetch(`${BASE}/trello/accounts`),
        fetch(`${BASE}/trello/boards`),
      ]);
      if (accRes.ok) {
        const data = await accRes.json();
        setAccounts(data.accounts || []);
      }
      if (boardRes.ok) {
        const data = await boardRes.json();
        setBoards(data.boards || []);
      }
    } catch {
      setError("Failed to load Trello settings.");
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="flex flex-col h-full w-full text-sm text-default overflow-hidden">
      {/* ── Header ── */}
      <div className="flex items-center gap-2 px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)] transition-colors"
          title="Back to lists"
        >
          <ArrowLeft size={13} /> Back to lists
        </button>
        <div className="flex items-center gap-2 flex-1 min-w-0 justify-center">
          <Trello size={15} className="text-accent shrink-0" />
          <span className="text-sm font-medium text-default">Trello Settings</span>
        </div>
        <button
          onClick={load}
          className="p-1.5 rounded hover:bg-[var(--ds-raised)] text-muted hover:text-[var(--ds-text)] transition-colors"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-y-auto p-3 space-y-6">
        {error && (
          <div className="flex items-center gap-2 text-xs text-red-400 bg-red-900/20 border border-red-800/40 rounded px-3 py-2">
            <AlertCircle size={13} /> {error}
          </div>
        )}

        {loading && accounts.length === 0 && boards.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-muted">
            <Loader2 size={18} className="animate-spin mr-2" /> Loading Trello settings...
          </div>
        ) : (
          <>
            <AccountsSection
              accounts={accounts}
              setAccounts={setAccounts}
            />
            <BoardsSection
              accounts={accounts}
              boards={boards}
              setBoards={setBoards}
            />
          </>
        )}
      </div>
    </div>
  );
}


// ── Accounts ──

function AccountsSection({ accounts, setAccounts }) {
  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <Key size={13} className="text-accent" />
        <h3 className="text-xs font-semibold text-default uppercase tracking-wider">Accounts</h3>
      </div>

      {accounts.length === 0 ? (
        <p className="text-xs text-faint italic mb-3">No Trello accounts yet — add one to connect boards.</p>
      ) : (
        <div className="space-y-2 mb-3">
          {accounts.map((acc) => (
            <AccountRow key={acc.name} acc={acc} setAccounts={setAccounts} />
          ))}
        </div>
      )}

      <AddAccountForm accounts={accounts} setAccounts={setAccounts} />
    </section>
  );
}

function AccountRow({ acc, setAccounts }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  async function handleDelete() {
    if (!confirm(`Delete Trello account "${acc.name}"? This also removes all boards using this account.`)) return;
    setDeleting(true);
    setError("");
    try {
      const res = await fetch(`${BASE}/trello/accounts/${encodeURIComponent(acc.name)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        const refreshed = await fetch(`${BASE}/trello/accounts`);
        if (refreshed.ok) setAccounts((await refreshed.json()).accounts || []);
      } else {
        setError(data.error || "Failed to delete account.");
      }
    } catch {
      setError("Failed to delete account.");
    }
    setDeleting(false);
  }

  return (
    <div className="rounded-lg border border-subtle surface-card px-3 py-2">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-default truncate flex-1 min-w-0">{acc.name}</span>
        <Flag label="key" set={acc.key_set} />
        <Flag label="token" set={acc.token_set} />
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="p-1 rounded hover:bg-red-900/30 text-faint hover:text-red-400 transition-colors"
          title="Delete account"
        >
          {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
        </button>
      </div>
      {error && (
        <div className="flex items-center gap-1.5 text-[11px] text-red-400 mt-1">
          <AlertCircle size={11} /> {error}
        </div>
      )}
    </div>
  );
}

function Flag({ label, set }) {
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded border flex items-center gap-0.5 ${
        set
          ? "bg-emerald-900/20 text-emerald-400 border-emerald-700/30"
          : "surface-raised text-faint border-subtle"
      }`}
    >
      {set ? <Check size={9} /> : null}
      {label} {set ? "set" : "not set"}
    </span>
  );
}

function AddAccountForm({ accounts, setAccounts }) {
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Detect existing account being edited (by matching name) to swap placeholders
  const existing = accounts.find(
    (a) => a.name.toLowerCase() === name.trim().toLowerCase()
  );
  const keySet = !!existing?.key_set;
  const tokenSet = !!existing?.token_set;

  function reset() {
    setName(""); setApiKey(""); setApiToken("");
    setShowKey(false); setShowToken(false);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${BASE}/trello/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          api_key: apiKey,
          api_token: apiToken,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        setAccounts(data.accounts || accounts);
        reset();
      } else {
        setError(data.error || "Failed to save account.");
      }
    } catch {
      setError("Failed to save account.");
    }
    setSaving(false);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-subtle surface-panel p-3 space-y-2"
    >
      <p className="text-[11px] text-muted font-medium">
        {existing ? `Edit "${existing.name}"` : "Add account"}
      </p>
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Account name (e.g. personal)"
        className="w-full surface-card text-default text-xs px-2.5 py-1.5 rounded border border-subtle outline-none focus:border-subtle"
      />
      <SecretInput
        value={apiKey}
        onChange={setApiKey}
        reveal={showKey}
        onToggleReveal={() => setShowKey((s) => !s)}
        placeholder={keySet ? "•••• saved — type to replace" : "API key"}
      />
      <SecretInput
        value={apiToken}
        onChange={setApiToken}
        reveal={showToken}
        onToggleReveal={() => setShowToken((s) => !s)}
        placeholder={tokenSet ? "•••• saved — type to replace" : "API token"}
      />
      {error && (
        <div className="flex items-center gap-1.5 text-[11px] text-red-400">
          <AlertCircle size={11} /> {error}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={saving || !name.trim()}
          className="flex items-center gap-1 px-3 py-1.5 text-xs bg-[var(--ds-accent)] hover:bg-[var(--ds-accent)] disabled:opacity-40 text-on-accent rounded transition-colors"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {existing ? "Save changes" : "Save"}
        </button>
        <span className="text-[10px] text-faint">
          Leave key/token blank to keep existing.
        </span>
      </div>
    </form>
  );
}

function SecretInput({ value, onChange, reveal, onToggleReveal, placeholder }) {
  return (
    <div className="relative">
      <input
        type={reveal ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full surface-card text-default text-xs pl-2.5 pr-8 py-1.5 rounded border border-subtle outline-none focus:border-subtle"
      />
      <button
        type="button"
        onClick={onToggleReveal}
        className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-faint hover:text-[var(--ds-text)] transition-colors"
        title={reveal ? "Hide" : "Reveal"}
        tabIndex={-1}
      >
        {reveal ? <EyeOff size={13} /> : <Eye size={13} />}
      </button>
    </div>
  );
}


// ── Boards ──

function BoardsSection({ accounts, boards, setBoards }) {
  const hasAccounts = accounts.length > 0;
  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <Link size={13} className="text-accent" />
        <h3 className="text-xs font-semibold text-default uppercase tracking-wider">Boards</h3>
      </div>

      {boards.length === 0 ? (
        <p className="text-xs text-faint italic mb-3">
          No Trello boards yet — {hasAccounts ? "add one below." : "add an account first."}
        </p>
      ) : (
        <div className="space-y-2 mb-3">
          {boards.map((b) => (
            <BoardRow key={b.name} board={b} accounts={accounts} setBoards={setBoards} />
          ))}
        </div>
      )}

      <AddBoardForm accounts={accounts} boards={boards} setBoards={setBoards} />
    </section>
  );
}

function BoardRow({ board, accounts, setBoards }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const accountMissing = !accounts.some((a) => a.name === board.account);

  async function handleDelete() {
    if (!confirm(`Delete board "${board.name}"?`)) return;
    setDeleting(true);
    setError("");
    try {
      const res = await fetch(`${BASE}/trello/boards/${encodeURIComponent(board.name)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        const refreshed = await fetch(`${BASE}/trello/boards`);
        if (refreshed.ok) setBoards((await refreshed.json()).boards || []);
      } else {
        setError(data.error || "Failed to delete board.");
      }
    } catch {
      setError("Failed to delete board.");
    }
    setDeleting(false);
  }

  return (
    <div className="rounded-lg border border-subtle surface-card px-3 py-2">
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-default truncate">{board.name}</span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                accountMissing
                  ? "bg-amber-900/20 text-amber-400 border-amber-700/30"
                  : "surface-card text-accent border-subtle"
              }`}
              title={accountMissing ? "Account not found" : "Account"}
            >
              {board.account || "—"}{accountMissing ? " (?)" : ""}
            </span>
          </div>
          <div className="text-[10px] text-faint mt-0.5 truncate">
            <span className="font-mono">{board.board_id}</span>
            {board.default_list ? <span> · default: {board.default_list}</span> : null}
          </div>
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="p-1 rounded hover:bg-red-900/30 text-faint hover:text-red-400 transition-colors"
          title="Delete board"
        >
          {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
        </button>
      </div>
      {error && (
        <div className="flex items-center gap-1.5 text-[11px] text-red-400 mt-1">
          <AlertCircle size={11} /> {error}
        </div>
      )}
    </div>
  );
}

function AddBoardForm({ accounts, boards, setBoards }) {
  const hasAccounts = accounts.length > 0;
  const [name, setName] = useState("");
  const [account, setAccount] = useState("");
  const [boardId, setBoardId] = useState("");
  const [defaultList, setDefaultList] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function reset() {
    setName(""); setAccount(""); setBoardId(""); setDefaultList("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim() || !account || !boardId.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${BASE}/trello/boards`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          account,
          board_id: boardId.trim(),
          default_list: defaultList.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok !== false) {
        setBoards(data.boards || boards);
        reset();
      } else {
        setError(data.error || "Failed to save board.");
      }
    } catch {
      setError("Failed to save board.");
    }
    setSaving(false);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-subtle surface-panel p-3 space-y-2"
    >
      <p className="text-[11px] text-muted font-medium">Add board</p>
      {!hasAccounts && (
        <div className="flex items-center gap-1.5 text-[11px] text-amber-400">
          <AlertCircle size={11} /> Add a Trello account before connecting boards.
        </div>
      )}
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Board name (e.g. household)"
        disabled={!hasAccounts}
        className="w-full surface-card text-default text-xs px-2.5 py-1.5 rounded border border-subtle outline-none focus:border-subtle disabled:opacity-40"
      />
      <select
        value={account}
        onChange={(e) => setAccount(e.target.value)}
        disabled={!hasAccounts}
        className="w-full surface-card text-default text-xs px-2.5 py-1.5 rounded border border-subtle outline-none focus:border-subtle disabled:opacity-40"
      >
        <option value="">{hasAccounts ? "Select account…" : "No accounts available"}</option>
        {accounts.map((a) => (
          <option key={a.name} value={a.name}>{a.name}</option>
        ))}
      </select>
      <input
        type="text"
        value={boardId}
        onChange={(e) => setBoardId(e.target.value)}
        placeholder="Board ID"
        disabled={!hasAccounts}
        className="w-full surface-card text-default text-xs px-2.5 py-1.5 rounded border border-subtle outline-none focus:border-subtle disabled:opacity-40 font-mono"
      />
      <p className="text-[10px] text-faint">
        Board ID is from the board URL: trello.com/b/<span className="text-muted">BOARD_ID</span>/...
      </p>
      <input
        type="text"
        value={defaultList}
        onChange={(e) => setDefaultList(e.target.value)}
        placeholder="Default list (optional)"
        disabled={!hasAccounts}
        className="w-full surface-card text-default text-xs px-2.5 py-1.5 rounded border border-subtle outline-none focus:border-subtle disabled:opacity-40"
      />
      {error && (
        <div className="flex items-center gap-1.5 text-[11px] text-red-400">
          <AlertCircle size={11} /> {error}
        </div>
      )}
      <button
        type="submit"
        disabled={saving || !hasAccounts || !name.trim() || !account || !boardId.trim()}
        className="flex items-center gap-1 px-3 py-1.5 text-xs bg-[var(--ds-accent)] hover:bg-[var(--ds-accent)] disabled:opacity-40 text-on-accent rounded transition-colors"
      >
        {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
        Save
      </button>
    </form>
  );
}
