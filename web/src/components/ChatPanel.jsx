import { useRef, useEffect } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import TypingIndicator from "./TypingIndicator";

/**
 * Self-contained chat panel.
 *
 * Phase 1: Fills the entire content area below the top bar.
 * Phase 2: Becomes the right panel in a split layout — no changes needed.
 *
 * Structurally, this is a flex column: messages area (scrollable) + input bar (pinned).
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

  // Auto-scroll to bottom on new messages, typing, or progress
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping, progress]);

  return (
    <div className="flex flex-col flex-1 min-h-0 min-w-0">
      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3 chat-scroll"
      >
        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}

        {/* Progress message (replaces on each new progress event) */}
        {progress && (
          <div className="text-sm text-slate-400 italic px-1">{progress}</div>
        )}

        {/* Typing indicator */}
        {isTyping && <TypingIndicator />}
      </div>

      {/* Input bar — pinned to bottom */}
      <ChatInput
        onSend={onSend}
        disabled={!connected || sending}
        placeholder={connected ? "Message Skipper…" : "Reconnecting…"}
      />
    </div>
  );
}
