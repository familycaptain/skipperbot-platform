import { useState, useEffect, useRef, useCallback } from "react";
import {
  Lightbulb, Save, Loader2, Trash2, Eye, Edit3, ArrowLeft,
  RefreshCw, X, Plus, FileText, GitBranch, Image as ImageIcon,
  Link2, GraduationCap, Tag, ChevronDown, Check, XCircle, MessageSquareQuote,
} from "lucide-react";
import MarkdownEditor, { getSelection } from "../../../web/src/components/MarkdownEditor";
import { buildMergedView, countChanges } from "../../../web/src/utils/diffUtils";
import { lazy, Suspense } from "react";

const FlowchartEditor = lazy(() => import("../../../web/src/components/FlowchartEditor"));

const STATUS_OPTIONS = ["idea", "exploring", "developing", "parked", "graduated"];
const PRIORITY_OPTIONS = ["high", "medium", "low"];

const STATUS_COLORS = {
  idea: "bg-sky-500/20 text-sky-400 border-sky-500/30",
  exploring: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  developing: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  parked: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  graduated: "bg-purple-500/20 text-purple-400 border-purple-500/30",
};

export default function BrainstormDetailApp({ appId, userId, context = {}, onTitle, onContextChange, refreshKey, onOpenApp, editProposal, onClearEditProposal }) {
  const [idea, setIdea] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Editor state for the active part
  const [activePartId, setActivePartId] = useState(null);
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(false);

  // Metadata editing
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState("");
  const [showStatusMenu, setShowStatusMenu] = useState(false);
  const [showPriorityMenu, setShowPriorityMenu] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Tags
  const [editingTags, setEditingTags] = useState(false);
  const [tagDraft, setTagDraft] = useState("");

  const editorViewRef = useRef(null);
  const [hasSelection, setHasSelection] = useState(false);
  const [pinnedSelection, setPinnedSelection] = useState(null);

  // Review mode state (inline diff from Skipper)
  const [reviewData, setReviewData] = useState(null); // { mergedText, highlights, revised, original, instruction, ideaId, partId }
  const [acceptingEdit, setAcceptingEdit] = useState(false);

  const ideaId = context.ideaId || null;

  // Load idea
  useEffect(() => {
    if (ideaId) loadIdea(ideaId);
  }, [ideaId]);

  // Auto-refresh when tools mutate brainstorming data
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (!ideaId || reviewData) return;
    // Force reload even when dirty — the tool just wrote authoritative content
    loadIdea(ideaId);
  }, [refreshKey]);

  // Handle incoming edit proposal from Skipper
  useEffect(() => {
    if (!editProposal) return;
    // Only handle proposals for this idea
    if (editProposal.idea_id !== ideaId) return;
    // Only handle proposals for the active part (or any part if none active)
    if (activePartId && editProposal.part_id && editProposal.part_id !== activePartId) return;

    const diffs = editProposal.diffs || [];
    if (diffs.length === 0) return;

    const { mergedText, highlights } = buildMergedView(diffs);
    setReviewData({
      mergedText,
      highlights,
      revised: editProposal.revised || "",
      original: editProposal.original || "",
      instruction: editProposal.instruction || "",
      ideaId: editProposal.idea_id,
      partId: editProposal.part_id,
      diffs,
    });
    setPreview(false);
    onClearEditProposal?.();
  }, [editProposal]);

  // Ctrl+S
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSavePart();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [content, dirty, activePartId, ideaId]);

  async function loadIdea(id) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/apps/brainstorming/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setIdea(data);
      onTitle?.(data.title || "Idea");

      // Select the main doc part by default (or the first part)
      const parts = data.parts || [];
      const mainPart = parts.find(p => p.is_main) || parts[0];
      let docContent = "";
      if (mainPart && (!activePartId || !parts.find(p => p.id === activePartId))) {
        setActivePartId(mainPart.id);
        setContent(mainPart.content || "");
        setDirty(false);
        docContent = mainPart.content || "";
      } else if (activePartId) {
        const currentPart = parts.find(p => p.id === activePartId);
        if (currentPart && !dirty) {
          setContent(currentPart.content || "");
        }
        docContent = currentPart?.content || "";
      }

      // Tell chat engine which idea is open
      onContextChange?.({
        app: "brainstorming",
        view: "detail",
        entityId: data.id,
        entityName: data.title || "Idea",
        entityType: "idea",
        partId: mainPart?.id || "",
        documentContent: docContent,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function selectPart(part) {
    if (dirty && activePartId !== part.id) {
      if (!confirm("You have unsaved changes. Switch anyway?")) return;
    }
    setActivePartId(part.id);
    setContent(part.content || "");
    setDirty(false);
    setPreview(false);
    // Update context with the newly selected part
    if (idea) {
      onContextChange?.({
        app: "brainstorming",
        view: "detail",
        entityId: idea.id,
        entityName: idea.title || "Idea",
        entityType: "idea",
        partId: part.id,
        documentContent: part.content || "",
      });
      setPinnedSelection(null);
    }
  }

  async function handleSavePart() {
    if (!dirty || !activePartId || !ideaId) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/apps/brainstorming/${ideaId}/parts/${activePartId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDirty(false);
      // Refresh to get updated_at
      loadIdea(ideaId);
    } catch (e) {
      setError(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdateMeta(fields) {
    if (!ideaId) return;
    try {
      const res = await fetch(`/api/apps/brainstorming/${ideaId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (res.ok) {
        const data = await res.json();
        setIdea(data);
        if (fields.title) onTitle?.(fields.title);
      }
    } catch {}
  }

  async function handleAddTag(e) {
    e.preventDefault();
    if (!tagDraft.trim() || !idea) return;
    const newTags = [...(idea.tags || []), tagDraft.trim().toLowerCase()];
    await handleUpdateMeta({ tags: newTags });
    setTagDraft("");
  }

  async function handleRemoveTag(tag) {
    if (!idea) return;
    const newTags = (idea.tags || []).filter(t => t !== tag);
    await handleUpdateMeta({ tags: newTags });
  }

  async function handleDelete() {
    if (!ideaId) return;
    try {
      await fetch(`/api/apps/brainstorming/${ideaId}`, { method: "DELETE" });
      onOpenApp?.("brainstorming");
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleGraduate() {
    if (!ideaId) return;
    try {
      await fetch(`/api/apps/brainstorming/${ideaId}/graduate`, { method: "POST" });
      loadIdea(ideaId);
    } catch {}
  }

  // Save flowchart meta (debounced by FlowchartEditor, called on every change)
  async function handleSaveFlowchartMeta(newMeta) {
    if (!ideaId || !activePartId) return;
    try {
      await fetch(`/api/apps/brainstorming/${ideaId}/parts/${activePartId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meta: newMeta }),
      });
    } catch {}
  }

  const [showAddPartMenu, setShowAddPartMenu] = useState(false);
  const [renamingPartId, setRenamingPartId] = useState(null);
  const [partTitleDraft, setPartTitleDraft] = useState("");

  async function handleRenamePart(partId, newTitle) {
    setRenamingPartId(null);
    if (!newTitle?.trim() || !ideaId) return;
    try {
      await fetch(`/api/apps/brainstorming/${ideaId}/parts/${partId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle.trim() }),
      });
      await loadIdea(ideaId);
    } catch {}
  }

  async function handleAddPart(partType = "document") {
    if (!ideaId) return;
    setShowAddPartMenu(false);
    const defaultTitle = partType === "flowchart" ? "Flowchart" : "Document";
    const title = prompt(`New ${defaultTitle.toLowerCase()} title:`, defaultTitle);
    if (!title?.trim()) return;
    const meta = partType === "flowchart" ? { nodes: [], edges: [] } : {};
    try {
      const res = await fetch(`/api/apps/brainstorming/${ideaId}/parts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: partType, title: title.trim(), meta }),
      });
      if (res.ok) {
        const part = await res.json();
        await loadIdea(ideaId);
        selectPart(part);
      }
    } catch {}
  }

  async function handleDeletePart(partId) {
    if (!ideaId) return;
    try {
      const res = await fetch(`/api/apps/brainstorming/${ideaId}/parts/${partId}`, { method: "DELETE" });
      if (res.ok) {
        await loadIdea(ideaId);
      }
    } catch {}
  }

  // Accept proposed revision — save revised content
  async function handleAcceptEdit() {
    if (!reviewData) return;
    setAcceptingEdit(true);
    try {
      const res = await fetch(
        `/api/apps/brainstorming/${reviewData.ideaId}/parts/${reviewData.partId}/accept-edit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: reviewData.revised }),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // Apply revised content locally and exit review mode
      setContent(reviewData.revised);
      setDirty(false);
      setReviewData(null);
      // Reload to get updated version
      loadIdea(ideaId);
    } catch (e) {
      setError(`Accept failed: ${e.message}`);
    } finally {
      setAcceptingEdit(false);
    }
  }

  // Reject proposed revision — restore original content
  function handleRejectEdit() {
    if (!reviewData) return;
    setContent(reviewData.original);
    setDirty(false);
    setReviewData(null);
  }

  // Quote to Chat — pin the current selection so it persists when clicking into chat
  function handlePinSelection() {
    const sel = getSelection(editorViewRef.current);
    if (!sel) return;
    setPinnedSelection(sel);
    setHasSelection(false);
    if (idea) {
      onContextChange?.({
        app: "brainstorming",
        view: "detail",
        entityId: idea.id,
        entityName: idea.title || "Idea",
        entityType: "idea",
        partId: activePartId || "",
        selectedText: sel,
      });
    }
  }

  function handleClearPin() {
    setPinnedSelection(null);
    if (idea) {
      onContextChange?.({
        app: "brainstorming",
        view: "detail",
        entityId: idea.id,
        entityName: idea.title || "Idea",
        entityType: "idea",
        partId: activePartId || "",
      });
    }
  }

  const handleSelectionChange = useCallback((selectedText) => {
    setHasSelection(!!selectedText);
  }, []);

  const activePart = idea?.parts?.find(p => p.id === activePartId);
  const parts = idea?.parts || [];

  if (loading && !idea) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading idea...
      </div>
    );
  }

  if (!idea) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Idea not found.
      </div>
    );
  }

  const statusClass = STATUS_COLORS[idea.status] || STATUS_COLORS.idea;

  return (
    <div className="flex flex-col h-full w-full">
      {/* ── Toolbar ── */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1.5 text-sm text-slate-300 min-w-0">
          <button onClick={() => onOpenApp?.("brainstorming")} className="p-1 text-slate-500 hover:text-white transition-colors shrink-0" title="Back to ideas">
            <ArrowLeft size={14} />
          </button>
          <Lightbulb size={14} className="text-amber-400 shrink-0" />
          {editingTitle ? (
            <form onSubmit={(e) => { e.preventDefault(); handleUpdateMeta({ title: titleDraft }); setEditingTitle(false); }} className="flex items-center gap-1">
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => setEditingTitle(false)}
                onKeyDown={(e) => { if (e.key === "Escape") setEditingTitle(false); }}
                className="bg-slate-800 text-white text-sm px-1.5 py-0.5 rounded border border-slate-600 outline-none w-56"
              />
            </form>
          ) : (
            <button
              onClick={() => { setTitleDraft(idea.title || ""); setEditingTitle(true); }}
              className="truncate hover:text-white transition-colors font-medium"
              title="Click to rename"
            >
              {idea.title || "Untitled Idea"}
            </button>
          )}
          {dirty && <span className="text-xs text-amber-400 shrink-0">unsaved</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {/* Status selector */}
          <div className="relative">
            <button
              onClick={() => { setShowStatusMenu(!showStatusMenu); setShowPriorityMenu(false); }}
              className={`px-2 py-0.5 rounded text-[11px] font-medium border capitalize ${statusClass}`}
            >
              {idea.status} <ChevronDown size={10} className="inline" />
            </button>
            {showStatusMenu && (
              <div className="absolute right-0 top-full mt-1 bg-slate-800 border border-slate-700 rounded shadow-lg z-10 py-1 min-w-[120px]">
                {STATUS_OPTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => { handleUpdateMeta({ status: s }); setShowStatusMenu(false); }}
                    className={`block w-full text-left px-3 py-1 text-xs capitalize hover:bg-slate-700 transition-colors ${idea.status === s ? "text-white font-medium" : "text-slate-400"}`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
          {/* Priority selector */}
          <div className="relative">
            <button
              onClick={() => { setShowPriorityMenu(!showPriorityMenu); setShowStatusMenu(false); }}
              className="px-2 py-0.5 rounded text-[11px] text-slate-400 hover:text-white border border-slate-700 capitalize"
            >
              {idea.priority} <ChevronDown size={10} className="inline" />
            </button>
            {showPriorityMenu && (
              <div className="absolute right-0 top-full mt-1 bg-slate-800 border border-slate-700 rounded shadow-lg z-10 py-1 min-w-[100px]">
                {PRIORITY_OPTIONS.map(p => (
                  <button
                    key={p}
                    onClick={() => { handleUpdateMeta({ priority: p }); setShowPriorityMenu(false); }}
                    className={`block w-full text-left px-3 py-1 text-xs capitalize hover:bg-slate-700 transition-colors ${idea.priority === p ? "text-white font-medium" : "text-slate-400"}`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
          </div>
          {hasSelection && !preview && !reviewData && (
            <button
              onMouseDown={(e) => { e.preventDefault(); handlePinSelection(); }}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-indigo-600 text-white hover:bg-indigo-500 transition-colors animate-pulse"
              title="Send selected text to Skipper"
            >
              <MessageSquareQuote size={12} />
              Quote to Chat
            </button>
          )}
          <button onClick={() => setPreview(!preview)} className={`p-1 rounded text-xs transition-colors ${preview ? "text-indigo-400 bg-slate-700" : "text-slate-500 hover:text-white hover:bg-slate-700"}`} title={preview ? "Edit" : "Preview"}>
            {preview ? <Edit3 size={14} /> : <Eye size={14} />}
          </button>
          <button onClick={handleSavePart} disabled={!dirty || saving} className="flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-400 hover:text-white hover:bg-slate-700 disabled:opacity-30 transition-colors">
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save
          </button>
          {!confirmDelete ? (
            <button onClick={() => setConfirmDelete(true)} className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-slate-700 transition-colors" title="Delete idea">
              <Trash2 size={14} />
            </button>
          ) : (
            <span className="flex items-center gap-1 text-xs">
              <span className="text-red-400">Delete?</span>
              <button onClick={handleDelete} className="px-1.5 py-0.5 rounded bg-red-600 text-white text-xs hover:bg-red-500">Yes</button>
              <button onClick={() => setConfirmDelete(false)} className="px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 text-xs hover:bg-slate-600">No</button>
            </span>
          )}
          <button onClick={() => ideaId && loadIdea(ideaId)} disabled={loading} className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors" title="Refresh">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Summary + Tags bar */}
      <div className="px-3 py-1.5 bg-slate-900/20 border-b border-slate-800/50 flex flex-wrap items-center gap-2 text-xs">
        {/* Summary */}
        {editingSummary ? (
          <form
            onSubmit={(e) => { e.preventDefault(); handleUpdateMeta({ summary: summaryDraft }); setEditingSummary(false); }}
            className="flex-1 min-w-0"
          >
            <input
              autoFocus
              value={summaryDraft}
              onChange={(e) => setSummaryDraft(e.target.value)}
              onBlur={() => { handleUpdateMeta({ summary: summaryDraft }); setEditingSummary(false); }}
              onKeyDown={(e) => { if (e.key === "Escape") setEditingSummary(false); }}
              placeholder="Brief summary..."
              className="w-full bg-slate-800 text-slate-300 text-xs px-2 py-0.5 rounded border border-slate-600 outline-none"
            />
          </form>
        ) : (
          <button
            onClick={() => { setSummaryDraft(idea.summary || ""); setEditingSummary(true); }}
            className="text-slate-500 hover:text-slate-300 italic truncate max-w-[300px]"
            title="Click to edit summary"
          >
            {idea.summary || "Add summary..."}
          </button>
        )}

        <span className="text-slate-700 mx-1">|</span>

        {/* Tags */}
        <Tag size={10} className="text-slate-500 shrink-0" />
        {(idea.tags || []).map(t => (
          <span key={t} className="flex items-center gap-0.5 px-1.5 py-0.5 bg-slate-800 rounded text-slate-400">
            {t}
            <button onClick={() => handleRemoveTag(t)} className="hover:text-white"><X size={8} /></button>
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
              className="bg-slate-800 text-slate-300 text-xs px-1.5 py-0.5 rounded border border-slate-700 outline-none w-20"
            />
          </form>
        ) : (
          <button onClick={() => setEditingTags(true)} className="text-slate-600 hover:text-slate-300">+ tag</button>
        )}

        {idea.status !== "graduated" && (
          <>
            <span className="text-slate-700 mx-1">|</span>
            <button
              onClick={handleGraduate}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-purple-600/30 hover:bg-purple-600/50 text-purple-400 border border-purple-500/30 transition-colors"
            >
              <GraduationCap size={10} />
              Graduate to Project
            </button>
          </>
        )}
      </div>

      {/* Pinned selection quote card */}
      {pinnedSelection && (
        <div className="px-3 py-2 bg-indigo-950/40 border-b border-indigo-800/50 flex items-start gap-2 shrink-0">
          <MessageSquareQuote size={14} className="text-indigo-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-xs text-indigo-400 font-medium mb-0.5">Quoted to Skipper</div>
            <div className="text-xs text-slate-400 line-clamp-3 font-mono whitespace-pre-wrap">{pinnedSelection}</div>
          </div>
          <button onClick={handleClearPin} className="text-indigo-400/60 hover:text-white shrink-0" title="Clear quote">
            <X size={12} />
          </button>
        </div>
      )}

      {/* Error bar */}
      {error && (
        <div className="px-3 py-1.5 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-white"><X size={12} /></button>
        </div>
      )}

      {/* Part tabs */}
      <div className="flex items-center bg-slate-900/30 border-b border-slate-800/50 shrink-0">
        <div className="flex items-center gap-0.5 px-3 py-1 overflow-x-auto flex-1 min-w-0">
          {parts.map(p => {
            const isActive = p.id === activePartId;
            const Icon = p.type === "flowchart" ? GitBranch : p.type === "image" ? ImageIcon : p.type === "link" ? Link2 : FileText;
            return (
              <div key={p.id} className="flex items-center shrink-0">
                {renamingPartId === p.id ? (
                  <form
                    onSubmit={(e) => { e.preventDefault(); handleRenamePart(p.id, partTitleDraft); }}
                    className="flex items-center gap-1 px-1"
                  >
                    <input
                      autoFocus
                      value={partTitleDraft}
                      onChange={(e) => setPartTitleDraft(e.target.value)}
                      onBlur={() => handleRenamePart(p.id, partTitleDraft)}
                      onKeyDown={(e) => { if (e.key === "Escape") setRenamingPartId(null); }}
                      className="bg-slate-700 text-white text-[11px] px-1.5 py-0.5 rounded border border-slate-600 outline-none w-24"
                    />
                  </form>
                ) : (
                  <button
                    onClick={() => selectPart(p)}
                    onDoubleClick={() => { if (!p.is_main) { setRenamingPartId(p.id); setPartTitleDraft(p.title || ""); } }}
                    className={`flex items-center gap-1 px-2 py-1 rounded-t text-[11px] transition-colors ${isActive ? "bg-slate-800 text-white border-b-2 border-amber-500" : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/50"}`}
                    title={p.is_main ? p.title : "Double-click to rename"}
                  >
                    <Icon size={10} />
                    {p.title || p.type}
                  </button>
                )}
                {!p.is_main && isActive && (
                  <button
                    onClick={() => { if (window.confirm(`Delete "${p.title || p.type}"? This cannot be undone.`)) handleDeletePart(p.id); }}
                    className="p-0.5 text-slate-600 hover:text-red-400 transition-colors"
                    title="Delete this part"
                  >
                    <X size={10} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
        <span className="text-slate-700 mx-0.5 shrink-0">|</span>
        <button
          onClick={() => handleAddPart("document")}
          className="flex items-center gap-0.5 px-1.5 py-1 text-[11px] text-slate-600 hover:text-slate-300 transition-colors shrink-0"
          title="Add document"
        >
          <Plus size={8} /><FileText size={10} />
        </button>
        <button
          onClick={() => handleAddPart("flowchart")}
          className="flex items-center gap-0.5 px-1.5 py-1 text-[11px] text-slate-600 hover:text-slate-300 transition-colors shrink-0"
          title="Add flowchart"
        >
          <Plus size={8} /><GitBranch size={10} />
        </button>
      </div>

      {/* ── Review mode banner ── */}
      {reviewData && (
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-indigo-900/40 border-b border-indigo-700/50 shrink-0">
          <div className="flex items-center gap-2 text-xs text-indigo-300 min-w-0 flex-1">
            <Eye size={14} className="shrink-0" />
            <span className="font-medium shrink-0">Review Mode</span>
            <span className="text-indigo-400/70 break-words line-clamp-2">— {reviewData.instruction}</span>
            <span className="text-indigo-400/50 shrink-0 whitespace-nowrap">
              ({countChanges(reviewData.diffs).additions}+ {countChanges(reviewData.diffs).deletions}−)
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleAcceptEdit}
              disabled={acceptingEdit}
              className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50"
            >
              {acceptingEdit ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Accept All
            </button>
            <button
              onClick={handleRejectEdit}
              disabled={acceptingEdit}
              className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium bg-red-600/80 hover:bg-red-500 text-white transition-colors disabled:opacity-50"
            >
              <XCircle size={12} />
              Reject
            </button>
          </div>
        </div>
      )}

      {/* ── Content area ── */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {!activePart ? (
          <div className="flex items-center justify-center h-full text-slate-600 text-sm">
            No parts available.
          </div>
        ) : activePart.type === "document" ? (
          reviewData ? (
            <MarkdownEditor
              key="review"
              value={reviewData.mergedText}
              readOnly={true}
              placeholder=""
              diffHighlights={reviewData.highlights}
            />
          ) : !preview ? (
            <MarkdownEditor
              key="edit"
              value={content}
              onChange={(val) => { setContent(val); setDirty(true); }}
              readOnly={false}
              placeholder="Start writing your idea..."
              onEditorReady={(view) => { editorViewRef.current = view; }}
              onSelectionChange={handleSelectionChange}
            />
          ) : (
            <div
              className="p-4 markdown-body text-sm text-slate-200 max-w-none overflow-auto"
              dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
            />
          )
        ) : activePart.type === "flowchart" ? (
          <Suspense fallback={<div className="flex items-center justify-center h-full text-slate-500"><Loader2 size={16} className="animate-spin mr-2" /> Loading flowchart...</div>}>
            <FlowchartEditor
              meta={activePart.meta || { nodes: [], edges: [] }}
              onMetaChange={(newMeta) => {
                handleSaveFlowchartMeta(newMeta);
              }}
              readOnly={false}
            />
          </Suspense>
        ) : (
          <div className="flex items-center justify-center h-full text-slate-600 text-sm">
            {activePart.type} part — editor not yet available
          </div>
        )}
      </div>
    </div>
  );
}


/* ── Minimal markdown → HTML (same as DocumentEditor) ── */

function markdownToHtml(md) {
  if (!md) return "";
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
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^#### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^---$/gm, "<hr/>")
    .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-400 underline">$1</a>');
  html = html.replace(/<\/li>\n+<li>/g, "</li><li>");
  html = html.replace(/((?:<li>[\s\S]*?<\/li>)+)/g, "<ul>$1</ul>");
  html = html
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br/>");
  return `<p>${html}</p>`;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
