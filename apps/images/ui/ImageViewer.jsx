import { useState, useEffect } from "react";
import { Loader2, Edit3, Save, Trash2, Image as ImageIcon } from "lucide-react";

/**
 * Image Viewer — multi-instance app for viewing a single image.
 * Opened with context: { imageId, title? }
 *
 * Props: appId, userId, context, onTitle, onOpenApp
 */
export default function ImageViewer({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const [image, setImage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const imageId = context.imageId || null;

  useEffect(() => {
    if (!imageId) return;
    setLoading(true);
    fetch(`/api/apps/images/${imageId}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && !data.error) {
          setImage(data);
          onTitle?.(data.title || data.filename || "Image");
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [imageId]);

  async function handleRenameTitle(title) {
    if (!imageId || !title.trim()) { setEditingTitle(false); return; }
    try {
      await fetch(`/api/apps/images/${imageId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() }),
      });
      setImage(prev => ({ ...prev, title: title.trim() }));
      onTitle?.(title.trim());
    } catch {}
    setEditingTitle(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted">
        <Loader2 size={18} className="animate-spin mr-2" /> Loading image...
      </div>
    );
  }

  if (!image) {
    return (
      <div className="flex items-center justify-center h-full text-faint text-sm">
        <ImageIcon size={24} className="mr-2 opacity-40" /> Image not found.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <div className="flex items-center gap-2 text-sm text-default min-w-0">
          <ImageIcon size={14} className="text-faint shrink-0" />
          {editingTitle ? (
            <form onSubmit={(e) => { e.preventDefault(); handleRenameTitle(titleDraft); }} className="flex items-center gap-1">
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => handleRenameTitle(titleDraft)}
                onKeyDown={(e) => { if (e.key === "Escape") setEditingTitle(false); }}
                className="surface-card text-sm px-1.5 py-0.5 rounded border border-subtle outline-none w-48"
              />
            </form>
          ) : (
            <button onClick={() => { setTitleDraft(image.title || image.filename || ""); setEditingTitle(true); }}
              className="truncate hover:text-[var(--ds-text)] transition-colors" title="Click to rename">
              {image.title || image.filename || "Untitled"}
            </button>
          )}
        </div>
      </div>

      {/* Image */}
      <div className="flex-1 flex items-center justify-center surface-page p-4 overflow-auto">
        <img
          src={`/${image.storage_path}`}
          alt={image.title || image.filename}
          className="max-w-full max-h-full object-contain rounded shadow-lg"
        />
      </div>
    </div>
  );
}
