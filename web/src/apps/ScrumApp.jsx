import React, { useState, useEffect, useCallback } from "react";
import {
  ClipboardList, Target, CheckCircle2, AlertTriangle, CalendarClock,
  ChevronDown, ChevronUp, Users, User, Send, MessageSquare, Check, Plus,
} from "lucide-react";

function ScrumSectionInput({ questionKey, person, onCreated }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const placeholders = {
    done: "I also finished\u2026",
    focus: "I\u2019m also working on\u2026",
    blocked: "No blockers / Blocked on\u2026",
  };

  async function handleSubmit(e) {
    e.preventDefault();
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      const res = await fetch("/api/apps/scrum", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          item_type: questionKey,
          title: text.trim(),
          person: person || "alice",
          response: text.trim(),
        }),
      });
      if (res.ok) {
        setText("");
        setOpen(false);
        onCreated();
      }
    } catch {}
    setSending(false);
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1 px-3 py-1.5 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
      >
        <Plus size={10} /> {placeholders[questionKey] || "Add\u2026"}
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-1.5 px-3 py-2">
      <input
        type="text"
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={placeholders[questionKey] || "Type here\u2026"}
        autoFocus
        className="flex-1 bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500"
      />
      <button
        type="submit"
        disabled={!text.trim() || sending}
        className="p-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 transition-colors"
        title="Submit"
      >
        <Send size={11} className="text-white" />
      </button>
      <button
        type="button"
        onClick={() => { setOpen(false); setText(""); }}
        className="p-1.5 rounded bg-slate-700 hover:bg-slate-600 transition-colors text-[10px] text-slate-300"
      >
        &times;
      </button>
    </form>
  );
}

const TYPE_META = {
  focus:    { icon: Target,         color: "text-blue-400",   bg: "bg-blue-500/10",    label: "Focus" },
  done:     { icon: CheckCircle2,   color: "text-emerald-400", bg: "bg-emerald-500/10", label: "Done" },
  blocked:  { icon: AlertTriangle,  color: "text-red-400",    bg: "bg-red-500/10",      label: "Blocked" },
  finding:  { icon: ClipboardList,  color: "text-amber-400",  bg: "bg-amber-500/10",    label: "Finding" },
  schedule: { icon: CalendarClock,  color: "text-cyan-400",   bg: "bg-cyan-500/10",     label: "Schedule" },
};

