import { useRef, useEffect, useState } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import TypingIndicator from "./TypingIndicator";
import AgentPresenceBar from "./AgentPresenceBar";
import { CornerUpLeft, X } from "lucide-react";
import useAgents, { agentLabel } from "../hooks/useAgents";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

// Relative label for a 'YYYY-MM-DD' separator date vs the current date. Derived at
// render time (not baked server-side) so an open window updates at midnight (issue #8).
function relLabel(dateStr, today) {
  if (!dateStr) return "";
  const todayKey = today.toLocaleDateString("en-CA");
  const y = new Date(today);
  y.setDate(y.getDate() - 1);
  const yKey = y.toLocaleDateString("en-CA");
  if (dateStr === todayKey) return "Today";
  if (dateStr === yKey) return "Yesterday";
  const [Y, M, D] = dateStr.split("-").map(Number);
  if (!Y) return dateStr;
  return `${MONTHS[M - 1]} ${D}, ${Y}`;
}

function sameMinute(a, b) {
  if (!a || !b) return false;
  return a.slice(0, 16) === b.slice(0, 16); // ISO 'YYYY-MM-DDTHH:MM'
}

/**
 * Self-contained chat panel: a flex column of messages (scrollable) + pinned input.
 * Renders date separators inline and a per-bubble timestamp (issue #8).
 */
export default function ChatPanel({
  userId,
  connected,
  messages,
  isTyping,
  progress,
  sending,
  onSend,
}) {
  const scrollRef = useRef(null);
  const agents = useAgents();
  // Shared thread: the message being replied to ({srv_id, speaker?}; no speaker = Skipper) or null.
  const [replyTo, setReplyTo] = useState(null);
  const handleSend = (text) => {
    onSend(text, replyTo ? { replyTo: replyTo.srv_id } : {});
    setReplyTo(null);
  };

  // Current day, refreshed at local midnight so 'Today'/'Yesterday' stay correct
  // while the window is open (operator's Gate-1 note).
  const [today, setToday] = useState(() => new Date());
  useEffect(() => {
    const now = new Date();
    const nextMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 5);
    const t = setTimeout(() => setToday(new Date()), nextMidnight - now);
    return () => clearTimeout(t);
  }, [today]);

  // Auto-scroll to bottom on new messages, typing, or progress
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping, progress]);

  return (
    <div className="flex flex-col flex-1 min-h-0 min-w-0">
      {/* Shared thread: who is present (Skipper + online agent participants). */}
      <AgentPresenceBar connected={connected} />
      {/* Messages area — aria-live so the deferred greeting and new messages are
          announced to assistive tech when they appear (issue #16). */}
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3 chat-scroll"
      >
        {messages.map((msg, i) => {
          // Date separator — rendered here (NOT via ChatMessage, whose default
          // branch would draw an unknown role as a bot bubble).
          if (msg.role === "date_separator") {
            const label = relLabel(msg.date, today);
            return (
              <div key={msg.id} role="separator" aria-label={label}
                   className="flex items-center gap-3 py-1 select-none">
                <div className="flex-1 h-px divider" />
                <span className="text-xs font-medium text-muted">{label}</span>
                <div className="flex-1 h-px divider" />
              </div>
            );
          }
          // Show the time only on the last of a run of same-sender, same-minute
          // messages (collapse consecutive); never on tool_call / tool_slot rows.
          const next = messages[i + 1];
          const showTime = msg.role !== "tool_call" && msg.role !== "tool_slot" && !(
            next && next.role === msg.role && sameMinute(next.ts, msg.ts)
          );
          return <ChatMessage key={msg.id} message={msg} showTime={showTime}
                              agents={agents} onReply={setReplyTo} />;
        })}

        {/* Progress message (replaces on each new progress event) */}
        {progress && (
          <div className="text-sm text-muted italic px-1">{progress}</div>
        )}

        {/* Typing indicator */}
        {isTyping && <TypingIndicator />}
      </div>

      {/* Input bar — pinned to bottom */}
      {replyTo && (
        <div className="shrink-0 flex items-center gap-2 px-4 py-1.5 border-t border-subtle surface-panel text-xs text-muted">
          <CornerUpLeft size={12} />
          <span className="truncate flex-1">
            Replying to {agentLabel(agents, replyTo.speaker || "skipper")}: {(replyTo.content || "").slice(0, 80)}
          </span>
          <button type="button" className="btn-ghost focus-ring rounded p-0.5" onClick={() => setReplyTo(null)}
                  aria-label="Cancel reply">
            <X size={12} />
          </button>
        </div>
      )}
      <ChatInput
        onSend={handleSend}
        focusKey={replyTo ? replyTo.srv_id : null}
        disabled={!connected || sending}
        placeholder={!connected ? "Reconnecting…"
          : replyTo ? `Reply to ${agentLabel(agents, replyTo.speaker || "skipper")}…` : "Message Skipper…"}
      />
    </div>
  );
}
