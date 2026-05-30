import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search, Plus, List, RefreshCw, Loader2, X, Trash2,
  ChevronDown, ChevronRight, ChevronUp, ExternalLink, Tag, Printer, Pencil, Trello,
} from "lucide-react";
import TrelloSettings from "./TrelloSettings.jsx";

const PREVIEW_LIMIT = 4;

export default function ListsApp({ appId, userId, context = {}, refreshKey, isActive }) {
  const [lists, setLists] = useState([]);
  const [boards, setBoards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSource, setActiveSource] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [showTrelloSettings, setShowTrelloSettings] = useState(false);

  // ── Fetch ──
  const loadLists = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery.trim()) params.set("q", searchQuery.trim());
      else if (activeSource) params.set("source", activeSource);
      const res = await fetch(`/api/apps/lists?${params}`);
      if (res.ok) {
        const data = await res.json();
        setLists(data.lists || []);
        if (data.boards) setBoards(data.boards);
      }
    } catch {}
    setLoading(false);
  }, [searchQuery, activeSource]);

  useEffect(() => { loadLists(); }, [loadLists]);

  // Auto-refresh from chat mutations
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadLists();
  }, [refreshKey]);

  // Reload when tab becomes active
  const wasActive = useRef(isActive);
  useEffect(() => {
    if (isActive && !wasActive.current) loadLists();
    wasActive.current = isActive;
  }, [isActive]);

  // ── Group lists by source ──
  function groupedLists() {
    const standalone = [];
    const byBoard = {};
    for (const lst of lists) {
      if (lst.trello) {
        const board = lst.trello.board || "unknown";
        if (!byBoard[board]) byBoard[board] = [];
        byBoard[board].push(lst);
      } else {
        standalone.push(lst);
      }
    }
    const groups = [];
    if (standalone.length > 0) {
      groups.push({ key: "standalone", label: "Standalone", trello: false, lists: standalone });
    }
    for (const board of Object.keys(byBoard).sort()) {
      groups.push({ key: board, label: board.charAt(0).toUpperCase() + board.slice(1), trello: true, lists: byBoard[board] });
    }
    return groups;
  }

  // ── Handlers ──
  function toggleExpand(listId) {
    setExpandedId(expandedId === listId ? null : listId);
  }

  // ── Trello settings view ──
  if (showTrelloSettings) {
    return (
      <TrelloSettings
        onBack={() => { setShowTrelloSettings(false); loadLists(); }}
      />
    );
  }

  return (
    <div className="flex flex-col h-full w-full text-sm text-gray-200 overflow-hidden">
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <List size={16} className="text-sky-400 shrink-0" />
          <div className="relative flex-1 max-w-xs">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search lists & items..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setActiveSource(""); }}
              className="w-full bg-slate-800/60 text-sm text-white pl-7 pr-2 py-1 rounded border border-slate-700 outline-none focus:border-sky-500"
            />
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowTrelloSettings(true)}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-400 hover:text-sky-400 transition-colors"
            title="Trello settings"
          >
            <Trello size={13} />
          </button>
          <button
            onClick={loadLists}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
            title="Refresh"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setShowNewForm(f => !f)}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-sky-600 hover:bg-sky-500 text-white rounded transition-colors"
          >
            <Plus size={12} /> New
          </button>
        </div>
      </div>

      {/* ── Source filter bubbles ── */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-900/20 border-b border-slate-800/50 overflow-x-auto shrink-0">
        <button
          onClick={() => setActiveSource("")}
          className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
            !activeSource ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
          }`}
        >
          All
        </button>
        <button
          onClick={() => { setActiveSource("standalone"); setSearchQuery(""); }}
          className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors ${
            activeSource === "standalone" ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
          }`}
        >
          Standalone
        </button>
        {boards.map((b) => (
          <button
            key={b}
            onClick={() => { setActiveSource(b); setSearchQuery(""); }}
            className={`px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-colors flex items-center gap-1 ${
              activeSource === b ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            <ExternalLink size={9} className="opacity-60" />
            {b.charAt(0).toUpperCase() + b.slice(1)}
          </button>
        ))}
      </div>

      {/* ── New list form ── */}
      {showNewForm && (
        <NewListForm
          userId={userId}
          onCreated={() => { setShowNewForm(false); loadLists(); }}
          onCancel={() => setShowNewForm(false)}
        />
      )}

      {/* ── List content ── */}
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {loading && lists.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-400">
            <Loader2 size={18} className="animate-spin mr-2" /> Loading lists...
          </div>
        ) : lists.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500 text-sm">
            <List size={32} className="mb-2 opacity-40" />
            {searchQuery ? "No lists match your search." : "No lists yet. Create one or connect a Trello board via chat."}
          </div>
        ) : (
          groupedLists().map((group) => (
            <div key={group.key}>
              {/* Group header */}
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{group.label}</h3>
                <span className="text-[10px] text-slate-600">({group.lists.length} {group.lists.length === 1 ? "list" : "lists"})</span>
                {group.trello && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-700/30">
                    ↔ Trello
                  </span>
                )}
              </div>

              {/* List cards */}
              <div className="space-y-2">
                {group.lists.map((lst) => (
                  <ListCard
                    key={lst.id}
                    lst={lst}
                    expanded={expandedId === lst.id}
                    onToggle={() => toggleExpand(lst.id)}
                    userId={userId}
                    onRefresh={loadLists}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}


// ── List Card ──

function ListCard({ lst, expanded, onToggle, userId, onRefresh }) {
  const [addText, setAddText] = useState("");
  const [adding, setAdding] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [detail, setDetail] = useState(null);
  const inputRef = useRef(null);

  const previewItems = lst.items?.slice(0, PREVIEW_LIMIT) || [];
  const extraCount = (lst.item_count || 0) - PREVIEW_LIMIT;
  const isTrello = !!lst.trello;

  // Load full detail when expanded
  useEffect(() => {
    if (!expanded) { setDetail(null); return; }
    (async () => {
      try {
        const res = await fetch(`/api/apps/lists/${lst.id}`);
        if (res.ok) setDetail(await res.json());
      } catch {}
    })();
  }, [expanded, lst.id]);

  // Focus input when expanded
  useEffect(() => {
    if (expanded && inputRef.current) inputRef.current.focus();
  }, [expanded]);

  async function handleAddItem(e) {
    e.preventDefault();
    if (!addText.trim() || adding) return;
    setAdding(true);
    try {
      await fetch(`/api/apps/lists/${lst.id}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: addText.trim(), added_by: userId }),
      });
      setAddText("");
      onRefresh();
      // Reload detail
      const res = await fetch(`/api/apps/lists/${lst.id}`);
      if (res.ok) setDetail(await res.json());
    } catch {}
    setAdding(false);
  }

  async function handleRemoveItem(itemId) {
    try {
      await fetch(`/api/apps/lists/${lst.id}/items/${itemId}`, { method: "DELETE" });
      onRefresh();
      const res = await fetch(`/api/apps/lists/${lst.id}`);
      if (res.ok) setDetail(await res.json());
    } catch {}
  }

  async function handleEditItem(itemId, newText) {
    if (!newText.trim()) return;
    try {
      await fetch(`/api/apps/lists/${lst.id}/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: newText.trim() }),
      });
      onRefresh();
      const res = await fetch(`/api/apps/lists/${lst.id}`);
      if (res.ok) setDetail(await res.json());
    } catch {}
  }

  async function handleMoveItem(itemId, newPos) {
    try {
      await fetch(`/api/apps/lists/${lst.id}/items/${itemId}/position`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_position: newPos }),
      });
      const res = await fetch(`/api/apps/lists/${lst.id}`);
      if (res.ok) setDetail(await res.json());
      onRefresh();
    } catch {}
  }

  async function handleSync() {
    setSyncing(true);
    try {
      await fetch(`/api/apps/lists/${lst.id}/sync`, { method: "POST" });
      onRefresh();
      const res = await fetch(`/api/apps/lists/${lst.id}`);
      if (res.ok) setDetail(await res.json());
    } catch {}
    setSyncing(false);
  }

  async function handleDelete() {
    if (!confirm(`Delete list "${lst.name}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await fetch(`/api/apps/lists/${lst.id}`, { method: "DELETE" });
      onRefresh();
    } catch {}
    setDeleting(false);
  }

  const items = expanded && detail ? detail.items : previewItems;
  const archivedItems = detail?.archived_items || [];

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 transition-colors hover:border-slate-600/50">
      {/* ── Collapsed header ── */}
      <button
        onClick={onToggle}
        className="w-full text-left flex items-center gap-3 px-3 py-2.5 group"
      >
        <div className="shrink-0 text-slate-500 transition-transform" style={{ transform: expanded ? "rotate(90deg)" : "" }}>
          <ChevronRight size={14} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white truncate">{lst.name}</span>
            <span className="text-[10px] text-slate-500">{lst.item_count} {lst.item_count === 1 ? "item" : "items"}</span>
            {lst.aliases?.length > 0 && (
              <span className="text-[10px] text-slate-600 flex items-center gap-0.5">
                <Tag size={8} />
                {lst.aliases.join(", ")}
              </span>
            )}
          </div>
          {/* Inline preview when collapsed */}
          {!expanded && previewItems.length > 0 && (
            <div className="mt-1 text-xs text-slate-500 truncate">
              {previewItems.map(i => i.text).join(" · ")}
              {extraCount > 0 && <span className="text-slate-600"> +{extraCount} more</span>}
            </div>
          )}
        </div>
        {isTrello && (
          <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-sky-900/20 text-sky-500 border border-sky-800/30">
            {lst.trello.board}
          </span>
        )}
      </button>

      {/* ── Expanded detail ── */}
      {expanded && (
        <div className="border-t border-slate-700/30 px-3 pb-3">
          {/* Trello info line */}
          {isTrello && lst.trello && (
            <div className="text-[11px] text-slate-500 pt-2 pb-1">
              Trello: {lst.trello.board} / {lst.trello.list_name}
              {lst.trello.last_sync && (
                <span className="ml-2 text-slate-600">· synced {fmtRelative(lst.trello.last_sync)}</span>
              )}
            </div>
          )}

          {/* Add item form */}
          <form onSubmit={handleAddItem} className="flex items-center gap-1.5 mt-2 mb-2">
            <input
              ref={inputRef}
              type="text"
              value={addText}
              onChange={(e) => setAddText(e.target.value)}
              placeholder="Add item..."
              className="flex-1 bg-slate-800 text-white text-xs px-2.5 py-1.5 rounded border border-slate-700 outline-none focus:border-sky-500"
            />
            <button
              type="submit"
              disabled={adding || !addText.trim()}
              className="px-2.5 py-1.5 text-xs bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-white rounded transition-colors"
            >
              {adding ? <Loader2 size={12} className="animate-spin" /> : "Add"}
            </button>
          </form>

          {/* Item list */}
          {!detail ? (
            <div className="flex items-center justify-center py-4 text-slate-500">
              <Loader2 size={14} className="animate-spin mr-1.5" /> Loading...
            </div>
          ) : items.length === 0 ? (
            <p className="text-xs text-slate-600 italic py-2">Empty list</p>
          ) : (
            <div className="space-y-0.5">
              {items.map((item, idx) => (
                <ListItemRow
                  key={item.id}
                  item={item}
                  idx={idx}
                  total={items.length}
                  onEdit={handleEditItem}
                  onMove={handleMoveItem}
                  onRemove={handleRemoveItem}
                />
              ))}
            </div>
          )}

          {/* Archived items */}
          {archivedItems.length > 0 && (
            <div className="mt-2">
              <button
                onClick={() => setShowArchived(!showArchived)}
                className="flex items-center gap-1 text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
              >
                <ChevronDown size={10} className={`transition-transform ${showArchived ? "" : "-rotate-90"}`} />
                Archived ({archivedItems.length})
              </button>
              {showArchived && (
                <div className="mt-1 space-y-0.5 pl-5">
                  {archivedItems.map((item) => (
                    <div key={item.id} className="text-xs text-slate-600 line-through py-0.5">
                      {item.text}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Action bar */}
          <div className="flex items-center gap-2 mt-3 pt-2 border-t border-slate-700/30">
            {isTrello && (
              <button
                onClick={handleSync}
                disabled={syncing}
                className="flex items-center gap-1 px-2 py-1 text-[11px] rounded bg-slate-700/50 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
              >
                <RefreshCw size={10} className={syncing ? "animate-spin" : ""} />
                Sync
              </button>
            )}
            <button
              onClick={() => printList(lst.name, items)}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded bg-slate-700/50 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
              title="Print this list"
            >
              <Printer size={10} />
              Print
            </button>
            <div className="flex-1" />
            <span className="text-[10px] text-slate-600 font-mono">{lst.id}</span>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded hover:bg-red-900/30 text-slate-500 hover:text-red-400 transition-colors"
            >
              <Trash2 size={10} />
              Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


// ── Editable List Item Row ──

function ListItemRow({ item, idx, total, onEdit, onMove, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(item.text);
  const editRef = useRef(null);

  useEffect(() => {
    if (editing && editRef.current) {
      editRef.current.focus();
      editRef.current.select();
    }
  }, [editing]);

  function startEdit() {
    setEditText(item.text);
    setEditing(true);
  }

  function commitEdit() {
    const trimmed = editText.trim();
    if (trimmed && trimmed !== item.text) {
      onEdit(item.id, trimmed);
    }
    setEditing(false);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter") { e.preventDefault(); commitEdit(); }
    if (e.key === "Escape") { setEditing(false); setEditText(item.text); }
  }

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-700/30 group/item transition-colors">
      <span className="text-[10px] text-slate-600 w-5 text-right shrink-0">{idx + 1}.</span>
      {editing ? (
        <input
          ref={editRef}
          type="text"
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          className="flex-1 bg-slate-800 text-white text-xs px-2 py-1 rounded border border-sky-500 outline-none min-w-0"
        />
      ) : (
        <span
          className="flex-1 text-xs text-slate-200 min-w-0 cursor-pointer hover:text-white"
          onDoubleClick={startEdit}
          title="Double-click to edit"
        >
          {item.text}
        </span>
      )}
      {!editing && item.added_by && item.added_by !== "trello_sync" && (
        <span className="text-[10px] text-slate-600 shrink-0">{item.added_by}</span>
      )}
      {!editing && (
        <div className="flex items-center gap-0 opacity-0 group-hover/item:opacity-100 transition-all shrink-0">
          <button
            onClick={startEdit}
            className="p-0.5 rounded hover:bg-slate-600/50 text-slate-500 hover:text-white transition-colors"
            title="Edit"
          >
            <Pencil size={11} />
          </button>
          <button
            onClick={() => onMove(item.id, idx - 1)}
            disabled={idx === 0}
            className="p-0.5 rounded hover:bg-slate-600/50 text-slate-500 hover:text-white disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:text-slate-500 transition-colors"
            title="Move up"
          >
            <ChevronUp size={11} />
          </button>
          <button
            onClick={() => onMove(item.id, idx + 1)}
            disabled={idx === total - 1}
            className="p-0.5 rounded hover:bg-slate-600/50 text-slate-500 hover:text-white disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:text-slate-500 transition-colors"
            title="Move down"
          >
            <ChevronDown size={11} />
          </button>
        </div>
      )}
      {!editing && (
        <button
          onClick={() => onRemove(item.id)}
          className="p-0.5 rounded opacity-0 group-hover/item:opacity-100 hover:bg-red-900/30 text-slate-500 hover:text-red-400 transition-all shrink-0"
          title="Remove"
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}


// ── New List Form ──

function NewListForm({ userId, onCreated, onCancel }) {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const ref = useRef(null);
  useEffect(() => { ref.current?.focus(); }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    try {
      const res = await fetch("/api/apps/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), created_by: userId }),
      });
      if (res.ok) onCreated();
    } catch {}
    setCreating(false);
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 px-3 py-2 bg-slate-900/40 border-b border-slate-800">
      <input
        ref={ref}
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="New list name..."
        className="flex-1 bg-slate-800 text-white text-xs px-2.5 py-1.5 rounded border border-slate-700 outline-none focus:border-sky-500"
      />
      <button
        type="submit"
        disabled={creating || !name.trim()}
        className="px-3 py-1.5 text-xs bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-white rounded transition-colors"
      >
        {creating ? <Loader2 size={12} className="animate-spin" /> : "Create"}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="px-2 py-1.5 text-xs text-slate-400 hover:text-white rounded hover:bg-slate-700 transition-colors"
      >
        Cancel
      </button>
    </form>
  );
}


// ── Helpers ──

function printList(listName, items) {
  const now = new Date().toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
  const rows = (items || [])
    .map((item, i) => {
      const meta = item.added_by && item.added_by !== "trello_sync"
        ? `<span style="color:#999;font-size:12px;margin-left:8px;">(${item.added_by})</span>`
        : "";
      return `<tr>
        <td style="width:32px;text-align:right;color:#888;padding:6px 8px;vertical-align:top;">${i + 1}.</td>
        <td style="padding:6px 8px;">${item.text}${meta}</td>
      </tr>`;
    })
    .join("");

  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(`<!DOCTYPE html><html><head><title>${listName}</title>
    <style>
      body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:40px auto;padding:0 24px;color:#222;}
      h1{font-size:22px;margin-bottom:4px;}
      .date{color:#888;font-size:13px;margin-bottom:20px;}
      table{width:100%;border-collapse:collapse;}
      tr{border-bottom:1px solid #eee;}
      tr:last-child{border-bottom:none;}
      td{font-size:15px;}
      .count{color:#888;font-size:13px;margin-top:16px;}
      @media print{body{margin:20px;}}
    </style></head>
    <body>
      <h1>${listName}</h1>
      <div class="date">${now}</div>
      <table>${rows}</table>
      <div class="count">${items?.length || 0} item${(items?.length || 0) === 1 ? "" : "s"}</div>
    </body></html>`);
  win.document.close();
  win.print();
}

function fmtRelative(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    const now = new Date();
    const diffMs = now - d;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return isoStr.slice(0, 16);
  }
}
