import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bell, Clock, FileText, Wrench } from "lucide-react";

/**
 * Single chat message bubble.
 *
 * Roles: "user" | "bot" | "notification" | "tool_call"
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

export default function ChatMessage({ message }) {
  const { role, content, source } = message;

  // ── User message ──
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] md:max-w-[65%] px-4 py-2.5 rounded-2xl rounded-br-md bg-indigo-600 text-white text-sm leading-relaxed">
          {content}
        </div>
      </div>
    );
  }

  // ── Notification ──
  if (role === "notification") {
    const Icon = NOTIF_ICONS[source] || Bell;
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] md:max-w-[70%] px-4 py-2.5 rounded-2xl rounded-bl-md bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 text-slate-200 text-sm leading-relaxed flex items-start gap-2">
          <Icon size={16} className="text-indigo-400 mt-0.5 shrink-0" />
          <span className="whitespace-pre-wrap">{content}</span>
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
        <div className="max-w-[85%] md:max-w-[70%] px-3 py-2 rounded-xl rounded-bl-sm bg-slate-700/50 border border-slate-600/40 text-xs">
          <div className="flex items-center gap-1.5 mb-1">
            <Wrench size={11} className="text-sky-400 shrink-0" />
            <span className="font-mono font-semibold text-sky-300 tracking-wide">{toolName}</span>
          </div>
          {argEntries.length > 0 && (
            <div className="space-y-0.5 pl-3 border-l border-slate-600/50 mt-1">
              {argEntries.map(([key, value]) => (
                <div key={key} className="flex gap-1.5 text-slate-400 leading-snug">
                  <span className="text-slate-500 shrink-0 font-mono">{key}:</span>
                  <span className="text-slate-300 font-mono break-all">{formatArgValue(value)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Bot message (markdown) ──
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] md:max-w-[70%] px-4 py-2.5 rounded-2xl rounded-bl-md bg-slate-800 text-slate-100 text-sm leading-relaxed markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
