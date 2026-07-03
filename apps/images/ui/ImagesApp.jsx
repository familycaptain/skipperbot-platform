import { useState, useEffect } from "react";
import { Image as ImageIcon, Loader2, RefreshCw, Trash2 } from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

/**
 * Images App — singleton list/gallery view of all saved images.
 * Clicking an image opens it in a new Image Viewer tab.
 *
 * Props: appId, userId, context, onTitle, onOpenApp
 */
export default function ImagesApp({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    onTitle?.("Images");
    loadImages();
  }, []);

  async function loadImages() {
    setLoading(true);
    try {
      const res = await fetch("/api/apps/images");
      if (res.ok) {
        const data = await res.json();
        setImages(Array.isArray(data) ? data : []);
      }
    } catch {}
    setLoading(false);
  }

  async function handleDelete(id, e) {
    e.stopPropagation();
    if (!confirm("Delete this image?")) return;
    try {
      await fetch(`/api/apps/images/${id}`, { method: "DELETE" });
      setImages(prev => prev.filter(img => img.id !== id));
    } catch {}
  }

  function handleOpen(img) {
    onOpenApp?.("image", { imageId: img.id, title: img.title || img.filename });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted">
        <Loader2 size={18} className="animate-spin mr-2" /> Loading images...
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-subtle shrink-0">
        <div className="flex items-center gap-2">
          <ImageIcon size={16} className="text-muted" />
          <span className="text-sm font-medium text-default">Images</span>
          <span className="text-xs text-faint">({images.length})</span>
        </div>
        <button
          onClick={loadImages}
          title="Refresh"
          className="text-faint hover:text-[var(--ds-text)] transition-colors"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Gallery grid */}
      <div className="flex-1 overflow-y-auto p-4">
        {images.length === 0 ? (
          <PristineEmpty
            appId="images"
            blurb={getAppManifest("images")?.blurb}
            records={images}
            loading={loading}
            filterActive={false}
            fallback={
              <div className="flex flex-col items-center justify-center h-full text-faint gap-3">
                <ImageIcon size={40} className="opacity-20" />
                <p className="text-sm">No images yet.</p>
                <p className="text-xs text-faint text-center max-w-[220px] leading-relaxed">
                  Ask Skipper to generate a chart — e.g. "show me a chart of SPY"
                </p>
              </div>
            }
          />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {images.map(img => (
              <div
                key={img.id}
                onClick={() => handleOpen(img)}
                className="group relative surface-panel border border-subtle rounded-lg overflow-hidden cursor-pointer hover:border-[var(--ds-border)] hover:bg-[var(--ds-card)] transition-all"
              >
                {/* Thumbnail */}
                <div className="aspect-video surface-page flex items-center justify-center overflow-hidden">
                  <img
                    src={`/${img.storage_path}`}
                    alt={img.title || img.filename}
                    className="w-full h-full object-cover"
                    onError={(e) => {
                      e.target.style.display = "none";
                      e.target.parentNode.innerHTML =
                        '<div class="flex items-center justify-center h-full w-full text-default"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></div>';
                    }}
                  />
                </div>

                {/* Caption */}
                <div className="p-2 flex items-start justify-between gap-1">
                  <div className="min-w-0">
                    <p className="text-xs text-default truncate font-medium leading-snug">
                      {img.title || img.filename || img.id}
                    </p>
                    <p className="text-[10px] text-faint mt-0.5">
                      {img.created_at
                        ? new Date(img.created_at).toLocaleDateString(undefined, {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                          })
                        : ""}
                    </p>
                  </div>
                  <button
                    onClick={(e) => handleDelete(img.id, e)}
                    className="opacity-0 group-hover:opacity-100 text-faint hover:text-red-400 transition-all shrink-0 p-0.5 mt-0.5"
                    title="Delete"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
