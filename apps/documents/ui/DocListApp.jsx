import { useState, useEffect, useCallback } from "react";
import {
  FileText, Loader2, Plus, Search, RefreshCw, Tag, Link, X, ChevronRight,
} from "lucide-react";

/**
 * Document List app — singleton app for browsing/searching/creating documents.
 *
 * Clicking a document opens it as a new multi-instance DocumentEditor tab
 * via onOpenApp("document", { docId, title }).
 */

const API_BASE = "";

export default function DocListApp({ userId, onTitle, onOpenApp, refreshKey }) {
  const [docs, setDocs] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { onTitle?.("Documents"); }, []);

  const loadList = useCallback(async (query) => {
    setLoading(true);
    setError(null);
    try {
      const q = query ?? searchQuery;
      const url = q
        ? `${API_BASE}/api/apps/documents/search?q=${encodeURIComponent(q)}`
        : `${API_BASE}/api/apps/documents`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setDocs(data.documents || data.results || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [searchQuery]);

  // Initial load
  useEffect(() => { loadList(); }, []);

  // Auto-refresh when chat mutates document data
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadList();
  }, [refreshKey]);

  function handleOpen(docId, title) {
    onOpenApp?.("document", { docId, title: title || "Document" });
  }

  async function handleCreate(title) {
    if (!title.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/apps/documents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim(), created_by: userId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const doc = await res.json();
      // Open the new doc in its own editor tab
      handleOpen(doc.id, doc.title || title.trim());
      // Refresh the list
      loadList();
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1.5 text-sm text-slate-300">
          <FileText size={14} className="text-slate-500" />
          <span className="text-slate-200">Documents</span>
        </div>
        <button
          onClick={() => loadList()}
          disabled={loading}
          className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="px-3 py-1.5 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-white"><X size={12} /></button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading && !docs ? (
          <div className="flex items-center justify-center h-32 text-slate-400">
            <Loader2 size={20} className="animate-spin mr-2" /> Loading...
          </div>
        ) : (
          <DocList
            docs={docs}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onSearch={() => loadList()}
            onOpen={handleOpen}
            onCreate={handleCreate}
            loading={loading}
          />
        )}
      </div>
    </div>
  );
}

/* ── Document List View ── */

function DocList({ docs, searchQuery, onSearchChange, onSearch, onOpen, onCreate, loading }) {
  const [newTitle, setNewTitle] = useState("");

  return (
    <div className="p-4 space-y-3">
      {/* Search bar */}
      <div className="flex items-center gap-2">
        <div className="flex-1 flex items-center bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-1.5">
          <Search size={14} className="text-slate-500 shrink-0 mr-2" />
          <input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onSearch(); }}
            placeholder="Search documents..."
            className="bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none w-full"
          />
          {searchQuery && (
            <button onClick={() => onSearchChange("")} className="text-slate-500 hover:text-white ml-1">
              <X size={12} />
            </button>
          )}
        </div>
        <button onClick={onSearch} disabled={loading} className="p-2 rounded bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700 transition-colors">
          <Search size={14} />
        </button>
      </div>

      {/* New document */}
      <form onSubmit={(e) => { e.preventDefault(); if (newTitle.trim()) { onCreate(newTitle); setNewTitle(""); } }} className="flex items-center gap-2">
        <div className="flex-1 flex items-center bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-1.5">
          <Plus size={14} className="text-slate-500 shrink-0 mr-2" />
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="New document title..."
            className="bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none w-full"
          />
        </div>
        <button type="submit" disabled={!newTitle.trim()} className="px-3 py-1.5 rounded bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-500 disabled:opacity-30 disabled:cursor-default transition-colors">
          Create
        </button>
      </form>

      {/* Document list */}
      {(!docs || docs.length === 0) ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-500">
          <FileText size={32} className="text-slate-600 mb-2" />
          <p className="text-sm">{searchQuery ? "No matching documents" : "No documents yet"}</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {docs.map((d) => (
            <button
              key={d.id}
              onClick={() => onOpen(d.id, d.title || d.id)}
              className="w-full text-left px-4 py-3 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-200 truncate">{d.title || d.id}</span>
                <ChevronRight size={14} className="text-slate-600 shrink-0" />
              </div>
              <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                <span>{d.word_count || 0} words</span>
                {d.updated_at && <span>{d.updated_at.slice(0, 10)}</span>}
                {d.created_by && <span>by {d.created_by}</span>}
                {d.tags && d.tags.length > 0 && (
                  <span className="flex items-center gap-1">
                    <Tag size={10} />
                    {d.tags.join(", ")}
                  </span>
                )}
              </div>
              {d.related_entity_id && (
                <div className="mt-1 text-xs text-indigo-400/70 flex items-center gap-1">
                  <Link size={10} /> {d.related_entity_id}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
