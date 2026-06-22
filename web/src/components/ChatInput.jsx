import { useState, useRef, useEffect } from "react";
import { SendHorizontal } from "lucide-react";

/**
 * Chat input bar with auto-expanding textarea.
 * Sends on Enter (Shift+Enter for newline).
 */
export default function ChatInput({ onSend, disabled, placeholder }) {
  const [text, setText] = useState("");
  const inputRef = useRef(null);

  // Focus input on mount and when re-enabled
  useEffect(() => {
    if (!disabled && inputRef.current) {
      inputRef.current.focus();
    }
  }, [disabled]);

  function handleSubmit(e) {
    e?.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    // Reset textarea height
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(e) {
    // Skip while IME-composing (e.isComposing / keyCode 229) so CJK users
    // pressing Enter to confirm a composition don't send a half-composed message.
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleInput(e) {
    setText(e.target.value);
    // Auto-resize textarea
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-2 px-4 py-3 border-t border-subtle surface-panel"
    >
      <textarea
        ref={inputRef}
        value={text}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        className="flex-1 resize-none input rounded-xl text-sm px-4 py-2.5 outline-none focus:ring-1 focus:ring-indigo-500/50 disabled:opacity-50 leading-relaxed"
      />
      {/* Controlled button (type=button + onClick), never a native submit button,
          so a native form submit can never fire a full-page reload under load
          (issue #36). Enter is handled by the textarea onKeyDown above; the
          <form onSubmit> is kept as a backstop. */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={disabled || !text.trim()}
        className="shrink-0 w-9 h-9 rounded-xl btn-primary flex items-center justify-center transition-colors"
      >
        <SendHorizontal size={16} />
      </button>
    </form>
  );
}
