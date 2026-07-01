import { useState, useEffect, useCallback } from "react";
import {
  Search, Plus, FolderOpen, Loader2, X, Folder, FileText, Paperclip, User,
} from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

export default function FoldersApp({ appId, userId, context = {}, refreshKey, isActive, onOpenApp }) {
  const [folders, setFolders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showNew, setShowNew] = useState(false);

  const fetchFolders = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery) {
        params.set("q", searchQuery);
        const res = await fetch(`/api/apps/folders/search?${params}`);
        if (res.ok) {
          const data = await res.json();
          setFolders(data.folders || []);
        }
      } else {
        params.set("root_only", "true");
        const res = await fetch(`/api/apps/folders?${params}`);
        if (res.ok) {
          const data = await res.json();
          setFolders(data.folders || []);
        }
      }
    } catch {} finally {
      setLoading(false);
    }
  }, [searchQuery]);

  useEffect(() => { fetchFolders(); }, [fetchFolders, refreshKey]);

  function openFolder(folder) {
    onOpenApp?.("folder", { folderId: folder.id, title: folder.name });
  }

  async function handleCreate(name, description, owner, tags) {
    try {
      const res = await fetch("/api/apps/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, owner, tags }),
      });
      if (res.ok) {
        const folder = await res.json();
        setShowNew(false);
        fetchFolders();
        openFolder(folder);
      } else if (res.status === 409) {
        const data = await res.json();
        alert(data.error || "A folder with that name already exists.");
      }
    } catch {}
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <FolderOpen size={14} className="text-blue-400 shrink-0" />
        <span className="text-sm font-medium text-default">Folders</span>
        <div className="flex-1" />
        <div className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search folders..."
            className="surface-card text-xs text-default pl-7 pr-2 py-1 rounded border border-subtle outline-none w-44 focus:border-blue-600"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]">
              <X size={10} />
            </button>
          )}
        </div>
        <button
          onClick={() => setShowNew(!showNew)}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-blue-600/80 hover:bg-blue-500 text-on-accent transition-colors"
        >
          <Plus size={12} />
          New Folder
        </button>
      </div>

      {/* New Folder Form */}
      {showNew && (
        <NewFolderForm onSubmit={handleCreate} onCancel={() => setShowNew(false)} />
      )}

      {/* Folder list */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-faint">
            <Loader2 size={16} className="animate-spin mr-2" /> Loading folders...
          </div>
        ) : folders.length === 0 ? (
          <PristineEmpty
            appId="folders"
            blurb={getAppManifest("folders")?.blurb}
            records={folders}
            loading={loading}
            filterActive={!!searchQuery}
            fallback={
              <div className="text-center py-8 text-faint text-sm">
                No folders match your search.
              </div>
            }
          />
        ) : (
          [...folders].sort((a, b) => a.name.localeCompare(b.name)).map((folder) => (
            <FolderCard key={folder.id} folder={folder} onClick={() => openFolder(folder)} />
          ))
        )}
      </div>
    </div>
  );
}


function FolderCard({ folder, onClick }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left p-3 rounded-lg surface-card hover:bg-[var(--ds-card)] border border-subtle hover:border-blue-700/30 transition-all group"
    >
      <div className="flex items-start gap-2.5">
        <Folder size={18} className="text-blue-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-sm font-medium text-default group-hover:text-[var(--ds-text)] truncate">
              {folder.name}
            </span>
          </div>
          {folder.description && (
            <p className="text-xs text-faint line-clamp-1 mb-1">{folder.description}</p>
          )}
          <div className="flex items-center gap-3 text-[10px] text-faint">
            <span className="flex items-center gap-1">
              <FileText size={10} />
              {folder.item_count || 0} items
            </span>
            {(folder.subfolder_count || 0) > 0 && (
              <span className="flex items-center gap-1">
                <Folder size={10} />
                {folder.subfolder_count} subfolders
              </span>
            )}
            {folder.owner && (
              <span className="flex items-center gap-1">
                <User size={10} />
                {folder.owner}
              </span>
            )}
            {folder.tags?.length > 0 && (
              <span className="flex items-center gap-1">
                {folder.tags.slice(0, 3).map((t) => (
                  <span key={t} className="px-1 py-0 surface-raised rounded text-faint">{t}</span>
                ))}
              </span>
            )}
            <span className="ml-auto">{fmtRelative(folder.updated_at)}</span>
          </div>
        </div>
      </div>
    </button>
  );
}


function NewFolderForm({ onSubmit, onCancel }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) return;
    onSubmit(name.trim(), description.trim(), owner.trim().toLowerCase(), []);
  }

  return (
    <form onSubmit={handleSubmit} className="px-3 py-2 bg-blue-950/20 border-b border-blue-900/30 space-y-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Folder name..."
        className="w-full surface-card text-sm text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-blue-600"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)..."
        className="w-full surface-card text-xs text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-blue-600"
      />
      <div className="flex items-center gap-2">
        <input
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          placeholder="Owner (empty = shared)"
          className="surface-card text-xs text-default px-2 py-1 rounded border border-subtle outline-none w-40 focus:border-blue-600"
        />
        <div className="flex-1" />
        <button type="button" onClick={onCancel} className="px-3 py-1 rounded text-xs text-muted hover:text-[var(--ds-text)] transition-colors">
          Cancel
        </button>
        <button
          type="submit"
          disabled={!name.trim()}
          className="px-3 py-1 rounded text-xs bg-blue-600 text-on-accent hover:bg-blue-500 disabled:opacity-30 transition-colors"
        >
          Create
        </button>
      </div>
    </form>
  );
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
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  } catch { return ""; }
}
