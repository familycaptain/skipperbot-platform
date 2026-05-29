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
      setGuide("_Failed to load guide._");
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
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-1.5 text-sm text-slate-300">
          <Wrench size={14} className="text-slate-500" />
          <span className="text-slate-200">Tools</span>
          {categories && (
            <span className="text-xs text-slate-500 ml-1">
              {categories.length} categories · {categories.reduce((n, c) => n + c.tools.length, 0)} tools
            </span>
          )}
        </div>
        <button
          onClick={() => { loadCategories(); setSelectedCat(null); setGuide(null); }}
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

      {/* Main content: sidebar + detail */}
      <div className="flex-1 min-h-0 flex">
        {/* Sidebar — Category list */}
        <div className="w-56 shrink-0 border-r border-slate-800 overflow-y-auto bg-slate-900/20">
          {loading && !categories ? (
            <div className="flex items-center justify-center h-32 text-slate-400">
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
                      : "border-l-2 border-transparent text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                  }`}
                >
                  <CategoryIcon catId={cat.id} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium truncate capitalize">{cat.id.replace(/_/g, " ")}</div>
                    <div className="text-[10px] text-slate-500">{cat.tools.length} tools</div>
                  </div>
                  {cat.guide && <BookOpen size={10} className="text-slate-600 shrink-0" />}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-slate-500 text-xs">
              No categories
            </div>
          )}
        </div>

        {/* Detail panel */}
        <div className="flex-1 min-w-0 overflow-y-auto">
          {selectedCat ? (
            <CategoryDetail cat={selectedCat} guide={guide} guideLoading={guideLoading} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-slate-500">
              <Wrench size={32} className="text-slate-600 mb-2" />
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
        <h2 className="text-lg font-semibold text-slate-100 capitalize flex items-center gap-2">
          <CategoryIcon catId={cat.id} size={18} />
          {cat.id.replace(/_/g, " ")}
        </h2>
        <p className="text-sm text-slate-400 mt-1">{cat.description}</p>
      </div>

      {/* Tools list */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <Box size={12} />
          Tools ({cat.tools.length})
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {cat.tools.map((tool) => (
            <div
              key={tool}
              className="px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700/40 text-sm text-slate-300 font-mono"
            >
              {tool}
            </div>
          ))}
        </div>
      </div>

      {/* Keywords */}
      {cat.keywords && cat.keywords.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Tag size={12} />
            Keywords
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {cat.keywords.map((kw) => (
              <span
                key={kw}
                className="px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700/40 text-[11px] text-slate-400"
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
            className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 hover:text-slate-300 transition-colors"
          >
            <BookOpen size={12} />
            Guide: {cat.guide}
            <ChevronRight size={12} className={`transition-transform ${showGuide ? "rotate-90" : ""}`} />
          </button>
          {showGuide && (
            <div className="rounded-lg bg-slate-800/40 border border-slate-700/40 p-4 overflow-x-auto">
              {guideLoading ? (
                <div className="flex items-center text-slate-400 text-sm">
                  <Loader2 size={14} className="animate-spin mr-2" /> Loading guide...
                </div>
              ) : guide ? (
                <div className="prose prose-invert prose-sm max-w-none
                  prose-headings:text-slate-200 prose-p:text-slate-300
                  prose-strong:text-slate-200 prose-code:text-indigo-300
                  prose-code:bg-slate-700/50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded
                  prose-pre:bg-slate-900/60 prose-pre:border prose-pre:border-slate-700/50
                  prose-a:text-indigo-400 prose-li:text-slate-300
                  prose-th:text-slate-300 prose-td:text-slate-400
                  prose-hr:border-slate-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{guide}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-sm text-slate-500 italic">No guide content</p>
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
  return <Wrench size={size} className="text-slate-500" />;
}
