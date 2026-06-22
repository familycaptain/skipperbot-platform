import { useState, useEffect, useRef, useCallback } from "react";
import {
  Save, FileText, Loader2, Trash2, Printer,
  Eye, Edit3, ArrowLeft, RefreshCw, Link, Tag, X, MessageSquareQuote,
} from "lucide-react";
// MarkdownEditor is a platform-shared UI primitive. The relative path
// reflects the current apps/<id>/ui/ → ../../../web/src/components/
// layout. A `@platform/components` alias will replace this once the
// optional-app shared-UI design lands — see OPEN_SOURCE.md TODO §6.
import MarkdownEditor, { getSelection } from "../../../web/src/components/MarkdownEditor";

/**
 * Document Editor — multi-instance app for editing a single document.
 *
 * Opened with context: { docId } or { entityId } to load a specific document.
 * Each open document gets its own tab in the taskbar.
 *
 * Props:
 *   appId, userId, context, onTitle, onContextChange, refreshKey, onOpenApp
 */

const API_BASE = "";

export default function DocumentEditor({ appId, userId, context = {}, onTitle, onContextChange, refreshKey, onOpenApp }) {
  const [docId, setDocId] = useState(null);
  const [docMeta, setDocMeta] = useState(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [hasSelection, setHasSelection] = useState(false);
  const [pinnedSelection, setPinnedSelection] = useState(null);

  const editorViewRef = useRef(null);

  // Load doc from context on mount or when context changes
  const contextDocId = context.docId || context.entityId || null;
  useEffect(() => {
    if (contextDocId) {
      loadDoc(contextDocId);
    }
  }, [contextDocId]);

  // Auto-refresh when chat mutates document data
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (docId && !dirty) loadDoc(docId);
  }, [refreshKey]);

  // Ctrl+S to save
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [content, dirty, docId, userId]);

  // Track selection changes from the editor
  const handleSelectionChange = useCallback((selectedText) => {
    setHasSelection(!!selectedText);
  }, []);

  function handlePinSelection() {
    const sel = getSelection(editorViewRef.current);
    if (!sel) return;
    setPinnedSelection(sel);
    setHasSelection(false);
    onContextChange?.({
      app: "documents",
      view: "editor",
      entityId: docId,
      entityName: docMeta?.title || "Document",
      entityType: "document",
      selectedText: sel,
      documentContent: content,
    });
  }

  function handleClearPin() {
    setPinnedSelection(null);
    onContextChange?.({
      app: "documents",
      view: "editor",
      entityId: docId,
      entityName: docMeta?.title || "Document",
      entityType: "document",
      documentContent: content,
    });
  }

  /* ── Data fetching ── */

  async function loadDoc(id) {
    setLoading(true);
    setError(null);
    setConfirmDelete(false);
    try {
      const res = await fetch(`${API_BASE}/api/apps/documents/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setDocId(id);
      setDocMeta(data);
      setContent(data.content || "");
      setDirty(false);
      setPreview(false);
      onTitle?.(data.title || "Document");
      onContextChange?.({
        app: "documents",
        view: "editor",
        entityId: id,
        entityName: data.title || "Document",
        entityType: "document",
        documentContent: data.content || "",
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!dirty || !docId) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/apps/documents/${docId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, updated_by: userId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDirty(false);
    } catch (e) {
      setError(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!docId) return;
    try {
      await fetch(`${API_BASE}/api/apps/documents/${docId}`, { method: "DELETE" });
      // Open the doc list (focuses the singleton Documents app)
      onOpenApp?.("documents");
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleRename(newTitle) {
    if (!newTitle.trim() || !docId) return;
    try {
      await fetch(`${API_BASE}/api/apps/documents/${docId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle.trim(), updated_by: userId }),
      });
      setDocMeta((m) => ({ ...m, title: newTitle.trim() }));
      onTitle?.(newTitle.trim());
      setEditingTitle(false);
    } catch (e) {
      setError(e.message);
    }
  }

  function handlePrint() {
    const printContent = content || "";
    const html = markdownToHtml(printContent);
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(`<!DOCTYPE html><html><head><title>${docMeta?.title || "Document"}</title>
      <style>body{font-family:system-ui,sans-serif;max-width:700px;margin:40px auto;padding:0 20px;line-height:1.6;color:#1a1a1a;}
      h1,h2,h3{margin-top:1.5em;}pre{background:#f4f4f4;padding:12px;border-radius:4px;overflow-x:auto;}
      code{background:#f4f4f4;padding:2px 4px;border-radius:2px;}table{border-collapse:collapse;width:100%;}
      th,td{border:1px solid #ddd;padding:8px;text-align:left;}th{background:#f4f4f4;}</style></head>
      <body>${html}</body></html>`);
    win.document.close();
    win.print();
  }

  /* ── Main render ── */
  return (
    <div className="flex flex-col h-full w-full">
      {/* ── Toolbar ── */}
      <div className="flex items-center justify-between px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <div className="flex items-center gap-1.5 text-sm text-default min-w-0">
          <button onClick={() => onOpenApp?.("documents")} className="p-1 text-faint hover:text-[var(--ds-text)] transition-colors shrink-0" title="Back to document list">
            <ArrowLeft size={14} />
          </button>
          <FileText size={14} className="text-faint shrink-0" />
          {editingTitle ? (
            <form onSubmit={(e) => { e.preventDefault(); handleRename(titleDraft); }} className="flex items-center gap-1">
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => setEditingTitle(false)}
                onKeyDown={(e) => { if (e.key === "Escape") setEditingTitle(false); }}
                className="surface-card text-default text-sm px-1.5 py-0.5 rounded border border-subtle outline-none w-48"
              />
            </form>
          ) : (
            <button
              onClick={() => { setTitleDraft(docMeta?.title || ""); setEditingTitle(true); }}
              className="truncate hover:text-[var(--ds-text)] transition-colors"
              title="Click to rename"
            >
              {docMeta?.title || "Untitled"}
            </button>
          )}
          {dirty && <span className="text-xs text-amber-400 shrink-0">unsaved</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setPreview(!preview)}
            className={`p-1 rounded text-xs transition-colors ${preview ? "text-indigo-400 surface-raised" : "text-faint hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)]"}`}
            title={preview ? "Edit" : "Preview"}
          >
            {preview ? <Edit3 size={14} /> : <Eye size={14} />}
          </button>
          {hasSelection && !preview && (
            <button
              onMouseDown={(e) => { e.preventDefault(); handlePinSelection(); }}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-indigo-600 text-on-accent hover:bg-indigo-500 transition-colors animate-pulse"
              title="Send selected text to Skipper"
            >
              <MessageSquareQuote size={12} />
              Quote to Chat
            </button>
          )}
          <button onClick={handlePrint} className="p-1 rounded text-faint hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)] transition-colors" title="Print">
            <Printer size={14} />
          </button>
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)] disabled:opacity-30 disabled:cursor-default transition-colors"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save
          </button>
          {!confirmDelete ? (
            <button onClick={() => setConfirmDelete(true)} className="p-1 rounded text-faint hover:text-red-400 hover:bg-[var(--ds-raised)] transition-colors" title="Delete">
              <Trash2 size={14} />
            </button>
          ) : (
            <span className="flex items-center gap-1 text-xs">
              <span className="text-red-400">Delete?</span>
              <button onClick={handleDelete} className="px-1.5 py-0.5 rounded bg-red-600 text-on-accent text-xs hover:bg-red-500">Yes</button>
              <button onClick={() => setConfirmDelete(false)} className="px-1.5 py-0.5 rounded surface-raised text-default text-xs hover:bg-[var(--ds-raised)]">No</button>
            </span>
          )}
          <button
            onClick={() => docId && loadDoc(docId)}
            disabled={loading}
            className="p-1 rounded text-faint hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)] transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Tags + links bar */}
      {docMeta && (
        <DocMetaBar docMeta={docMeta} docId={docId} userId={userId} onUpdate={(m) => setDocMeta(m)} />
      )}

      {/* Pinned selection quote card */}
      {pinnedSelection && (
        <div className="px-3 py-2 bg-indigo-950/40 border-b border-indigo-800/50 flex items-start gap-2">
          <MessageSquareQuote size={14} className="text-indigo-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-xs text-indigo-400 font-medium mb-0.5">Quoted to Skipper</div>
            <div className="text-xs text-muted line-clamp-3 font-mono whitespace-pre-wrap">{pinnedSelection}</div>
          </div>
          <button onClick={handleClearPin} className="text-indigo-400/60 hover:text-[var(--ds-text)] shrink-0" title="Clear quote">
            <X size={12} />
          </button>
        </div>
      )}

      {/* Error bar */}
      {error && (
        <div className="px-3 py-1.5 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-[var(--ds-text)]"><X size={12} /></button>
        </div>
      )}

      {/* ── Content ── */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {!preview ? (
          <MarkdownEditor
            value={content}
            onChange={(val) => { setContent(val); setDirty(true); }}
            readOnly={false}
            placeholder="Start writing..."
            onSelectionChange={handleSelectionChange}
            onEditorReady={(view) => { editorViewRef.current = view; }}
          />
        ) : (
          <div
            className="p-4 markdown-body text-sm text-default max-w-none overflow-auto"
            dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
          />
        )}
      </div>
    </div>
  );
}

