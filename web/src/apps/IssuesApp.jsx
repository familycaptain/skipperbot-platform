import { useState, useEffect, useCallback, useRef } from "react";
import { Bug, Plus, ChevronRight, Loader2, RefreshCw, Paperclip, X, Image as ImageIcon, Clipboard, Search, Bell } from "lucide-react";

const API_BASE = "";

/** Upload a File/Blob to the images API. Returns the image ID or null. */
async function uploadImageFile(file, userId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("uploaded_by", userId);
  formData.append("title", "Issue screenshot");
  const res = await fetch("/api/apps/images/upload", { method: "POST", body: formData });
  if (!res.ok) throw new Error("Upload failed");
  const data = await res.json();
  return data.id || null;
}

/** Hook: listen for paste events containing images. Calls onImage(file) for each. */
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

export default function IssuesApp({ appId, userId, context = {}, onTitle, onOpenApp }) {
  const [view, setView] = useState("list"); // "list" | "new" | "detail"
  const [issues, setIssues] = useState(null);
  const [detail, setDetail] = useState(null);
  const [filter, setFilter] = useState("all"); // "all" | "open" | "fixed" | "mine"
  const [showFixed, setShowFixed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [users, setUsers] = useState([]);

  async function apiFetch(url) {
    const res = await fetch(`${API_BASE}${url}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  useEffect(() => {
    fetch("/api/users").then(r => r.json()).then(setUsers).catch(() => {});
  }, []);

  async function apiMutate(url, method, body) {
    const res = await fetch(`${API_BASE}${url}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  const loadIssues = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let url = "/api/apps/issues";
      const params = [];
      if (filter === "open") params.push("status=open");
      if (filter === "fixed") params.push("status=fixed");
      if (filter === "mine") params.push(`reported_by=${userId}`);
      if (params.length) url += "?" + params.join("&");
      const data = await apiFetch(url);
      setIssues(data.issues || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [filter, userId]);

  useEffect(() => {
    loadIssues();
  }, [loadIssues]);

  useEffect(() => {
    if (context.issueId) {
      loadDetail(context.issueId);
    }
  }, [context.issueId]);

  async function loadDetail(issueId) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/apps/issues/${issueId}`);
      if (data.error) { setError(data.error); return; }
      setDetail(data);
      setView("detail");
      onTitle?.(data.title || "Issue");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function goList() {
    setView("list");
    setDetail(null);
    onTitle?.("Issues");
    loadIssues();
  }

  if (loading && !issues && !detail) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <Loader2 size={20} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col text-slate-200">
      {error && (
        <div className="px-4 py-2 bg-red-900/40 border-b border-red-700/40 text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-2 hover:text-white"><X size={14} /></button>
        </div>
      )}

      {view === "list" && (
        <ListView
          issues={issues || []}
          filter={filter}
          setFilter={setFilter}
          showFixed={showFixed}
          setShowFixed={setShowFixed}
          onIssueClick={loadDetail}
          onNewClick={() => setView("new")}
          onRefresh={loadIssues}
          loading={loading}
          userId={userId}
          apiMutate={apiMutate}
          setError={setError}
        />
      )}

      {view === "new" && (
        <NewIssueForm
          userId={userId}
          apiMutate={apiMutate}
          onCreated={(issue) => {
            loadDetail(issue.id);
          }}
          onCancel={goList}
          setError={setError}
        />
      )}

      {view === "detail" && detail && (
        <DetailView
          issue={detail}
          userId={userId}
          users={users}
          apiMutate={apiMutate}
          onBack={goList}
          onRefresh={() => loadDetail(detail.id)}
          setError={setError}
          onOpenApp={onOpenApp}
        />
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  List View                                                                 */
/* ═══════════════════════════════════════════════════════════════════════════ */

const STATUS_COLORS = {
  open: "bg-amber-600",
  in_progress: "bg-blue-600",
  pending_validation: "bg-purple-600",
  fixed: "bg-emerald-600",
  wont_fix: "bg-slate-600",
  duplicate: "bg-slate-600",
};

const TYPE_ICON = {
  bug: "\u{1FAB2}",      // 🪲
  feature: "\u2728",      // ✨
};

function IssueRow({ iss, onIssueClick }) {
  return (
    <button
      onClick={() => onIssueClick(iss.id)}
      className="w-full text-left px-4 py-3 border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors flex items-start gap-3"
    >
      <span className="text-lg shrink-0">{TYPE_ICON[iss.type] || TYPE_ICON.bug}</span>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-slate-200 line-clamp-2">{iss.title}</div>
        <div className="text-xs text-slate-500 mt-0.5">
          {iss.reported_by} &middot; {new Date(iss.created_at).toLocaleDateString()}
        </div>
      </div>
      <span className={`text-[10px] px-2 py-0.5 rounded-full text-white ${STATUS_COLORS[iss.status] || "bg-slate-600"}`}>
        {iss.status.replace("_", " ")}
      </span>
      <ChevronRight size={14} className="text-slate-600 shrink-0" />
    </button>
  );
}

function ListView({ issues, filter, setFilter, showFixed, setShowFixed, onIssueClick, onNewClick, onRefresh, loading, userId, apiMutate, setError }) {
  const [search, setSearch] = useState("");

  const CLOSED_STATUSES = ["fixed", "wont_fix", "duplicate", "resolved"];

  // Hide fixed/closed unless checkbox is checked
  const visibleIssues = showFixed ? issues : issues.filter((iss) => !CLOSED_STATUSES.includes(iss.status));

  // Search filter
  const searchFiltered = search.trim()
    ? visibleIssues.filter((iss) => {
        const q = search.toLowerCase();
        return (
          iss.title?.toLowerCase().includes(q) ||
          iss.description?.toLowerCase().includes(q) ||
          iss.reported_by?.toLowerCase().includes(q) ||
          iss.resolution?.toLowerCase().includes(q) ||
          iss.status?.toLowerCase().includes(q)
        );
      })
    : visibleIssues;

  // My issues: reported by me, not closed
  const myIssues = searchFiltered.filter(
    (iss) => iss.reported_by === userId && !["fixed", "wont_fix", "duplicate"].includes(iss.status)
  );
  const needsValidation = myIssues.filter((iss) => iss.status === "pending_validation");

  async function confirmFixed(issueId) {
    try {
      await apiMutate(`/api/apps/issues/${issueId}`, "PATCH", {
        updated_by: userId,
        status: "fixed",
      });
      onRefresh();
    } catch (err) {
      setError?.(err.message);
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-700/50">
        <button
          onClick={onNewClick}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors"
        >
          <Plus size={14} /> New Issue
        </button>
        <div className="relative flex-1 min-w-[140px]">
          <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search issues…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-7 pr-2 py-1.5 text-xs rounded bg-slate-800 border border-slate-600 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showFixed}
            onChange={(e) => setShowFixed(e.target.checked)}
            className="accent-emerald-500 rounded"
          />
          Fixed
        </label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-xs bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-300"
        >
          <option value="all">All</option>
          <option value="open">Open</option>
          <option value="mine">Mine</option>
        </select>
        <button onClick={onRefresh} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors" title="Refresh">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* My Issues — pending validation */}
        {needsValidation.length > 0 && (
          <div className="border-b border-purple-700/40">
            <div className="px-4 py-2 bg-purple-900/20 text-xs font-semibold text-purple-300 uppercase tracking-wider">
              Needs Your Validation
            </div>
            {needsValidation.map((iss) => (
              <div key={iss.id} className="flex items-center border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors">
                <button
                  onClick={() => onIssueClick(iss.id)}
                  className="flex-1 text-left px-4 py-3 flex items-start gap-3 min-w-0"
                >
                  <span className="text-lg shrink-0">{TYPE_ICON[iss.type] || TYPE_ICON.bug}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-slate-200 line-clamp-2">{iss.title}</div>
                    {iss.resolution && (
                      <div className="text-xs text-purple-300/70 mt-0.5 line-clamp-1">Fix: {iss.resolution}</div>
                    )}
                  </div>
                </button>
                <button
                  onClick={() => confirmFixed(iss.id)}
                  className="shrink-0 mr-3 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition-colors"
                >
                  Confirm Fixed
                </button>
              </div>
            ))}
          </div>
        )}

        {/* My open issues (not pending_validation) */}
        {myIssues.filter((iss) => iss.status !== "pending_validation").length > 0 && (
          <div className="border-b border-slate-700/40">
            <div className="px-4 py-2 bg-slate-800/40 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              My Open Issues
            </div>
            {myIssues.filter((iss) => iss.status !== "pending_validation").map((iss) => (
              <IssueRow key={iss.id} iss={iss} onIssueClick={onIssueClick} />
            ))}
          </div>
        )}

        {/* Remaining issues — excludes only those shown in My Open Issues above */}
        <div>
          {(() => {
            const myOpenIds = new Set(myIssues.map(i => i.id));
            const remainingIssues = searchFiltered.filter(iss => !myOpenIds.has(iss.id));
            const hasMyOpen = myIssues.length > 0;
            return (
              <>
                {hasMyOpen && (
                  <div className="px-4 py-2 bg-slate-800/40 text-xs font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700/40">
                    Other Issues
                  </div>
                )}
                {!hasMyOpen && issues.length > 0 && (
                  <div className="px-4 py-2 bg-slate-800/40 text-xs font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700/40">
                    All Issues
                  </div>
                )}
                {issues.length === 0 ? (
                  <div className="text-center text-slate-500 py-12 text-sm">No issues found</div>
                ) : remainingIssues.length === 0 ? (
                  <div className="text-center text-slate-500 py-8 text-sm">No other issues</div>
                ) : (
                  remainingIssues.map((iss) => (
                    <IssueRow key={iss.id} iss={iss} onIssueClick={onIssueClick} />
                  ))
                )}
              </>
            );
          })()}
        </div>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  New Issue Form                                                            */
/* ═══════════════════════════════════════════════════════════════════════════ */

function NewIssueForm({ userId, apiMutate, onCreated, onCancel, setError }) {
  const [type, setType] = useState("bug");
  const [description, setDescription] = useState("");
  const [screenshots, setScreenshots] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef(null);
  const formRef = useRef(null);

  async function doUpload(file) {
    setUploading(true);
    try {
      const imgId = await uploadImageFile(file, userId);
      if (imgId) setScreenshots((prev) => [...prev, imgId]);
    } catch (err) {
      setError?.(err.message);
    } finally {
      setUploading(false);
    }
  }

  usePasteImage(formRef, useCallback((file) => doUpload(file), [userId]));

  async function handleUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    await doUpload(file);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function handleSubmit() {
    if (!description.trim()) return;
    setSubmitting(true);
    try {
      const resp = await apiMutate("/api/apps/issues", "POST", {
        type,
        description: description.trim(),
        reported_by: userId,
        screenshots,
      });
      if (resp.ok && resp.issue) {
        onCreated(resp.issue);
      } else {
        setError?.(resp.error || "Failed to create issue");
      }
    } catch (err) {
      setError?.(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div ref={formRef} className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-200">Report an Issue</h2>
        <button onClick={onCancel} className="text-xs text-slate-400 hover:text-slate-200">Cancel</button>
      </div>

      {/* Type toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setType("bug")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            type === "bug"
              ? "bg-red-600/30 text-red-300 border border-red-500/40"
              : "bg-slate-800 text-slate-400 border border-slate-700 hover:border-slate-600"
          }`}
        >
          {"\u{1FAB2}"} Bug
        </button>
        <button
          onClick={() => setType("feature")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            type === "feature"
              ? "bg-violet-600/30 text-violet-300 border border-violet-500/40"
              : "bg-slate-800 text-slate-400 border border-slate-700 hover:border-slate-600"
          }`}
        >
          {"\u2728"} Feature Request
        </button>
      </div>

      {/* Description */}
      <div>
        <label className="block text-xs text-slate-500 mb-1">What&apos;s going on?</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe the bug or what you'd like..."
          rows={8}
          className="w-full min-h-[200px] bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-y"
          autoFocus
        />
        <p className="text-xs text-slate-600 mt-1">Tip: paste a screenshot here with Ctrl+V</p>
      </div>

      {/* Screenshots (paste only) */}
      {uploading && <p className="text-xs text-slate-400">Uploading screenshot...</p>}
      {screenshots.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {screenshots.map((imgId, i) => (
            <div key={imgId} className="relative group">
              <img
                src={`/api/apps/images/${imgId}/file`}
                alt=""
                className="h-24 max-w-[200px] object-cover rounded-lg border border-slate-600"
              />
              <button
                onClick={() => setScreenshots((prev) => prev.filter((s) => s !== imgId))}
                className="absolute -top-2 -right-2 bg-red-600 rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X size={12} className="text-white" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={!description.trim() || submitting}
        className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {submitting ? "Submitting..." : "Submit"}
      </button>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════ */
/*  Detail View                                                               */
/* ═══════════════════════════════════════════════════════════════════════════ */

const ALL_STATUSES = ["open", "in_progress", "pending_validation", "fixed", "wont_fix", "duplicate"];

function DetailView({ issue, userId, users = [], apiMutate, onBack, onRefresh, setError, onOpenApp }) {
  const [status, setStatus] = useState(issue.status);
  const [reportedBy, setReportedBy] = useState(issue.reported_by || "");
  const [description, setDescription] = useState(issue.description);
  const [resolution, setResolution] = useState(issue.resolution || "");
  const [screenshots, setScreenshots] = useState(issue.screenshots || []);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [nudging, setNudging] = useState(false);
  const [nudged, setNudged] = useState(false);
  const fileRef = useRef(null);
  const detailRef = useRef(null);

  const isDev = userId === "alice";

  useEffect(() => {
    setStatus(issue.status);
    setReportedBy(issue.reported_by || "");
    setDescription(issue.description);
    setResolution(issue.resolution || "");
    setScreenshots(issue.screenshots || []);
    setDirty(false);
    setNudged(false);
  }, [issue]);

  async function handleNudge() {
    setNudging(true);
    try {
      const resp = await fetch(`${API_BASE}/api/apps/issues/${issue.id}/nudge`, { method: "POST" });
      const data = await resp.json();
      if (data.error) {
        setError?.(data.error);
      } else {
        setNudged(true);
      }
    } catch (err) {
      setError?.(err.message);
    } finally {
      setNudging(false);
    }
  }

  async function doUpload(file) {
    setUploading(true);
    try {
      const imgId = await uploadImageFile(file, userId);
      if (imgId) {
        setScreenshots((prev) => [...prev, imgId]);
        setDirty(true);
      }
    } catch (err) {
      setError?.(err.message);
    } finally {
      setUploading(false);
    }
  }

  usePasteImage(detailRef, useCallback((file) => doUpload(file), [userId]));

  async function handleUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    await doUpload(file);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function handleSave() {
    setSaving(true);
    try {
      const body = {
        updated_by: userId,
        status,
        description,
        resolution,
        screenshots,
        reported_by: reportedBy,
      };
      const resp = await apiMutate(`/api/apps/issues/${issue.id}`, "PATCH", body);
      if (resp.error) {
        setError?.(resp.error);
      } else {
        setDirty(false);
        onRefresh();
      }
    } catch (err) {
      setError?.(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div ref={detailRef} className="p-4 space-y-5 overflow-y-auto">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={onBack}
            className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
            title="Back to list"
          >
            <ChevronRight size={18} className="rotate-180" />
          </button>
          <span className="text-lg">{TYPE_ICON[issue.type] || TYPE_ICON.bug}</span>
          <h2 className="text-lg font-semibold text-slate-200 flex-1">{issue.title}</h2>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500 ml-8">
          <span className="flex items-center gap-1">Reported by {isDev ? (
            <select
              value={reportedBy}
              onChange={(e) => { setReportedBy(e.target.value); setDirty(true); }}
              className="text-xs bg-slate-800 border border-slate-600 rounded px-1.5 py-0.5 text-slate-300"
            >
              {users.map((u) => (
                <option key={u.name} value={u.name}>{u.display_name || u.name}</option>
              ))}
            </select>
          ) : (
            <span className="text-slate-300">{reportedBy}</span>
          )}</span>
          <span>&middot;</span>
          <span>{new Date(issue.created_at).toLocaleString()}</span>
          <span>&middot;</span>
          <button
            onClick={() => {
              const text = `Please query the issue details for issue ${issue.id} from the database, access and view any related screenshots, and work on fixing this issue.`;
              navigator.clipboard.writeText(text);
            }}
            className="text-slate-500 hover:text-indigo-400 cursor-pointer transition-colors"
            title="Click to copy prompt to clipboard"
          >{issue.id}</button>
        </div>
      </div>

      {/* Status */}
      <div className="ml-8">
        <label className="block text-xs text-slate-500 mb-1">Status</label>
        {isDev ? (
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setDirty(true); }}
            className="text-xs bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-300"
          >
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace("_", " ")}</option>
            ))}
          </select>
        ) : (
          <span className={`text-xs px-2 py-0.5 rounded-full text-white ${STATUS_COLORS[status] || "bg-slate-600"}`}>
            {status.replace("_", " ")}
          </span>
        )}
      </div>

      {/* Nudge reporter button — only for pending_validation */}
      {status === "pending_validation" && issue.reported_by && (
        <div className="ml-8">
          <button
            onClick={handleNudge}
            disabled={nudging || nudged}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              nudged
                ? "bg-emerald-900/30 text-emerald-400 border border-emerald-700/40"
                : "bg-amber-900/30 text-amber-300 border border-amber-700/40 hover:bg-amber-800/40"
            } disabled:opacity-60`}
          >
            <Bell size={12} />
            {nudging ? "Sending..." : nudged ? `Pinged ${issue.reported_by}` : `Ping ${issue.reported_by} to validate`}
          </button>
        </div>
      )}

      {/* Description */}
      <div className="ml-8">
        <label className="block text-xs text-slate-500 mb-1">Description</label>
        <textarea
          value={description}
          onChange={(e) => { setDescription(e.target.value); setDirty(true); }}
          rows={4}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 resize-y"
          readOnly={issue.reported_by !== userId && !isDev}
        />
      </div>

      {/* Screenshots */}
      <div className="ml-8">
        <label className="block text-xs text-slate-500 mb-1">Screenshots</label>
        <div className="flex flex-wrap gap-2 mb-2">
          {screenshots.map((imgId, i) => (
            <div key={imgId} className="relative group">
              <button
                onClick={() => onOpenApp?.("image", { imageId: imgId })}
                className="block"
              >
                <img
                  src={`/api/apps/images/${imgId}/file`}
                  alt=""
                  className="h-24 max-w-[200px] object-cover rounded-lg border border-slate-600 hover:border-indigo-500 transition-colors cursor-pointer"
                />
              </button>
              <button
                onClick={() => { setScreenshots((prev) => prev.filter((s) => s !== imgId)); setDirty(true); }}
                className="absolute -top-2 -right-2 bg-red-600 rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X size={12} className="text-white" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Resolution (developer only for editing, read-only for others when filled) */}
      {(isDev || resolution) && (
        <div className="ml-8">
          <label className="block text-xs text-slate-500 mb-1">Resolution</label>
          {isDev ? (
            <textarea
              value={resolution}
              onChange={(e) => { setResolution(e.target.value); setDirty(true); }}
              placeholder="What was done to fix this..."
              rows={3}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-y"
            />
          ) : (
            <div className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300 whitespace-pre-wrap">
              {resolution}
            </div>
          )}
        </div>
      )}

      {/* Save */}
      {dirty && (
        <div className="ml-8">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
