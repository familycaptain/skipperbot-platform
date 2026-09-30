import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Bell, Clock, CornerUpLeft, FileText, Layers, Wrench } from "lucide-react";
import { agentLabel } from "../hooks/useAgents";

/**
 * Single chat message bubble.
 *
 * Roles: "user" | "bot" | "notification" | "tool_call" | "tool_slot"
 * Shared thread: a "bot" message with `speaker` is an agent participant (labelled, with a
 * Reply button); a "user" message with `routed_to` went to that agent instead of Skipper.
 * Bot messages render markdown. User messages render plain text.
 * Notifications get a colored badge based on source.
 * Tool calls show tool name + args with a wrench icon.
 */

const NOTIF_ICONS = {
  reminder: Clock,
  research: FileText,
  refine: FileText,
};

function formatArgValue(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") {
    return value.length > 90 ? value.slice(0, 90) + "…" : value;
  }
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const s = JSON.stringify(value);
    return s.length > 90 ? `[${value.length} items]` : s;
  }
  if (typeof value === "object") {
    const s = JSON.stringify(value);
    return s.length > 90 ? s.slice(0, 90) + "…" : s;
  }
  return String(value);
}

// A small, muted timestamp shown under a bubble (issue #8). Locale-formatted so it
// respects the user's 12h/24h preference; a real <time> element for accessibility.
function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function MessageTime({ ts, align }) {
  const label = formatTime(ts);
  if (!label) return null;
  const full = (() => { const d = new Date(ts); return isNaN(d) ? "" : d.toLocaleString(); })();
  return (
    <time
      dateTime={ts}
      title={full}
      className={`block text-[11px] text-faint mt-0.5 px-1 ${align === "end" ? "text-right" : "text-left"}`}
    >
      {label}
    </time>
  );
}

export default function ChatMessage({ message, showTime = false, agents = {}, onReply }) {
  const { role, content, source, ts } = message;

  // ── User message ──
  if (role === "user") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[80%] md:max-w-[65%] px-4 py-2.5 rounded-2xl rounded-br-md bg-indigo-600 text-on-accent text-sm leading-relaxed">
          {content}
        </div>
        {/* Shared thread: this message went to an agent participant, not Skipper. */}
        {message.routed_to && (
          <span className="pill pill-neutral text-[11px] mt-1" title="Delivered to this agent — Skipper won't reply to it">
            → {agentLabel(agents, message.routed_to)}
          </span>
        )}
        {showTime && <MessageTime ts={ts} align="end" />}
      </div>
    );
  }

  // ── Notification ──
  if (role === "notification") {
    const Icon = NOTIF_ICONS[source] || Bell;
    return (
      <div className="flex flex-col items-start">
        <div className="max-w-[85%] md:max-w-[70%] px-4 py-2.5 rounded-2xl rounded-bl-md bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 text-default text-sm leading-relaxed flex items-start gap-2">
          <Icon size={16} className="text-indigo-400 mt-0.5 shrink-0" />
          {/* Render markdown like bot bubbles (sanitized: react-markdown escapes HTML,
              no rehype-raw). remark-breaks keeps single newlines as line breaks so a
              plain multi-line notification doesn't collapse (was whitespace-pre-wrap). */}
          <div className="markdown-body min-w-0 flex-1">
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{content}</ReactMarkdown>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Skipper's notifications (reminders, nudges, results) are things people answer —
              "done", "snooze it". The server maps the card's id to its log row. */}
          {onReply && message.srv_id && (
            <button
              type="button"
              onClick={() => onReply(message)}
              className="btn-ghost focus-ring text-[11px] px-1 mt-0.5 rounded flex items-center gap-1 text-faint"
              title="Reply to this notification"
            >
              <CornerUpLeft size={11} /> Reply
            </button>
          )}
          {showTime && <MessageTime ts={ts} align="start" />}
        </div>
      </div>
    );
  }

  // ── Tool call ──
  if (role === "tool_call") {
    const { toolName, toolArgs } = message;
    const argEntries = Object.entries(toolArgs || {}).filter(
      ([, v]) => v !== null && v !== undefined && v !== ""
    );
    return (
      <div className="flex justify-start pl-1">
        <div className="max-w-[85%] md:max-w-[70%] px-3 py-2 rounded-xl rounded-bl-sm surface-raised border border-subtle text-xs">
          <div className="flex items-center gap-1.5 mb-1">
            <Wrench size={11} className="text-accent shrink-0" />
            <span className="font-mono font-semibold text-accent tracking-wide">{toolName}</span>
          </div>
          {argEntries.length > 0 && (
            <div className="space-y-0.5 pl-3 border-l border-subtle mt-1">
              {argEntries.map(([key, value]) => (
                <div key={key} className="flex gap-1.5 text-muted leading-snug">
                  <span className="text-faint shrink-0 font-mono">{key}:</span>
                  <span className="text-default font-mono break-all">{formatArgValue(value)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Tool-category slot load/unload (observability for the slot-based tool router) ──
  if (role === "tool_slot") {
    const { loaded, unloaded, slots } = message;
    return (
      <div className="flex justify-start pl-1">
        <div className="max-w-[85%] md:max-w-[70%] px-3 py-1.5 rounded-xl rounded-bl-sm bg-emerald-900/25 border border-emerald-700/40 text-xs">
          <div className="flex items-center gap-2 flex-wrap font-mono">
            <Layers size={11} className="text-emerald-400 shrink-0" />
            {loaded && <span className="text-emerald-300">＋ {loaded}</span>}
            {unloaded && <span className="text-faint">－ {unloaded}</span>}
            {Array.isArray(slots) && (
              <span className="text-faint">slots: [{slots.join(", ") || "—"}]</span>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Agent participant message (shared thread) ──
  if (message.speaker) {
    return (
      <div className="flex flex-col items-start">
        <span className="text-xs font-semibold text-muted px-1 mb-0.5">
          {agentLabel(agents, message.speaker)}
        </span>
        <div className="max-w-[85%] md:max-w-[70%] px-4 py-2.5 rounded-2xl rounded-bl-md surface-raised border border-strong text-sm leading-relaxed markdown-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
        <div className="flex items-center gap-2">
          {onReply && message.srv_id && (
            <button
              type="button"
              onClick={() => onReply(message)}
              className="btn-ghost focus-ring text-[11px] px-1 mt-0.5 rounded flex items-center gap-1"
              title={`Reply to ${agentLabel(agents, message.speaker)}`}
            >
              <CornerUpLeft size={11} /> Reply
            </button>
          )}
          {showTime && <MessageTime ts={ts} align="start" />}
        </div>
      </div>
    );
  }

  // ── Bot message (markdown) ──
  return (
    <div className="flex flex-col items-start group">
      <div className="max-w-[85%] md:max-w-[70%] px-4 py-2.5 rounded-2xl rounded-bl-md surface-card text-sm leading-relaxed markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
      <div className="flex items-center gap-2">
        {/* Reply to Skipper specifically — makes intent explicit in the shared thread (it
            wins over an agent's open question). Always visible: hover-only would hide it on touch screens. */}
        {onReply && message.srv_id && (
          <button
            type="button"
            onClick={() => onReply(message)}
            className="btn-ghost focus-ring text-[11px] px-1 mt-0.5 rounded flex items-center gap-1 text-faint"
            title="Reply to Skipper"
          >
            <CornerUpLeft size={11} /> Reply
          </button>
        )}
        {showTime && <MessageTime ts={ts} align="start" />}
      </div>
    </div>
  );
}