/* ── Document Meta Bar (tags + linked entities) ── */

function DocMetaBar({ docMeta, docId, userId, onUpdate }) {
  const [editingTags, setEditingTags] = useState(false);
  const [tagDraft, setTagDraft] = useState("");
  const [linkDraft, setLinkDraft] = useState("");
  const [linking, setLinking] = useState(false);

  const tags = docMeta.tags || [];
  const linkedEntities = docMeta.linked_entities || [];

  async function saveTags(newTags) {
    try {
      const res = await fetch(`${API_BASE}/api/apps/documents/${docId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags: newTags.join(","), updated_by: userId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      onUpdate(data);
    } catch {}
  }

  async function handleAddTag(e) {
    e.preventDefault();
    if (!tagDraft.trim()) return;
    const newTags = [...tags, tagDraft.trim().toLowerCase()];
    await saveTags(newTags);
    setTagDraft("");
  }

  async function handleRemoveTag(tag) {
    const newTags = tags.filter((t) => t !== tag);
    await saveTags(newTags);
  }

  async function handleLink(e) {
    e.preventDefault();
    if (!linkDraft.trim()) return;
    setLinking(true);
    try {
      await fetch(`${API_BASE}/api/apps/documents/${docId}/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: linkDraft.trim(), created_by: userId }),
      });
      // Reload doc to get updated linked_entities
      const res = await fetch(`${API_BASE}/api/apps/documents/${docId}`);
      const data = await res.json();
      onUpdate(data);
      setLinkDraft("");
    } catch {} finally {
      setLinking(false);
    }
  }

  async function handleUnlink(entityId) {
    try {
      await fetch(`${API_BASE}/api/apps/documents/${docId}/unlink`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: entityId }),
      });
      const res = await fetch(`${API_BASE}/api/apps/documents/${docId}`);
      const data = await res.json();
      onUpdate(data);
    } catch {}
  }

  return (
    <div className="px-3 py-1.5 surface-panel border-b border-subtle flex flex-wrap items-center gap-2 text-xs text-faint">
      {/* Doc ID */}
      <span className="text-faint font-mono select-all">{docId}</span>

      <span className="text-default mx-1">|</span>

      {/* Tags */}
      <Tag size={10} className="shrink-0" />
      {tags.map((t) => (
        <span key={t} className="flex items-center gap-0.5 px-1.5 py-0.5 surface-card rounded text-muted">
          {t}
          <button onClick={() => handleRemoveTag(t)} className="hover:text-[var(--ds-text)]"><X size={8} /></button>
        </span>
      ))}
      {editingTags ? (
        <form onSubmit={handleAddTag} className="flex items-center gap-1">
          <input
            autoFocus
            value={tagDraft}
            onChange={(e) => setTagDraft(e.target.value)}
            onBlur={() => { if (!tagDraft) setEditingTags(false); }}
            onKeyDown={(e) => { if (e.key === "Escape") setEditingTags(false); }}
            placeholder="tag"
            className="surface-card text-default text-xs px-1.5 py-0.5 rounded border border-subtle outline-none w-20"
          />
        </form>
      ) : (
        <button onClick={() => setEditingTags(true)} className="text-faint hover:text-[var(--ds-text)]">+ tag</button>
      )}

      <span className="text-default mx-1">|</span>

      {/* Links */}
      <Link size={10} className="shrink-0" />
      {linkedEntities.length === 0 && !linking && (
        <span className="text-faint">no links</span>
      )}
      {linkedEntities.map((eid) => (
        <span key={eid} className="flex items-center gap-0.5 px-1.5 py-0.5 surface-card rounded text-indigo-400/70">
          {eid}
          <button onClick={() => handleUnlink(eid)} className="hover:text-[var(--ds-text)]"><X size={8} /></button>
        </span>
      ))}
      {linking ? (
        <form onSubmit={handleLink} className="flex items-center gap-1">
          <input
            autoFocus
            value={linkDraft}
            onChange={(e) => setLinkDraft(e.target.value)}
            onBlur={() => { if (!linkDraft) setLinking(false); }}
            onKeyDown={(e) => { if (e.key === "Escape") setLinking(false); }}
            placeholder="entity ID (e.g. p-xxx)"
            className="surface-card text-default text-xs px-1.5 py-0.5 rounded border border-subtle outline-none w-36"
          />
        </form>
      ) : (
        <button onClick={() => setLinking(true)} className="text-faint hover:text-[var(--ds-text)]">+ link</button>
      )}
    </div>
  );
}

