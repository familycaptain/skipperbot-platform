import { useState, useEffect, useCallback } from "react";
import {
  FolderOpen, Folder, FileText, Paperclip, Loader2, Plus, Trash2, ArrowLeft,
  ChevronRight, Pencil, X, Check, FilePlus, Search,
} from "lucide-react";

export default function FolderDetailApp({ appId, userId, context = {}, refreshKey, isActive, onOpenApp, onTitle }) {
  const folderId = context?.folderId || "";
  const [folder, setFolder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAddDoc, setShowAddDoc] = useState(false);
  const [showNewDoc, setShowNewDoc] = useState(false);
  const [showNewSub, setShowNewSub] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");

  const fetchFolder = useCallback(async () => {
    if (!folderId) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/apps/folders/${folderId}`);
      if (res.ok) {
        const data = await res.json();
        setFolder(data);
        onTitle?.(data.name);
      }
    } catch {} finally {
      setLoading(false);
    }
  }, [folderId]);

  useEffect(() => { fetchFolder(); }, [fetchFolder, refreshKey]);

  async function handleRemoveItem(entityId) {
    try {
      await fetch(`/api/apps/folders/${folderId}/items/${entityId}`, { method: "DELETE" });
      fetchFolder();
    } catch {}
  }

  async function handleAddExistingDoc(entityId) {
    try {
      const res = await fetch(`/api/apps/folders/${folderId}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: entityId }),
      });
      if (res.ok) {
        setShowAddDoc(false);
        fetchFolder();
      }
    } catch {}
  }

  async function handleCreateDoc(title, content) {
    try {
      const res = await fetch(`/api/apps/folders/${folderId}/new-doc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, content, tags: [] }),
      });
      if (res.ok) {
        setShowNewDoc(false);
        fetchFolder();
        const data = await res.json();
        if (data.doc?.id) {
          onOpenApp?.("document", { docId: data.doc.id, title: data.doc.title });
        }
      }
    } catch {}
  }

  async function handleCreateSubfolder(name, description) {
    try {
      const res = await fetch("/api/apps/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, parent_folder_id: folderId }),
      });
      if (res.ok) {
        setShowNewSub(false);
        fetchFolder();
      } else if (res.status === 409) {
        const data = await res.json();
        alert(data.error || "A subfolder with that name already exists.");
      }
    } catch {}
  }

  async function handleSaveEdit() {
    try {
      const body = {};
      if (editName.trim()) body.name = editName.trim();
      if (editDesc !== undefined) body.description = editDesc.trim();
      await fetch(`/api/apps/folders/${folderId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setEditing(false);
      fetchFolder();
    } catch {}
  }

  async function handleDelete() {
    if (!confirm(`Delete folder "${folder?.name}"? Contents are preserved.`)) return;
    try {
      await fetch(`/api/apps/folders/${folderId}`, { method: "DELETE" });
      onOpenApp?.("folders");
    } catch {}
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-faint">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading folder...
      </div>
    );
  }

  if (!folder) {
    return (
      <div className="flex items-center justify-center h-full text-faint text-sm">
        Folder not found.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header */}
      <div className="px-3 py-2 surface-panel border-b border-subtle shrink-0">
        {/* Breadcrumbs */}
        {folder.breadcrumbs?.length > 1 && (
          <div className="flex items-center gap-1 text-[10px] text-faint mb-1">
            <button
              onClick={() => onOpenApp?.("folders")}
              className="hover:text-[var(--ds-muted)] transition-colors"
            >
              Folders
            </button>
            {folder.breadcrumbs.map((bc, i) => (
              <span key={bc.id} className="flex items-center gap-1">
                <ChevronRight size={8} />
                {i < folder.breadcrumbs.length - 1 ? (
                  <button
                    onClick={() => onOpenApp?.("folder", { folderId: bc.id, title: bc.name })}
                    className="hover:text-[var(--ds-muted)] transition-colors"
                  >
                    {bc.name}
                  </button>
                ) : (
                  <span className="text-muted">{bc.name}</span>
                )}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          <FolderOpen size={16} className="text-blue-400 shrink-0" />
          {editing ? (
            <div className="flex items-center gap-2 flex-1">
              <div className="flex flex-col gap-1 flex-1">
                <input
                  autoFocus
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Folder name"
                  className="surface-card text-sm text-default px-2 py-0.5 rounded border border-subtle outline-none focus:border-blue-600"
                />
                <input
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  placeholder="Description (optional)"
                  className="surface-card text-xs text-default px-2 py-0.5 rounded border border-subtle outline-none focus:border-blue-600"
                />
              </div>
              <button onClick={handleSaveEdit} className="text-green-400 hover:text-green-300 shrink-0">
                <Check size={14} />
              </button>
              <button onClick={() => setEditing(false)} className="text-faint hover:text-[var(--ds-text)] shrink-0">
                <X size={14} />
              </button>
            </div>
          ) : (
            <>
              <span className="text-sm font-medium text-default flex-1 truncate">{folder.name}</span>
              <button
                onClick={() => { setEditName(folder.name); setEditDesc(folder.description || ""); setEditing(true); }}
                className="text-faint hover:text-[var(--ds-text)] transition-colors"
              >
                <Pencil size={12} />
              </button>
              <button onClick={handleDelete} className="text-faint hover:text-red-400 transition-colors">
                <Trash2 size={12} />
              </button>
            </>
          )}
        </div>

        {folder.description && !editing && (
          <p className="text-xs text-faint mt-0.5 ml-6">{folder.description}</p>
        )}

        <div className="flex items-center gap-3 text-[10px] text-faint mt-1 ml-6">
          <span>{folder.item_count || 0} items</span>
          <span>{folder.subfolder_count || 0} subfolders</span>
          {folder.owner && <span>Owner: {folder.owner}</span>}
          <span className="text-default">{folder.id}</span>
        </div>
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-1 px-3 py-1.5 surface-panel border-b border-subtle shrink-0">
        <button
          onClick={() => { setShowAddDoc(!showAddDoc); setShowNewDoc(false); setShowNewSub(false); }}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] surface-raised hover:bg-[var(--ds-raised)] text-default transition-colors"
        >
          <Plus size={10} /> Add Document
        </button>
        <button
          onClick={() => { setShowNewDoc(!showNewDoc); setShowAddDoc(false); setShowNewSub(false); }}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] surface-raised hover:bg-[var(--ds-raised)] text-default transition-colors"
        >
          <FilePlus size={10} /> New Document
        </button>
        <button
          onClick={() => { setShowNewSub(!showNewSub); setShowAddDoc(false); setShowNewDoc(false); }}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] surface-raised hover:bg-[var(--ds-raised)] text-default transition-colors"
        >
          <Folder size={10} /> New Subfolder
        </button>
      </div>

      {/* Inline forms */}
      {showAddDoc && <AddDocForm onSubmit={handleAddExistingDoc} onCancel={() => setShowAddDoc(false)} />}
      {showNewDoc && <NewDocForm onSubmit={handleCreateDoc} onCancel={() => setShowNewDoc(false)} />}
      {showNewSub && <NewSubfolderForm onSubmit={handleCreateSubfolder} onCancel={() => setShowNewSub(false)} />}

      {/* Contents */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-1.5">
        {/* Subfolders */}
        {folder.subfolders?.length > 0 && (
          <div className="mb-3">
            <div className="text-[10px] text-faint uppercase tracking-wider mb-1.5">Subfolders</div>
            {[...folder.subfolders].sort((a, b) => a.name.localeCompare(b.name)).map((sf) => (
              <button
                key={sf.id}
                onClick={() => onOpenApp?.("folder", { folderId: sf.id, title: sf.name })}
                className="w-full text-left flex items-center gap-2 p-2 rounded-md surface-card hover:bg-[var(--ds-card)] border border-subtle hover:border-blue-700/30 transition-all mb-1"
              >
                <Folder size={14} className="text-blue-400 shrink-0" />
                <span className="text-xs text-default">{sf.name}</span>
                <span className="text-[10px] text-faint ml-auto">{sf.id}</span>
              </button>
            ))}
          </div>
        )}

        {/* Items */}
        {folder.items?.length > 0 ? (
          <div>
            <div className="text-[10px] text-faint uppercase tracking-wider mb-1.5">Contents</div>
            {[...folder.items].sort((a, b) => (a.title || a.entity_id).localeCompare(b.title || b.entity_id)).map((item) => (
              <ItemRow
                key={item.entity_id}
                item={item}
                onOpen={() => {
                  if (item.entity_id.startsWith("d-")) {
                    onOpenApp?.("document", { docId: item.entity_id, title: item.title || item.entity_id });
                  }
                }}
                onRemove={() => handleRemoveItem(item.entity_id)}
              />
            ))}
          </div>
        ) : (!folder.subfolders?.length && (
          <div className="text-center py-8 text-faint text-sm">
            This folder is empty. Add documents or create new ones above.
          </div>
        ))}
      </div>
    </div>
  );
}


function ItemRow({ item, onOpen, onRemove }) {
  const isDoc = item.entity_type === "document" || item.entity_id.startsWith("d-");
  const Icon = isDoc ? FileText : Paperclip;
  const iconColor = isDoc ? "text-emerald-400" : "text-amber-400";

  return (
    <div className="flex items-center gap-2 p-2 rounded-md surface-card hover:bg-[var(--ds-card)] border border-subtle group transition-all mb-1">
      <Icon size={14} className={`${iconColor} shrink-0`} />
      <button onClick={onOpen} className="flex-1 text-left min-w-0">
        <div className="text-xs text-default group-hover:text-[var(--ds-text)] truncate">
          {item.title || item.entity_id}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-faint">
          <span>{item.entity_id}</span>
          {item.word_count > 0 && <span>{item.word_count} words</span>}
          {item.mime_type && <span>{item.mime_type}</span>}
          {item.tags?.length > 0 && (
            <span>{item.tags.slice(0, 3).join(", ")}</span>
          )}
        </div>
      </button>
      <button
        onClick={onRemove}
        className="text-default hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all shrink-0"
        title="Remove from folder"
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}


function AddDocForm({ onSubmit, onCancel }) {
  const [docId, setDocId] = useState("");
  const [results, setResults] = useState([]);
  const [query, setQuery] = useState("");

  async function handleSearch() {
    if (!query.trim()) return;
    try {
      const res = await fetch(`/api/docs?q=${encodeURIComponent(query.trim())}`);
      if (res.ok) {
        const data = await res.json();
        setResults(data.docs || data || []);
      }
    } catch {}
  }

  return (
    <div className="px-3 py-2 bg-blue-950/20 border-b border-blue-900/30 space-y-2">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search documents to add..."
            className="w-full surface-card text-xs text-default pl-7 pr-2 py-1.5 rounded border border-subtle outline-none focus:border-blue-600"
          />
        </div>
        <button onClick={handleSearch} className="px-2 py-1 rounded text-xs bg-blue-600/80 text-on-accent hover:bg-blue-500">
          Search
        </button>
        <button onClick={onCancel} className="text-faint hover:text-[var(--ds-text)]">
          <X size={14} />
        </button>
      </div>
      <div className="text-[10px] text-faint">Or enter an entity ID directly:</div>
      <div className="flex items-center gap-2">
        <input
          value={docId}
          onChange={(e) => setDocId(e.target.value)}
          placeholder="d-xxxxxxxx or a-xxxxxxxx"
          className="flex-1 surface-card text-xs text-default px-2 py-1 rounded border border-subtle outline-none focus:border-blue-600"
        />
        <button
          onClick={() => docId.trim() && onSubmit(docId.trim())}
          disabled={!docId.trim()}
          className="px-2 py-1 rounded text-xs bg-blue-600 text-on-accent hover:bg-blue-500 disabled:opacity-30"
        >
          Add
        </button>
      </div>
      {results.length > 0 && (
        <div className="max-h-32 overflow-y-auto space-y-1">
          {results.map((doc) => (
            <button
              key={doc.id}
              onClick={() => onSubmit(doc.id)}
              className="w-full text-left flex items-center gap-2 px-2 py-1 rounded surface-card hover:bg-[var(--ds-raised)] text-xs text-default"
            >
              <FileText size={10} className="text-emerald-400 shrink-0" />
              <span className="truncate">{doc.title || doc.id}</span>
              <span className="text-[10px] text-faint ml-auto shrink-0">{doc.id}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}


function NewDocForm({ onSubmit, onCancel }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit(title.trim(), content);
  }

  return (
    <form onSubmit={handleSubmit} className="px-3 py-2 bg-emerald-950/20 border-b border-emerald-900/30 space-y-2">
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Document title..."
        className="w-full surface-card text-sm text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-emerald-600"
      />
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Initial content (optional, markdown)..."
        rows={3}
        className="w-full surface-card text-xs text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-emerald-600 resize-none"
      />
      <div className="flex items-center gap-2 justify-end">
        <button type="button" onClick={onCancel} className="px-3 py-1 rounded text-xs text-muted hover:text-[var(--ds-text)] transition-colors">
          Cancel
        </button>
        <button
          type="submit"
          disabled={!title.trim()}
          className="px-3 py-1 rounded text-xs bg-emerald-600 text-on-accent hover:bg-emerald-500 disabled:opacity-30 transition-colors"
        >
          Create Document
        </button>
      </div>
    </form>
  );
}


function NewSubfolderForm({ onSubmit, onCancel }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) return;
    onSubmit(name.trim(), description.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="px-3 py-2 bg-blue-950/20 border-b border-blue-900/30 space-y-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Subfolder name..."
        className="w-full surface-card text-sm text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-blue-600"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)..."
        className="w-full surface-card text-xs text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-blue-600"
      />
      <div className="flex items-center gap-2 justify-end">
        <button type="button" onClick={onCancel} className="px-3 py-1 rounded text-xs text-muted hover:text-[var(--ds-text)] transition-colors">
          Cancel
        </button>
        <button
          type="submit"
          disabled={!name.trim()}
          className="px-3 py-1 rounded text-xs bg-blue-600 text-on-accent hover:bg-blue-500 disabled:opacity-30 transition-colors"
        >
          Create Subfolder
        </button>
      </div>
    </form>
  );
}
