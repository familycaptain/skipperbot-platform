import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Wrench, Loader2, RefreshCw, ChevronRight, BookOpen, Tag,
  FileText, Box, X,
} from "lucide-react";

/**
 * Tools Browser App — singleton for viewing tool categories and guides.
 *
 * Props: appId, userId, context, onTitle, refreshKey
 */

export default function ToolsApp({ appId, userId, onTitle, refreshKey }) {
  const [categories, setCategories] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedCat, setSelectedCat] = useState(null);
  const [guide, setGuide] = useState(null);
  const [guideLoading, setGuideLoading] = useState(false);

  useEffect(() => { onTitle?.("Tools"); }, []);

  const loadCategories = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/apps/tools/categories");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setCategories(data.categories || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadCategories(); }, []);
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadCategories();
  }, [refreshKey]);

  const loadGuide = useCallback(async (guideName) => {
    if (!guideName) { setGuide(null); return; }
    setGuideLoading(true);
    try {
      const res = await fetch(`/api/apps/tools/guide/${encodeURIComponent(guideName)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setGuide(data.content || "");
    } catch {
      setGuide("__GUIDE_LOAD_ERROR__");
    } finally {
      setGuideLoading(false);
    }
  }, []);

  function handleSelectCategory(cat) {
    setSelectedCat(cat);
    setGuide(null);
    if (cat.guide) loadGuide(cat.guide);
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <div className="flex items-center gap-1.5 text-sm text-default">
          <Wrench size={14} className="text-faint" />
          <span className="text-default">Tools</span>
          {categories && (
            <span className="text-xs text-faint ml-1">
              {categories.length} categories · {categories.reduce((n, c) => n + c.tools.length, 0)} tools
            </span>
          )}
        </div>
        <button
          onClick={() => { loadCategories(); setSelectedCat(null); setGuide(null); }}
          disabled={loading}
          className="p-1 rounded icon-btn transition-colors"
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="px-3 py-1.5 bg-red-900/30 border-b border-red-800/50 text-xs text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-[var(--ds-text)]"><X size={12} /></button>
        </div>
      )}

      {/* Main content: sidebar + detail */}
      <div className="flex-1 min-h-0 flex">
        {/* Sidebar — Category list */}
        <div className="w-56 shrink-0 border-r border-subtle overflow-y-auto surface-panel">
          {loading && !categories ? (
            <div className="flex items-center justify-center h-32 text-muted">
              <Loader2 size={16} className="animate-spin mr-2" /> Loading...
            </div>
          ) : categories && categories.length > 0 ? (
            <div className="py-1">
              {categories.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => handleSelectCategory(cat)}
                  className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-colors ${
                    selectedCat?.id === cat.id
                      ? "bg-indigo-600/20 border-l-2 border-indigo-500 text-indigo-300"
                      : "border-l-2 border-transparent text-muted hover:bg-[var(--ds-card)] hover:text-[var(--ds-text)]"
                  }`}
                >
                  <CategoryIcon catId={cat.id} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium truncate capitalize">{cat.id.replace(/_/g, " ")}</div>
                    <div className="text-[10px] text-faint">{cat.tools.length} tools</div>
                  </div>
                  {cat.guide && <BookOpen size={10} className="text-faint shrink-0" />}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-faint text-xs">
              No categories
            </div>
          )}
        </div>

        {/* Detail panel */}
        <div className="flex-1 min-w-0 overflow-y-auto">
          {selectedCat ? (
            <CategoryDetail cat={selectedCat} guide={guide} guideLoading={guideLoading} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-faint">
              <Wrench size={32} className="text-faint mb-2" />
              <p className="text-sm">Select a category to view its tools</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Category Detail Panel ── */

function CategoryDetail({ cat, guide, guideLoading }) {
  const [showGuide, setShowGuide] = useState(true);

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-default capitalize flex items-center gap-2">
          <CategoryIcon catId={cat.id} size={18} />
          {cat.id.replace(/_/g, " ")}
        </h2>
        <p className="text-sm text-muted mt-1">{cat.description}</p>
      </div>

      {/* Tools list */}
      <div>
        <h3 className="text-xs font-semibold text-faint uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <Box size={12} />
          Tools ({cat.tools.length})
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {cat.tools.map((tool) => (
            <div
              key={tool}
              className="px-3 py-2 rounded-lg surface-card border border-subtle text-sm text-default font-mono"
            >
              {tool}
            </div>
          ))}
        </div>
      </div>

      {/* Keywords */}
      {cat.keywords && cat.keywords.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-faint uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Tag size={12} />
            Keywords
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {cat.keywords.map((kw) => (
              <span
                key={kw}
                className="px-2 py-0.5 rounded-full surface-card border border-subtle text-[11px] text-muted"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Guide */}
      {cat.guide && (
        <div>
          <button
            onClick={() => setShowGuide(!showGuide)}
            className="flex items-center gap-1.5 text-xs font-semibold text-faint uppercase tracking-wider mb-2 hover:text-[var(--ds-text)] transition-colors"
          >
            <BookOpen size={12} />
            Guide
            <ChevronRight size={12} className={`transition-transform ${showGuide ? "rotate-90" : ""}`} />
          </button>
          {showGuide && (
            <div className="rounded-lg surface-card border border-subtle p-4 overflow-x-auto">
              {guideLoading ? (
                <div className="flex items-center text-muted text-sm">
                  <Loader2 size={14} className="animate-spin mr-2" /> Loading guide...
                </div>
              ) : guide === "__GUIDE_LOAD_ERROR__" ? (
                <p className="text-sm text-amber-400/80 italic">This guide could not be loaded.</p>
              ) : guide ? (
                <div className="prose prose-invert prose-sm max-w-none
                  prose-headings:text-[var(--ds-text)] prose-p:text-[var(--ds-text)]
                  prose-strong:text-[var(--ds-text)] prose-code:text-indigo-300
                  prose-code:bg-[var(--ds-raised)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded
                  prose-pre:bg-[var(--ds-panel)] prose-pre:border prose-pre:border-[var(--ds-border)]
                  prose-a:text-indigo-400 prose-li:text-[var(--ds-text)]
                  prose-th:text-[var(--ds-text)] prose-td:text-[var(--ds-muted)]
                  prose-hr:border-[var(--ds-border)]">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{guide}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-sm text-faint italic">No guide content</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Category Icon Helper ── */

const CATEGORY_ICONS = {
  core: "🧠",
  filesystem: "📁",
  web: "🌐",
  knowledge: "📚",
  system: "⚙️",
  utility: "🔧",
  messaging: "💬",
  reminders: "⏰",
  goals: "🎯",
  lists: "📋",
  notifications: "🔔",
  jobs: "⚡",
  artifacts: "📎",
  printing: "🖨️",
  research: "🔬",
  docs: "📝",
  user_guide: "❓",
  finance: "📈",
  recipes: "🍳",
  links: "🔗",
};

function CategoryIcon({ catId, size = 14 }) {
  const emoji = CATEGORY_ICONS[catId];
  if (emoji) {
    return <span style={{ fontSize: size * 0.85 }}>{emoji}</span>;
  }
  return <Wrench size={size} className="text-faint" />;
}