const SCRUM_QUESTIONS = [
  { key: "done",    label: "What did you finish?",          icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20" },
  { key: "focus",   label: "What are you working on today?", icon: Target,       color: "text-blue-400",    bg: "bg-blue-500/10",    border: "border-blue-500/20" },
  { key: "blocked", label: "Any blockers?",                  icon: AlertTriangle,color: "text-red-400",     bg: "bg-red-500/10",     border: "border-red-500/20" },
];

function stripPrefix(title) {
  return title.replace(/^(Completed|Focus|Blocked):\s*/i, "");
}

const SEVERITY_BADGE = {
  critical: "bg-red-600/30 text-red-300",
  warning:  "bg-amber-600/30 text-amber-300",
  info:     "bg-blue-600/30 text-blue-300",
};

function ScrumItemCard({ item, userId, person, onResponded }) {
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);

  const meta = TYPE_META[item.item_type] || TYPE_META.finding;
  const Icon = meta.icon;
  const hasResponse = !!item.response;
  const isOwnItem = !person || person === userId;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!replyText.trim() || sending) return;
    setSending(true);
    try {
      const res = await fetch(`/api/apps/scrum/${item.id}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response_text: replyText.trim(), user_id: userId }),
      });
      if (res.ok) {
        setReplyText("");
        setReplyOpen(false);
        onResponded(item.id, replyText.trim());
      }
    } catch {}
    setSending(false);
  }

  return (
    <div className={`px-3 py-2 ${hasResponse ? "bg-slate-800/20" : ""}`}>
      <div className="flex items-start gap-2">
        <div className={`mt-0.5 p-1 rounded ${meta.bg}`}>
          <Icon size={12} className={meta.color} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={`text-xs font-medium truncate ${hasResponse ? "text-slate-400" : "text-white"}`}>
              {item.title}
            </span>
            {hasResponse && (
              <span className="flex items-center gap-0.5 px-1 py-0 rounded text-[10px] bg-emerald-600/20 text-emerald-400">
                <Check size={8} /> replied
              </span>
            )}
            {item.severity && (
              <span className={`px-1 py-0 rounded text-[10px] ${SEVERITY_BADGE[item.severity] || SEVERITY_BADGE.info}`}>
                {item.severity}
              </span>
            )}
          </div>
          {item.project_name && (
            <span className="text-[10px] text-slate-500">{item.project_name}</span>
          )}
          {item.detail && (
            <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{item.detail}</p>
          )}
          {!person && item.person && (
            <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500 mt-0.5">
              <Users size={9} /> {item.person}
            </span>
          )}

          {/* Existing response display */}
          {hasResponse && (
            <div className="mt-1.5 px-2 py-1.5 bg-indigo-500/10 border border-indigo-500/20 rounded text-xs text-indigo-300">
              <span className="text-[10px] text-indigo-400/60 uppercase font-medium">Response:</span>
              <p className="mt-0.5">{item.response}</p>
            </div>
          )}

          {/* Reply button + input */}
          {isOwnItem && !hasResponse && (
            <div className="mt-1.5">
              {!replyOpen ? (
                <button
                  onClick={() => setReplyOpen(true)}
                  className="flex items-center gap-1 text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  <MessageSquare size={10} /> Reply
                </button>
              ) : (
                <form onSubmit={handleSubmit} className="flex items-end gap-1.5">
                  <textarea
                    value={replyText}
                    onChange={e => setReplyText(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(e); } }}
                    placeholder="Type your response..."
                    rows={2}
                    autoFocus
                    className="flex-1 bg-slate-800 text-white text-xs px-2 py-1.5 rounded border border-slate-700 outline-none focus:border-indigo-500 resize-none"
                  />
                  <div className="flex flex-col gap-1">
                    <button
                      type="submit"
                      disabled={!replyText.trim() || sending}
                      className="p-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      title="Send response"
                    >
                      <Send size={11} className="text-white" />
                    </button>
                    <button
                      type="button"
                      onClick={() => { setReplyOpen(false); setReplyText(""); }}
                      className="p-1.5 rounded bg-slate-700 hover:bg-slate-600 transition-colors text-[10px] text-slate-300"
                      title="Cancel"
                    >
                      &times;
                    </button>
                  </div>
                </form>
              )}
              {sending && (
                <p className="text-[10px] text-indigo-400 mt-1 animate-pulse">Sending to Skipper...</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ScrumApp({ appId, userId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [person, setPerson] = useState(userId || "");
  const [days, setDays] = useState(7);
  const [users, setUsers] = useState([]);
  const [expandedDates, setExpandedDates] = useState(new Set());

  // Load users for the person picker
  useEffect(() => {
    fetch("/api/users")
      .then(r => r.ok ? r.json() : [])
      .then(data => setUsers(Array.isArray(data) ? data : data.users || []))
      .catch(() => {});
  }, []);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (person) params.set("person", person);
      params.set("days", String(days));
      const res = await fetch(`/api/apps/scrum?${params}`);
      if (res.ok) {
        const data = await res.json();
        setItems(data.items || []);
      }
    } catch {}
    setLoading(false);
  }, [person, days]);

  useEffect(() => { loadItems(); }, [loadItems]);

  // Auto-expand the most recent date
  useEffect(() => {
    if (items.length > 0) {
      const dates = [...new Set(items.map(i => i.report_date))];
      if (dates.length > 0) {
        setExpandedDates(new Set([dates[0]]));
      }
    }
  }, [items]);

  // Optimistic update after responding
  function handleResponded(itemId, responseText) {
    setItems(prev => prev.map(i =>
      i.id === itemId ? { ...i, response: responseText, responded_at: new Date().toISOString() } : i
    ));
  }

  // Group items by date
  const grouped = {};
  for (const item of items) {
    const d = item.report_date;
    if (!grouped[d]) grouped[d] = [];
    grouped[d].push(item);
  }
  const sortedDates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  function toggleDate(d) {
    setExpandedDates(prev => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d); else next.add(d);
      return next;
    });
  }

  function formatDate(iso) {
    try {
      const d = new Date(iso + "T12:00:00");
      return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    } catch { return iso; }
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <ClipboardList size={14} className="text-indigo-400" />
          <h2 className="text-sm font-medium text-white">Daily Scrum</h2>
        </div>
        <div className="flex items-center gap-2">
          {/* Person picker */}
          <div className="flex items-center gap-1">
            <User size={12} className="text-slate-400" />
            <select
              value={person}
              onChange={e => setPerson(e.target.value)}
              className="bg-slate-800 text-white text-xs px-2 py-1 rounded border border-slate-700 outline-none"
            >
              <option value="">All Users</option>
              {users.map(u => (
                <option key={u.name} value={u.name}>{u.display_name || u.name}</option>
              ))}
            </select>
          </div>
          {/* Days picker */}
          <select
            value={days}
            onChange={e => setDays(parseInt(e.target.value))}
            className="bg-slate-800 text-white text-xs px-2 py-1 rounded border border-slate-700 outline-none"
          >
            <option value={1}>Today</option>
            <option value={3}>3 days</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {loading && (
          <div className="text-center text-slate-400 text-sm py-8">Loading...</div>
        )}

        {!loading && items.length === 0 && (
          <div className="text-center py-12 space-y-3">
            <ClipboardList size={36} className="text-slate-600 mx-auto" />
            <p className="text-sm text-slate-400">No scrum items yet.</p>
            <p className="text-xs text-slate-500">
              Items appear here after the daily PM digest runs each morning.
            </p>
          </div>
        )}

        {sortedDates.map(d => {
          const dateItems = grouped[d];
          const isExpanded = expandedDates.has(d);
          const typeCounts = {};
          const pendingCount = dateItems.filter(i => !i.response).length;
          for (const it of dateItems) {
            typeCounts[it.item_type] = (typeCounts[it.item_type] || 0) + 1;
          }

          return (
            <div key={d} className="border border-slate-700/50 rounded-lg overflow-hidden">
              {/* Date header */}
              <button
                onClick={() => toggleDate(d)}
                className="w-full flex items-center justify-between px-3 py-2 bg-slate-800/50 hover:bg-slate-800/80 transition-colors"
              >
                <div className="flex items-center gap-2">
                  {isExpanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
                  <span className="text-sm font-medium text-white">{formatDate(d)}</span>
                  <span className="text-xs text-slate-500">{dateItems.length} items</span>
                  {pendingCount > 0 && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-indigo-600/30 text-indigo-300">
                      {pendingCount} pending
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  {Object.entries(typeCounts).map(([type, count]) => {
                    const meta = TYPE_META[type] || TYPE_META.finding;
                    const TIcon = meta.icon;
                    return (
                      <span key={type} className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] ${meta.bg} ${meta.color}`}>
                        <TIcon size={10} /> {count}
                      </span>
                    );
                  })}
                </div>
              </button>

              {/* Items grouped by scrum question */}
              {isExpanded && (() => {
                const now = new Date();
                const todayStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
                const isToday = d === todayStr;
                const isOwnScrum = !person || person === userId;
                return (
                <div>
                  {SCRUM_QUESTIONS.map(q => {
                    const sectionItems = dateItems.filter(i => i.item_type === q.key);
                    const QIcon = q.icon;
                    return (
                      <div key={q.key}>
                        <div className={`flex items-center gap-2 px-3 py-1.5 ${q.bg} border-b ${q.border}`}>
                          <QIcon size={13} className={q.color} />
                          <span className={`text-xs font-semibold ${q.color}`}>{q.label}</span>
                          {sectionItems.length > 0 && (
                            <span className="text-[10px] text-slate-500">{sectionItems.length}</span>
                          )}
                        </div>
                        {sectionItems.length > 0 ? (
                          <div className="divide-y divide-slate-800/50">
                            {sectionItems.map(item => (
                              <ScrumItemCard
                                key={item.id}
                                item={{ ...item, title: stripPrefix(item.title) }}
                                userId={userId}
                                person={person}
                                onResponded={handleResponded}
                              />
                            ))}
                          </div>
                        ) : (
                          <div className="px-3 py-1.5 text-[10px] text-slate-600 italic">
                            {q.key === "blocked" ? "No blockers reported" : "None"}
                          </div>
                        )}
                        {/* Freeform input — only for today and own scrum */}
                        {isToday && isOwnScrum && (
                          <ScrumSectionInput
                            questionKey={q.key}
                            person={person || userId}
                            onCreated={loadItems}
                          />
                        )}
                      </div>
                    );
                  })}
                  {/* Other types (finding, schedule) */}
                  {(() => {
                    const otherItems = dateItems.filter(i => !SCRUM_QUESTIONS.some(q => q.key === i.item_type));
                    if (otherItems.length === 0) return null;
                    return (
                      <div>
                        <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-700/20 border-b border-slate-700/30">
                          <ClipboardList size={13} className="text-slate-400" />
                          <span className="text-xs font-semibold text-slate-400">Other</span>
                          <span className="text-[10px] text-slate-500">{otherItems.length}</span>
                        </div>
                        <div className="divide-y divide-slate-800/50">
                          {otherItems.map(item => (
                            <ScrumItemCard
                              key={item.id}
                              item={item}
                              userId={userId}
                              person={person}
                              onResponded={handleResponded}
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })()}
                </div>
                );
              })()}
            </div>
          );
        })}
      </div>
    </div>
  );
}