/* ── Minimal markdown → HTML ── */

function markdownToHtml(md) {
  if (!md) return "";

  // Parse tables before other transforms (so pipes don't get mangled)
  md = md.replace(
    /^(\|.+\|)\n(\|[-:| ]+\|)\n((?:\|.+\|\n?)+)/gm,
    (_, headerRow, _sepRow, bodyBlock) => {
      const parseRow = (row) =>
        row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const headers = parseRow(headerRow);
      const thHtml = headers.map((h) => `<th>${h}</th>`).join("");
      const rows = bodyBlock.trim().split("\n");
      const tbodyHtml = rows
        .map((r) => {
          const cells = parseRow(r);
          return `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
        })
        .join("");
      return `<table><thead><tr>${thHtml}</tr></thead><tbody>${tbodyHtml}</tbody></table>`;
    }
  );

  let html = md
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    // Headings
    .replace(/^#### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    // Bold + italic
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    // Horizontal rule
    .replace(/^---$/gm, "<hr/>")
    // Unordered lists
    .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-400 underline">$1</a>');
  // Collapse all whitespace between adjacent list items so they stay grouped
  html = html.replace(/<\/li>\n+<li>/g, "</li><li>");
  // Wrap consecutive <li> runs in <ul> BEFORE paragraph conversion
  html = html.replace(/((?:<li>[\s\S]*?<\/li>)+)/g, "<ul>$1</ul>");
  html = html
    // Line breaks → paragraphs
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br/>");
  return `<p>${html}</p>`;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
