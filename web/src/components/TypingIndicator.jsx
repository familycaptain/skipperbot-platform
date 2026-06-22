/**
 * Animated typing dots shown while Skipper is thinking.
 */
export default function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="px-4 py-3 rounded-2xl rounded-bl-md surface-card">
        <div className="flex gap-1.5">
          <span className="w-2 h-2 rounded-full dot animate-bounce [animation-delay:0ms]" />
          <span className="w-2 h-2 rounded-full dot animate-bounce [animation-delay:150ms]" />
          <span className="w-2 h-2 rounded-full dot animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}
