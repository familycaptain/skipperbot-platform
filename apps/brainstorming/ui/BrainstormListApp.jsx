import { useState, useEffect, useCallback } from "react";
import {
  Search, Plus, Lightbulb, Loader2, X, Filter,
  Sparkles, ParkingCircle, GraduationCap, Pencil,
} from "lucide-react";
import PristineEmpty from "../../../web/src/components/PristineEmpty";
import { getAppManifest } from "../../../web/src/apps/registry";

const STATUS_OPTIONS = ["idea", "exploring", "developing", "parked", "graduated"];
const PRIORITY_OPTIONS = ["high", "medium", "low"];

const STATUS_COLORS = {
  idea: "bg-[var(--ds-accent)] text-accent border-subtle",
  exploring: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  developing: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  parked: "surface-raised text-muted border-subtle",
  graduated: "bg-purple-500/20 text-purple-400 border-purple-500/30",
};

const PRIORITY_DOTS = {
  high: "bg-red-400",
  medium: "bg-amber-400",
  low: "surface-raised",
};

export default function BrainstormListApp({ appId, userId, context = {}, refreshKey, isActive, onOpenApp }) {
  const [ideas, setIdeas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showNew, setShowNew] = useState(false);

  const fetchIdeas = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      if (searchQuery) params.set("q", searchQuery);
      const res = await fetch(`/api/apps/brainstorming?${params}`);
      if (res.ok) setIdeas(await res.json());
    } catch {} finally {
      setLoading(false);
    }
  }, [statusFilter, searchQuery]);

  useEffect(() => { fetchIdeas(); }, [fetchIdeas, refreshKey]);

  function openIdea(idea) {
    onOpenApp?.("brainstorm", { ideaId: idea.id, title: idea.title });
  }

  async function handleCreate(title, summary, priority, tags) {
    try {
      const res = await fetch("/api/apps/brainstorming", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, summary, priority, tags, created_by: userId }),
      });
      if (res.ok) {
        const idea = await res.json();
        setShowNew(false);
        fetchIdeas();
        openIdea(idea);
      }
    } catch {}
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <Lightbulb size={14} className="text-amber-400 shrink-0" />
        <span className="text-sm font-medium text-default">Ideas</span>
        <div className="flex-1" />
        <div className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search ideas..."
            className="surface-card text-xs text-default pl-7 pr-2 py-1 rounded border border-subtle outline-none w-44 focus:border-amber-600"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-faint hover:text-[var(--ds-text)]">
              <X size={10} />
            </button>
          )}
        </div>
        <button
          onClick={() => setShowNew(!showNew)}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-amber-600/80 hover:bg-amber-500 text-on-accent transition-colors"
        >
          <Plus size={12} />
          New Idea
        </button>
      </div>

      {/* Status filter tabs */}
      <div className="flex items-center gap-1 px-3 py-1.5 surface-panel border-b border-subtle shrink-0 overflow-x-auto">
        <button
          onClick={() => setStatusFilter("")}
          className={`px-2 py-0.5 rounded text-[11px] transition-colors ${!statusFilter ? "surface-raised text-default" : "text-faint hover:text-[var(--ds-text)]"}`}
        >
          All
        </button>
        {STATUS_OPTIONS.filter(s => s !== "graduated").map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(statusFilter === s ? "" : s)}
            className={`px-2 py-0.5 rounded text-[11px] capitalize transition-colors ${statusFilter === s ? "surface-raised text-default" : "text-faint hover:text-[var(--ds-text)]"}`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* New Idea Form */}
      {showNew && (
        <NewIdeaForm onSubmit={handleCreate} onCancel={() => setShowNew(false)} />
      )}

      {/* Idea list */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-faint">
            <Loader2 size={16} className="animate-spin mr-2" /> Loading ideas...
          </div>
        ) : ideas.length === 0 ? (
          <PristineEmpty
            appId="brainstorming"
            blurb={getAppManifest("brainstorming")?.blurb}
            records={ideas}
            loading={loading}
            filterActive={!!searchQuery || !!statusFilter}
            fallback={
              <div className="text-center py-8 text-faint text-sm">
                No ideas match your filters.
              </div>
            }
          />
        ) : (
          ideas.map((idea) => (
            <IdeaCard key={idea.id} idea={idea} onClick={() => openIdea(idea)} />
          ))
        )}
      </div>
    </div>
  );
}


function IdeaCard({ idea, onClick }) {
  const statusClass = STATUS_COLORS[idea.status] || STATUS_COLORS.idea;
  const priorityDot = PRIORITY_DOTS[idea.priority] || PRIORITY_DOTS.medium;

  return (
    <button
      onClick={onClick}
      className="w-full text-left p-3 rounded-lg surface-card hover:bg-[var(--ds-card)] border border-subtle hover:border-amber-700/30 transition-all group"
    >
      <div className="flex items-start gap-2">
        <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${priorityDot}`} title={idea.priority} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-sm font-medium text-default group-hover:text-[var(--ds-text)] truncate">
              {idea.title}
            </span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${statusClass} capitalize shrink-0`}>
              {idea.status}
            </span>
          </div>
          {idea.summary && (
            <p className="text-xs text-faint line-clamp-2 mb-1">{idea.summary}</p>
          )}
          <div className="flex items-center gap-2 text-[10px] text-faint">
            {idea.tags?.length > 0 && (
              <span className="flex items-center gap-1">
                {idea.tags.map((t) => (
                  <span key={t} className="px-1 py-0 surface-raised rounded text-faint">{t}</span>
                ))}
              </span>
            )}
            {idea.part_count > 1 && (
              <span>{idea.part_count} parts</span>
            )}
            <span className="ml-auto">{fmtRelative(idea.updated_at)}</span>
          </div>
        </div>
      </div>
    </button>
  );
}


function NewIdeaForm({ onSubmit, onCancel }) {
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [priority, setPriority] = useState("medium");

  function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit(title.trim(), summary.trim(), priority, []);
  }

  return (
    <form onSubmit={handleSubmit} className="px-3 py-2 bg-amber-950/20 border-b border-amber-900/30 space-y-2">
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Idea title..."
        className="w-full surface-card text-sm text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-amber-600"
      />
      <input
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        placeholder="Brief summary (optional)..."
        className="w-full surface-card text-xs text-default px-3 py-1.5 rounded border border-subtle outline-none focus:border-amber-600"
      />
      <div className="flex items-center gap-2">
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          className="surface-card text-xs text-default px-2 py-1 rounded border border-subtle outline-none"
        >
          {PRIORITY_OPTIONS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <div className="flex-1" />
        <button type="button" onClick={onCancel} className="px-3 py-1 rounded text-xs text-muted hover:text-[var(--ds-text)] transition-colors">
          Cancel
        </button>
        <button
          type="submit"
          disabled={!title.trim()}
          className="px-3 py-1 rounded text-xs bg-amber-600 text-on-accent hover:bg-amber-500 disabled:opacity-30 transition-colors"
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
