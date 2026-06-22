import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search, Plus, Loader2, Trash2, Edit3, Save, X, Pin, PinOff,
  Tag, Calendar, User, ChevronDown, Image as ImageIcon, Send,
  ArrowUp, Filter, Upload, ChevronLeft, ChevronRight, GripVertical,
  MessageSquare, Maximize2, Users, Activity, RefreshCw,
} from "lucide-react";

/** Upload a File/Blob to the images API. Returns the image ID or null. */
async function uploadImageFile(file, userId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("uploaded_by", userId);
  formData.append("title", "Timeline photo");
  const res = await fetch("/api/apps/images/upload", { method: "POST", body: formData });
  if (!res.ok) throw new Error("Upload failed");
  const data = await res.json();
  return data.id || null;
}

/** Hook: listen for paste events containing images. */
function usePasteImage(ref, onImage) {
  useEffect(() => {
    const el = ref?.current || document;
    function handlePaste(e) {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          e.preventDefault();
          const file = item.getAsFile();
          if (file) onImage(file);
          return;
        }
      }
    }
    el.addEventListener("paste", handlePaste);
    return () => el.removeEventListener("paste", handlePaste);
  }, [ref, onImage]);
}

const IMG_URL = (id) => `/api/apps/images/${id}/file`;

/**
 * Timeline App — Family Journal / Microblog
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 */

const API = "/api/apps/timeline";
const PAGE_SIZE = 20;

// ═══════════════════════════════════════════════════════════════════════════
//  Main App
// ═══════════════════════════════════════════════════════════════════════════

export default function TimelineApp({ appId, userId, onTitle, refreshKey }) {
  const [posts, setPosts] = useState([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offset, setOffset] = useState(0);

  // Feed mode: "family" = everyone posts | "activity" = personal activity log
  const [feedMode, setFeedMode] = useState("family");
  const [activityAuthor, setActivityAuthor] = useState(userId || "");
  const [showActivityAuthorDropdown, setShowActivityAuthorDropdown] = useState(false);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [authorFilter, setAuthorFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [showAuthorDropdown, setShowAuthorDropdown] = useState(false);
  const [allTags, setAllTags] = useState([]);
  const [allAuthors, setAllAuthors] = useState([]);

  // Composer
  const [showComposer, setShowComposer] = useState(false);
  const [editingPost, setEditingPost] = useState(null);

  // Scroll
  const feedRef = useRef(null);
  const sentinelRef = useRef(null);

  useEffect(() => { if (onTitle) onTitle("Timeline"); }, [onTitle]);

  // ── Load feed ──────────────────────────────────────────────────────────

  const loadFeed = useCallback(async (reset = true) => {
    if (reset) setLoading(true);
    else setLoadingMore(true);

    const newOffset = reset ? 0 : offset;
    try {
      const params = new URLSearchParams({ limit: PAGE_SIZE, offset: newOffset });
      if (feedMode === "activity") {
        params.set("visibility", "personal");
        params.set("author", activityAuthor || userId || "");
      } else {
        params.set("visibility", "everyone");
        if (authorFilter) params.set("author", authorFilter);
      }
      if (tagFilter) params.set("tag", tagFilter);
      if (activeSearch) params.set("search", activeSearch);
      if (dateFilter) {
        // Show posts from the selected date onward (jump to that day)
        params.set("after", new Date(dateFilter + "T00:00:00").toISOString());
        const nextDay = new Date(dateFilter + "T00:00:00");
        nextDay.setDate(nextDay.getDate() + 1);
        params.set("before", nextDay.toISOString());
      }

      const res = await fetch(`${API}?${params}`);
      const data = await res.json();

      if (reset) {
        setPosts(data.posts || []);
        setOffset(PAGE_SIZE);
      } else {
        setPosts(prev => [...prev, ...(data.posts || [])]);
        setOffset(newOffset + PAGE_SIZE);
      }
      setTotal(data.total || 0);
      setHasMore(data.has_more || false);
    } catch (e) {
      console.error("Failed to load timeline:", e);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [feedMode, activityAuthor, tagFilter, authorFilter, activeSearch, dateFilter, offset]);

  const loadTags = useCallback(async () => {
    try {
      const res = await fetch(`${API}/tags`);
      const data = await res.json();
      setAllTags(data.tags || []);
    } catch (e) {
      console.error("Failed to load tags:", e);
    }
  }, []);

  const loadAuthors = useCallback(async () => {
    try {
      const res = await fetch(`${API}/authors`);
      const data = await res.json();
      setAllAuthors(data.authors || []);
    } catch (e) {
      console.error("Failed to load authors:", e);
    }
  }, []);

  useEffect(() => { loadFeed(true); loadTags(); loadAuthors(); }, [feedMode, activityAuthor, tagFilter, authorFilter, activeSearch, dateFilter, refreshKey]);

  // ── Infinite scroll via IntersectionObserver ───────────────────────────

  useEffect(() => {
    if (!sentinelRef.current || !hasMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          loadFeed(false);
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, loading, loadFeed]);

  // ── Search ─────────────────────────────────────────────────────────────

  const handleSearch = (e) => {
    e.preventDefault();
    setActiveSearch(searchQuery.trim());
  };

  const clearSearch = () => {
    setSearchQuery("");
    setActiveSearch("");
  };

  // ── CRUD handlers ──────────────────────────────────────────────────────

  const handleDelete = async (postId) => {
    if (!confirm("Delete this post?")) return;
    try {
      await fetch(`${API}/${postId}`, { method: "DELETE" });
      loadFeed(true);
    } catch (e) {
      console.error("Delete failed:", e);
    }
  };

  const handlePin = async (postId) => {
    try {
      await fetch(`${API}/${postId}/pin`, { method: "PATCH" });
      loadFeed(true);
    } catch (e) {
      console.error("Pin toggle failed:", e);
    }
  };

  const handleEdit = (post) => {
    setEditingPost(post);
    setShowComposer(true);
  };

  const handleComposerDone = () => {
    setShowComposer(false);
    setEditingPost(null);
    loadFeed(true);
    loadTags();
  };

  const scrollToTop = () => {
    feedRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full w-full surface-page text-default">
      {/* ── Toolbar ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-subtle surface-panel flex-wrap">

        {/* Feed mode toggle */}
        <div className="flex items-center rounded overflow-hidden border border-subtle flex-shrink-0">
          <button
            onClick={() => setFeedMode("family")}
            title="Family feed — shared posts visible to everyone"
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
              feedMode === "family"
                ? "bg-violet-600 text-on-accent"
                : "surface-card text-muted hover:text-[var(--ds-text)]"
            }`}
          >
            <Users size={12} /> Family
          </button>
          <button
            onClick={() => setFeedMode("activity")}
            title="Personal activity log — auto-logged CRUD events"
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors border-l border-subtle ${
              feedMode === "activity"
                ? "bg-emerald-700 text-on-accent"
                : "surface-card text-muted hover:text-[var(--ds-text)]"
            }`}
          >
            <Activity size={12} /> Activity
          </button>
        </div>

        {/* Activity mode: whose log? */}
        {feedMode === "activity" && (
          <div className="relative flex-shrink-0">
            <button
              onClick={() => { setShowActivityAuthorDropdown(!showActivityAuthorDropdown); setShowTagDropdown(false); setShowAuthorDropdown(false); }}
              className="flex items-center gap-1 px-2 py-1.5 text-xs rounded border border-emerald-600 bg-emerald-700/20 text-emerald-300 hover:border-emerald-400"
            >
              <User size={12} />
              <span className="capitalize">{activityAuthor || "Select person"}</span>
              <ChevronDown size={12} />
            </button>
            {showActivityAuthorDropdown && (
              <div className="absolute left-0 top-full mt-1 w-40 surface-card border border-subtle rounded shadow-xl z-50 max-h-60 overflow-y-auto">
                {userId && (
                  <button
                    onClick={() => { setActivityAuthor(userId); setShowActivityAuthorDropdown(false); }}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--ds-raised)] capitalize ${
                      activityAuthor === userId ? "text-emerald-300 bg-emerald-700/10" : "text-default"
                    }`}
                  >
                    {userId} (me)
                  </button>
                )}
                {allAuthors.filter(a => a.author_id !== userId).map(a => (
                  <button
                    key={a.author_id}
                    onClick={() => { setActivityAuthor(a.author_id); setShowActivityAuthorDropdown(false); }}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--ds-raised)] capitalize ${
                      activityAuthor === a.author_id ? "text-emerald-300 bg-emerald-700/10" : "text-default"
                    }`}
                  >
                    {a.author_id}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Search */}
        <form onSubmit={handleSearch} className="flex items-center gap-1 flex-1 min-w-[180px]">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
            <input
              type="text"
              placeholder="Search posts…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-7 pr-2 py-1.5 text-xs rounded surface-card border border-subtle text-default placeholder-gray-500 focus:outline-none focus:border-violet-500"
            />
          </div>
          {activeSearch && (
            <button onClick={clearSearch} className="text-faint hover:text-[var(--ds-text)]" title="Clear search">
              <X size={14} />
            </button>
          )}
        </form>

        {/* Tag filter */}
        <div className="relative">
          <button
            onClick={() => { setShowTagDropdown(!showTagDropdown); }}
            className={`flex items-center gap-1 px-2 py-1.5 text-xs rounded border ${
              tagFilter ? "border-violet-500 bg-violet-500/20 text-violet-300" : "border-subtle surface-card text-muted"
            } hover:border-[var(--ds-border)]`}
          >
            <Tag size={12} />
            {tagFilter ? `#${tagFilter}` : "Tags"}
            <ChevronDown size={12} />
          </button>
          {showTagDropdown && (
            <div className="absolute right-0 top-full mt-1 w-48 surface-card border border-subtle rounded shadow-xl z-50 max-h-60 overflow-y-auto">
              <button
                onClick={() => { setTagFilter(""); setShowTagDropdown(false); }}
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--ds-raised)] text-muted"
              >
                All tags
              </button>
              {allTags.map(t => (
                <button
                  key={t.tag}
                  onClick={() => { setTagFilter(t.tag); setShowTagDropdown(false); }}
                  className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--ds-raised)] ${
                    tagFilter === t.tag ? "text-violet-300 bg-violet-500/10" : "text-default"
                  }`}
                >
                  #{t.tag} <span className="text-faint ml-1">({t.post_count})</span>
                </button>
              ))}
              {allTags.length === 0 && (
                <div className="px-3 py-2 text-xs text-faint">No tags yet</div>
              )}
            </div>
          )}
        </div>

        {/* Author filter — family mode only */}
        {feedMode === "family" && <div className="relative">
          <button
            onClick={() => { setShowAuthorDropdown(!showAuthorDropdown); }}
            className={`flex items-center gap-1 px-2 py-1.5 text-xs rounded border ${
              authorFilter ? "border-blue-500 bg-blue-500/20 text-blue-300" : "border-subtle surface-card text-muted"
            } hover:border-[var(--ds-border)]`}
          >
            <User size={12} />
            {authorFilter ? authorFilter : "Author"}
            <ChevronDown size={12} />
          </button>
          {showAuthorDropdown && (
            <div className="absolute right-0 top-full mt-1 w-48 surface-card border border-subtle rounded shadow-xl z-50 max-h-60 overflow-y-auto">
              <button
                onClick={() => { setAuthorFilter(""); setShowAuthorDropdown(false); }}
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--ds-raised)] text-muted"
              >
                All authors
              </button>
              {allAuthors.map(a => (
                <button
                  key={a.author_id}
                  onClick={() => { setAuthorFilter(a.author_id); setShowAuthorDropdown(false); }}
                  className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--ds-raised)] capitalize ${
                    authorFilter === a.author_id ? "text-blue-300 bg-blue-500/10" : "text-default"
                  }`}
                >
                  {a.author_id} <span className="text-faint ml-1">({a.post_count})</span>
                </button>
              ))}
            </div>
          )}
        </div>}

        {/* Date filter */}
        <div className="relative">
          <input
            type="date"
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="px-2 py-1.5 text-xs rounded border border-subtle surface-card text-muted hover:border-[var(--ds-border)] focus:outline-none focus:border-violet-500"
            title="Jump to date"
          />
        </div>

        {/* Post count */}
        <span className="text-xs text-faint">
          {total} {feedMode === "activity" ? `entr${total !== 1 ? "ies" : "y"}` : `post${total !== 1 ? "s" : ""}`}
        </span>

        {/* Refresh */}
        <button
          onClick={() => loadFeed(true)}
          disabled={loading}
          className="p-1.5 rounded border border-subtle surface-card text-muted hover:text-[var(--ds-text)] hover:border-[var(--ds-border)] disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>

        {/* New Post — family mode only */}
        {feedMode === "family" && (
          <button
            onClick={() => { setEditingPost(null); setShowComposer(true); }}
            className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-violet-600 hover:bg-violet-500 text-on-accent font-medium"
          >
            <Plus size={14} /> New Post
          </button>
        )}
      </div>

      {/* Close dropdowns on outside click */}
      {(showTagDropdown || showAuthorDropdown || showActivityAuthorDropdown) && (
        <div className="fixed inset-0 z-40" onClick={() => { setShowTagDropdown(false); setShowAuthorDropdown(false); setShowActivityAuthorDropdown(false); }} />
      )}

      {/* ── Active filters bar ─────────────────────────────────────── */}
      {(activeSearch || tagFilter || authorFilter || dateFilter) && (
        <div className="flex items-center gap-2 px-4 py-1.5 surface-panel border-b border-subtle text-xs">
          <Filter size={12} className="text-faint" />
          {activeSearch && (
            <span className="surface-card px-2 py-0.5 rounded text-default">
              Search: "{activeSearch}"
              <button onClick={clearSearch} className="ml-1 text-faint hover:text-[var(--ds-text)]">×</button>
            </span>
          )}
          {tagFilter && (
            <span className="bg-violet-500/20 px-2 py-0.5 rounded text-violet-300">
              #{tagFilter}
              <button onClick={() => setTagFilter("")} className="ml-1 text-violet-400 hover:text-violet-200">×</button>
            </span>
          )}
          {authorFilter && (
            <span className="bg-blue-500/20 px-2 py-0.5 rounded text-blue-300 capitalize">
              {authorFilter}
              <button onClick={() => setAuthorFilter("")} className="ml-1 text-blue-400 hover:text-blue-200">×</button>
            </span>
          )}
          {dateFilter && (
            <span className="bg-amber-500/20 px-2 py-0.5 rounded text-amber-300">
              {new Date(dateFilter + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
              <button onClick={() => setDateFilter("")} className="ml-1 text-amber-400 hover:text-amber-200">×</button>
            </span>
          )}
        </div>
      )}

      {/* ── Composer ───────────────────────────────────────────────── */}
      {showComposer && (
        <PostComposer
          userId={userId}
          editingPost={editingPost}
          onDone={handleComposerDone}
          onCancel={() => { setShowComposer(false); setEditingPost(null); }}
          allTags={allTags}
        />
      )}

      {/* ── Feed ───────────────────────────────────────────────────── */}
      <div ref={feedRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="animate-spin text-violet-400" size={28} />
          </div>
        ) : posts.length === 0 ? (
          <div className="text-center py-16 text-faint">
            {feedMode === "activity" ? (
              <>
                <p className="text-lg mb-2">No activity entries yet</p>
                <p className="text-sm capitalize">{activityAuthor} hasn't done anything logged yet — entries appear automatically when records are created, updated, or completed.</p>
              </>
            ) : (
              <>
                <p className="text-lg mb-2">No posts yet</p>
                <p className="text-sm">Click "New Post" to start your family journal!</p>
              </>
            )}
          </div>
        ) : (
          <>
            {posts.map(post => (
              feedMode === "activity"
                ? <ActivityCard key={post.id} post={post} />
                : <PostCard
                    key={post.id}
                    post={post}
                    onDelete={handleDelete}
                    onPin={handlePin}
                    onEdit={handleEdit}
                    onTagClick={(tag) => setTagFilter(tag)}
                  />
            ))}

            {/* Sentinel for infinite scroll */}
            <div ref={sentinelRef} className="h-4" />

            {loadingMore && (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="animate-spin text-faint" size={18} />
                <span className="ml-2 text-xs text-faint">Loading more…</span>
              </div>
            )}

            {!hasMore && posts.length > 0 && (
              <div className="text-center py-4 text-xs text-faint">
                — End of timeline —
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Scroll to top ──────────────────────────────────────────── */}
      {posts.length > 5 && (
        <button
          onClick={scrollToTop}
          className="fixed bottom-6 right-6 p-2 rounded-full surface-card border border-subtle text-muted hover:text-[var(--ds-text)] hover:border-violet-500 shadow-lg z-30"
          title="Back to top"
        >
          <ArrowUp size={16} />
        </button>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Activity Card (compact log entry for personal activity feed)
// ═══════════════════════════════════════════════════════════════════════════

const APP_COLORS = {
  auto:        "text-amber-400  bg-amber-400/10  border-amber-700/40",
  home:        "text-blue-400   bg-blue-400/10   border-blue-700/40",
  medical:     "text-rose-400   bg-rose-400/10   border-rose-700/40",
  recipes:     "text-orange-400 bg-orange-400/10 border-orange-700/40",
  meals:       "text-yellow-400 bg-yellow-400/10 border-yellow-700/40",
  goals:       "text-violet-400 bg-violet-400/10 border-violet-700/40",
  investment:  "text-emerald-400 bg-emerald-400/10 border-emerald-700/40",
  timeline:    "text-accent    bg-[var(--ds-accent)]    border-subtle",
};

function ActivityCard({ post }) {
  const timeStr = post.created_at
    ? new Date(post.created_at).toLocaleString("en-US", {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      })
    : "";

  const appColorClass = APP_COLORS[post.source_app] ||
    "text-muted surface-raised border-subtle";

  // Strip the auto-appended activity tag from display
  const displayTags = (post.tags || []).filter(t => t !== "activity");

  return (
    <div className="flex items-start gap-3 px-3 py-2.5 rounded-lg surface-panel border border-subtle hover:border-[var(--ds-border)] transition-colors">
      {/* Source app badge */}
      {post.source_app ? (
        <span className={`flex-shrink-0 mt-0.5 px-1.5 py-0.5 text-[10px] font-medium rounded border ${appColorClass}`}>
          {post.source_app}
        </span>
      ) : (
        <span className="flex-shrink-0 mt-0.5 w-2 h-2 rounded-full surface-raised mt-2" />
      )}

      {/* Title */}
      <span className="flex-1 text-sm text-default leading-snug">{post.title || post.id}</span>

      {/* Tags (excluding 'activity') */}
      {displayTags.length > 0 && (
        <div className="flex gap-1 flex-shrink-0">
          {displayTags.map(t => (
            <span key={t} className="px-1.5 py-0.5 text-[10px] rounded-full surface-card text-faint">#{t}</span>
          ))}
        </div>
      )}

      {/* Time */}
      <span className="flex-shrink-0 text-xs text-faint whitespace-nowrap">{timeStr}</span>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Post Card
// ═══════════════════════════════════════════════════════════════════════════

function PostCard({ post, onDelete, onPin, onEdit, onTagClick }) {
  const [expanded, setExpanded] = useState(false);
  const [lightboxIdx, setLightboxIdx] = useState(-1);
  const bodyPreviewLen = 2000;
  const body = post.body || "";
  const isLong = body.length > bodyPreviewLen;
  const displayBody = expanded || !isLong ? body : body.slice(0, bodyPreviewLen) + "…";
  const photos = post.photos || [];

  const dateStr = post.created_at
    ? new Date(post.created_at).toLocaleDateString("en-US", {
        weekday: "short", month: "short", day: "numeric", year: "numeric",
      })
    : "";

  const sourceIcon = post.source_app ? "🔧" : "";

  return (
    <div className="surface-panel border border-subtle rounded-lg overflow-hidden hover:border-[var(--ds-border)] transition-colors">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-subtle">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          {post.pinned && <Pin size={13} className="text-amber-400 flex-shrink-0" />}
          {sourceIcon && <span className="text-sm">{sourceIcon}</span>}
          <User size={13} className="text-faint flex-shrink-0" />
          <span className="text-xs font-medium text-default capitalize">{post.author_id || "Unknown"}</span>
          <span className="text-faint">·</span>
          <span className="text-xs text-faint">{dateStr}</span>
          {post.source_app && (
            <>
              <span className="text-faint">·</span>
              <span className="text-xs text-faint italic">via {post.source_app}</span>
            </>
          )}
        </div>
        {/* Actions */}
        <div className="flex items-center gap-1">
          <button onClick={() => onPin(post.id)} className="p-1 rounded hover:bg-[var(--ds-card)] text-faint hover:text-amber-400" title={post.pinned ? "Unpin" : "Pin"}>
            {post.pinned ? <PinOff size={13} /> : <Pin size={13} />}
          </button>
          <button onClick={() => onEdit(post)} className="p-1 rounded hover:bg-[var(--ds-card)] text-faint hover:text-blue-400" title="Edit">
            <Edit3 size={13} />
          </button>
          <button onClick={() => onDelete(post.id)} className="p-1 rounded hover:bg-[var(--ds-card)] text-faint hover:text-red-400" title="Delete">
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Title */}
      {post.title && (
        <div className="px-4 pt-2.5">
          <h3 className="text-sm font-semibold text-default">{post.title}</h3>
        </div>
      )}

      {/* Body */}
      <div className="px-4 py-2.5">
        <div
          className="markdown-body text-sm text-default max-w-none leading-relaxed"
          dangerouslySetInnerHTML={{ __html: markdownToHtml(displayBody) }}
          onClick={(e) => {
            const a = e.target.closest('a[href]');
            if (a) { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); }
          }}
        />
        {isLong && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-1 text-xs text-violet-400 hover:text-violet-300"
          >
            {expanded ? "Show less" : "Read more…"}
          </button>
        )}
      </div>

      {/* Link Previews */}
      <LinkPreviews body={body} />

      {/* Photo Carousel */}
      {photos.length > 0 && (
        <PhotoCarousel photos={photos} onClickPhoto={(idx) => setLightboxIdx(idx)} />
      )}

      {/* Tags */}
      {post.tags && post.tags.length > 0 && (
        <div className="px-4 pb-2.5 flex flex-wrap gap-1">
          {post.tags.map(tag => (
            <button
              key={tag}
              onClick={() => onTagClick(tag)}
              className="px-2 py-0.5 text-[10px] rounded-full bg-violet-500/15 text-violet-300 hover:bg-violet-500/25 transition-colors"
            >
              #{tag}
            </button>
          ))}
        </div>
      )}

      {/* Source link */}
      {post.source_label && (
        <div className="px-4 pb-2.5 text-xs text-faint">
          → {post.source_label}
        </div>
      )}

      {/* Lightbox */}
      {lightboxIdx >= 0 && (
        <Lightbox
          photos={photos}
          startIndex={lightboxIdx}
          onClose={() => setLightboxIdx(-1)}
        />
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Link Previews (OpenGraph cards for URLs in post body)
// ═══════════════════════════════════════════════════════════════════════════

function LinkPreviews({ body }) {
  const [previews, setPreviews] = useState([]);

  useEffect(() => {
    if (!body) return;
    // Extract bare URLs from body text
    const urlRegex = /https?:\/\/[^\s<]+/g;
    const urls = [...new Set((body.match(urlRegex) || []))];
    if (urls.length === 0) { setPreviews([]); return; }

    let cancelled = false;
    (async () => {
      const results = [];
      for (const url of urls.slice(0, 3)) { // max 3 previews
        try {
          const res = await fetch(`${API}/link-preview?url=${encodeURIComponent(url)}`);
          if (!res.ok) continue;
          const data = await res.json();
          if (data.title || data.description || data.image) {
            results.push(data);
          }
        } catch { /* skip */ }
      }
      if (!cancelled) setPreviews(results);
    })();
    return () => { cancelled = true; };
  }, [body]);

  if (previews.length === 0) return null;

  return (
    <div className="px-4 pb-2 space-y-2">
      {previews.map((p, i) => (
        <a
          key={i}
          href={p.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => { e.preventDefault(); window.open(p.url, '_blank', 'noopener'); }}
          className="flex items-start gap-3 p-3 rounded-lg border border-subtle surface-card hover:bg-[var(--ds-card)] hover:border-[var(--ds-border)] transition-colors cursor-pointer no-underline"
        >
          {p.image && (
            <img
              src={p.image}
              alt=""
              className="w-20 h-20 rounded object-cover flex-shrink-0 surface-raised"
              onError={(e) => { e.target.style.display = 'none'; }}
            />
          )}
          <div className="flex-1 min-w-0">
            {p.title && (
              <div className="text-sm font-medium text-default line-clamp-2 leading-snug">{p.title}</div>
            )}
            {p.description && (
              <div className="text-xs text-muted mt-1 line-clamp-2 leading-relaxed">{p.description}</div>
            )}
            {p.site_name && (
              <div className="text-[10px] text-faint mt-1">{p.site_name}</div>
            )}
          </div>
        </a>
      ))}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Photo Carousel (horizontal scroll strip on post cards)
// ═══════════════════════════════════════════════════════════════════════════

function PhotoCarousel({ photos, onClickPhoto }) {
  const scrollRef = useRef(null);
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);

  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanLeft(el.scrollLeft > 2);
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  }, []);

  useEffect(() => {
    checkScroll();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", checkScroll, { passive: true });
    const ro = new ResizeObserver(checkScroll);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", checkScroll); ro.disconnect(); };
  }, [checkScroll, photos.length]);

  return (
    <div className="relative px-4 pb-2.5 group/carousel">
      {/* Left arrow */}
      {canLeft && (
        <button
          onClick={() => scrollRef.current?.scrollBy({ left: -200, behavior: "smooth" })}
          className="absolute left-1 top-1/2 -translate-y-1/2 z-10 p-1 rounded-full surface-card border border-subtle text-default hover:text-[var(--ds-text)] opacity-0 group-hover/carousel:opacity-100 transition-opacity"
        >
          <ChevronLeft size={14} />
        </button>
      )}

      {/* Scroll strip */}
      <div
        ref={scrollRef}
        className="flex gap-2 overflow-x-auto scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent pb-1"
        style={{ scrollbarWidth: "thin" }}
      >
        {photos.map((photo, idx) => (
          <div
            key={photo.id}
            className="relative flex-shrink-0 cursor-pointer group/photo"
            onClick={() => onClickPhoto(idx)}
          >
            <img
              src={IMG_URL(photo.image_id)}
              alt={photo.caption || ""}
              className="h-28 max-w-[200px] object-cover rounded-lg border border-subtle hover:border-violet-500 transition-colors"
              loading="lazy"
            />
            {/* Expand icon overlay */}
            <div className="absolute inset-0 flex items-center justify-center bg-transparent hover:bg-[rgb(0_0_0/0.30)] rounded-lg transition-colors">
              <Maximize2 size={16} className="text-default opacity-0 group-hover/photo:opacity-80 transition-opacity" />
            </div>
            {/* Caption */}
            {photo.caption && (
              <div className="absolute bottom-0 left-0 right-0 px-2 py-1 surface-overlay rounded-b-lg">
                <span className="text-[10px] text-default line-clamp-1">{photo.caption}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Right arrow */}
      {canRight && (
        <button
          onClick={() => scrollRef.current?.scrollBy({ left: 200, behavior: "smooth" })}
          className="absolute right-1 top-1/2 -translate-y-1/2 z-10 p-1 rounded-full surface-card border border-subtle text-default hover:text-[var(--ds-text)] opacity-0 group-hover/carousel:opacity-100 transition-opacity"
        >
          <ChevronRight size={14} />
        </button>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Lightbox (full-screen image viewer with prev/next)
// ═══════════════════════════════════════════════════════════════════════════

function Lightbox({ photos, startIndex, onClose }) {
  const [idx, setIdx] = useState(startIndex);
  const photo = photos[idx];

  useEffect(() => {
    function handleKey(e) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft" && idx > 0) setIdx(idx - 1);
      if (e.key === "ArrowRight" && idx < photos.length - 1) setIdx(idx + 1);
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [idx, photos.length, onClose]);

  if (!photo) return null;

  return (
    <div
      className="fixed inset-0 z-[100] surface-overlay flex items-center justify-center"
      onClick={onClose}
    >
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-full surface-card text-default hover:text-[var(--ds-text)] z-10"
      >
        <X size={20} />
      </button>

      {/* Counter */}
      <div className="absolute top-4 left-4 text-sm text-muted">
        {idx + 1} / {photos.length}
      </div>

      {/* Prev */}
      {idx > 0 && (
        <button
          onClick={(e) => { e.stopPropagation(); setIdx(idx - 1); }}
          className="absolute left-4 top-1/2 -translate-y-1/2 p-2 rounded-full surface-card text-default hover:text-[var(--ds-text)]"
        >
          <ChevronLeft size={24} />
        </button>
      )}

      {/* Image */}
      <img
        src={IMG_URL(photo.image_id)}
        alt={photo.caption || ""}
        className="max-h-[85vh] max-w-[90vw] object-contain rounded-lg"
        onClick={(e) => e.stopPropagation()}
      />

      {/* Next */}
      {idx < photos.length - 1 && (
        <button
          onClick={(e) => { e.stopPropagation(); setIdx(idx + 1); }}
          className="absolute right-4 top-1/2 -translate-y-1/2 p-2 rounded-full surface-card text-default hover:text-[var(--ds-text)]"
        >
          <ChevronRight size={24} />
        </button>
      )}

      {/* Caption */}
      {photo.caption && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 surface-panel px-4 py-2 rounded-lg max-w-lg text-center">
          <span className="text-sm text-default">{photo.caption}</span>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
//  Post Composer (Create / Edit)
// ═══════════════════════════════════════════════════════════════════════════

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
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-indigo-400 underline">$1</a>')
    // Auto-link bare URLs (not already inside an <a> tag)
    .replace(/(^|[^"'>])(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer" class="text-indigo-400 underline break-all">$2</a>');
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


function PostComposer({ userId, editingPost, onDone, onCancel, allTags }) {
  const [title, setTitle] = useState(editingPost?.title || "");
  const [body, setBody] = useState(editingPost?.body || "");
  const [tagInput, setTagInput] = useState((editingPost?.tags || []).join(", "));
  const [saving, setSaving] = useState(false);
  const [showTagSuggest, setShowTagSuggest] = useState(false);
  const bodyRef = useRef(null);
  const fileInputRef = useRef(null);
  const composerRef = useRef(null);

  // Photos: array of { image_id, caption, _uploading?, _localUrl? }
  // For existing posts, seed from post.photos
  const [photos, setPhotos] = useState(() =>
    (editingPost?.photos || []).map(p => ({ image_id: p.image_id, caption: p.caption || "", id: p.id }))
  );
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.focus();
  }, []);

  // Paste image support
  const handlePastedImage = useCallback(async (file) => {
    const localUrl = URL.createObjectURL(file);
    const tempId = `_tmp_${Date.now()}`;
    setPhotos(prev => [...prev, { image_id: tempId, caption: "", _uploading: true, _localUrl: localUrl }]);
    try {
      const imageId = await uploadImageFile(file, userId);
      setPhotos(prev => prev.map(p =>
        p.image_id === tempId ? { ...p, image_id: imageId, _uploading: false } : p
      ));
    } catch (e) {
      console.error("Paste upload failed:", e);
      setPhotos(prev => prev.filter(p => p.image_id !== tempId));
    }
  }, [userId]);

  usePasteImage(composerRef, handlePastedImage);

  // File picker upload
  const handleFileSelect = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true);
    for (const file of files) {
      const localUrl = URL.createObjectURL(file);
      const tempId = `_tmp_${Date.now()}_${Math.random()}`;
      setPhotos(prev => [...prev, { image_id: tempId, caption: "", _uploading: true, _localUrl: localUrl }]);
      try {
        const imageId = await uploadImageFile(file, userId);
        setPhotos(prev => prev.map(p =>
          p.image_id === tempId ? { ...p, image_id: imageId, _uploading: false } : p
        ));
      } catch (e) {
        console.error("File upload failed:", e);
        setPhotos(prev => prev.filter(p => p.image_id !== tempId));
      }
    }
    setUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Photo management
  const removePhoto = (idx) => {
    setPhotos(prev => prev.filter((_, i) => i !== idx));
  };

  const movePhoto = (idx, dir) => {
    setPhotos(prev => {
      const arr = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= arr.length) return arr;
      [arr[idx], arr[target]] = [arr[target], arr[idx]];
      return arr;
    });
  };

  const updateCaption = (idx, caption) => {
    setPhotos(prev => prev.map((p, i) => i === idx ? { ...p, caption } : p));
  };

  const tagSuggestions = allTags
    .map(t => t.tag)
    .filter(t => {
      const currentTags = tagInput.split(",").map(s => s.trim().toLowerCase());
      const lastTag = currentTags[currentTags.length - 1] || "";
      return lastTag && t.startsWith(lastTag) && !currentTags.slice(0, -1).includes(t);
    });

  const handleTagSuggestion = (tag) => {
    const parts = tagInput.split(",").map(s => s.trim());
    parts[parts.length - 1] = tag;
    setTagInput(parts.join(", ") + ", ");
    setShowTagSuggest(false);
  };

  const anyUploading = photos.some(p => p._uploading);

  const handleSubmit = async () => {
    if (!body.trim() || anyUploading) return;
    setSaving(true);
    try {
      const tags = tagInput.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
      const readyPhotos = photos.filter(p => !p._uploading && !p.image_id.startsWith("_tmp_"));

      if (editingPost) {
        // Update post metadata/body
        await fetch(`${API}/${editingPost.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, body, tags }),
        });

        // Remove old photos that were deleted
        const oldPhotoIds = new Set((editingPost.photos || []).map(p => p.id));
        const keepPhotoIds = new Set(photos.filter(p => p.id).map(p => p.id));
        for (const oldId of oldPhotoIds) {
          if (!keepPhotoIds.has(oldId)) {
            await fetch(`${API}/${editingPost.id}/photos/${oldId}`, { method: "DELETE" });
          }
        }

        // Add new photos (ones without an existing `id`)
        const newPhotos = readyPhotos.filter(p => !p.id);
        if (newPhotos.length > 0) {
          await fetch(`${API}/${editingPost.id}/photos`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_ids: newPhotos.map(p => p.image_id) }),
          });
        }
      } else {
        // Create new post
        const res = await fetch(API, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title, body, tags,
            author_id: userId || "unknown",
          }),
        });
        const newPost = await res.json();

        // Attach photos to the new post
        if (readyPhotos.length > 0 && newPost.id) {
          await fetch(`${API}/${newPost.id}/photos`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_ids: readyPhotos.map(p => p.image_id) }),
          });
        }
      }
      onDone();
    } catch (e) {
      console.error("Save failed:", e);
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div ref={composerRef} className="border-b border-subtle surface-panel px-4 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted">
          {editingPost ? `Editing ${editingPost.id}` : "New Post"}
        </span>
        <button onClick={onCancel} className="text-faint hover:text-[var(--ds-text)]">
          <X size={16} />
        </button>
      </div>

      {/* Title */}
      <input
        type="text"
        placeholder="Title (optional)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="w-full px-3 py-1.5 text-sm rounded surface-card border border-subtle text-default placeholder-gray-500 focus:outline-none focus:border-violet-500"
      />

      {/* Body */}
      <textarea
        ref={bodyRef}
        placeholder="What's happening? (Markdown supported · paste images here)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={5}
        className="w-full px-3 py-2 text-sm rounded surface-card border border-subtle text-default placeholder-gray-500 focus:outline-none focus:border-violet-500 resize-y font-mono"
      />

      {/* Photo strip */}
      {photos.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "thin" }}>
          {photos.map((photo, idx) => (
            <div key={photo.image_id} className="relative flex-shrink-0 group/thumb">
              <img
                src={photo._localUrl || IMG_URL(photo.image_id)}
                alt={photo.caption || ""}
                className={`h-20 w-20 object-cover rounded-lg border ${
                  photo._uploading ? "border-yellow-500/50 opacity-60" : "border-subtle"
                }`}
              />
              {photo._uploading && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <Loader2 size={16} className="animate-spin text-yellow-400" />
                </div>
              )}
              {/* Remove button */}
              {!photo._uploading && (
                <button
                  onClick={() => removePhoto(idx)}
                  className="absolute -top-1 -right-1 p-0.5 rounded-full bg-red-600 text-on-accent opacity-0 group-hover/thumb:opacity-100 transition-opacity"
                >
                  <X size={10} />
                </button>
              )}
              {/* Reorder arrows */}
              {!photo._uploading && photos.length > 1 && (
                <div className="absolute bottom-0 left-0 right-0 flex justify-center gap-0.5 pb-0.5 opacity-0 group-hover/thumb:opacity-100 transition-opacity">
                  {idx > 0 && (
                    <button onClick={() => movePhoto(idx, -1)} className="p-0.5 rounded surface-card text-default">
                      <ChevronLeft size={10} />
                    </button>
                  )}
                  {idx < photos.length - 1 && (
                    <button onClick={() => movePhoto(idx, 1)} className="p-0.5 rounded surface-card text-default">
                      <ChevronRight size={10} />
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Caption inputs for photos */}
      {photos.length > 0 && (
        <div className="space-y-1">
          {photos.map((photo, idx) => (
            !photo._uploading && (
              <div key={photo.image_id + "_cap"} className="flex items-center gap-2">
                <img
                  src={photo._localUrl || IMG_URL(photo.image_id)}
                  alt=""
                  className="h-6 w-6 object-cover rounded"
                />
                <input
                  type="text"
                  placeholder={`Caption for photo ${idx + 1}`}
                  value={photo.caption}
                  onChange={(e) => updateCaption(idx, e.target.value)}
                  className="flex-1 px-2 py-1 text-[11px] rounded surface-card border border-subtle text-default placeholder-gray-600 focus:outline-none focus:border-violet-500"
                />
              </div>
            )
          ))}
        </div>
      )}

      {/* Tags */}
      <div className="relative">
        <input
          type="text"
          placeholder="Tags: vacation, family, bob (comma-separated)"
          value={tagInput}
          onChange={(e) => { setTagInput(e.target.value); setShowTagSuggest(true); }}
          onFocus={() => setShowTagSuggest(true)}
          onBlur={() => setTimeout(() => setShowTagSuggest(false), 200)}
          className="w-full px-3 py-1.5 text-xs rounded surface-card border border-subtle text-default placeholder-gray-500 focus:outline-none focus:border-violet-500"
        />
        {showTagSuggest && tagSuggestions.length > 0 && (
          <div className="absolute left-0 top-full mt-1 w-full surface-card border border-subtle rounded shadow-xl z-50 max-h-32 overflow-y-auto">
            {tagSuggestions.slice(0, 8).map(tag => (
              <button
                key={tag}
                onMouseDown={() => handleTagSuggestion(tag)}
                className="w-full text-left px-3 py-1 text-xs hover:bg-[var(--ds-raised)] text-default"
              >
                #{tag}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={handleFileSelect}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1 px-2 py-1.5 text-xs rounded border border-subtle text-muted hover:text-[var(--ds-text)] hover:border-[var(--ds-border)] disabled:opacity-40"
            title="Add photos"
          >
            {uploading ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
            Photos
          </button>
          <span className="text-[10px] text-faint">Ctrl+Enter to post · Paste images</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded border border-subtle text-muted hover:text-[var(--ds-text)] hover:border-[var(--ds-border)]"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!body.trim() || saving || anyUploading}
            className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-violet-600 hover:bg-violet-500 text-on-accent font-medium disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
            {editingPost ? "Save" : "Post"}
          </button>
        </div>
      </div>
    </div>
  );
}
