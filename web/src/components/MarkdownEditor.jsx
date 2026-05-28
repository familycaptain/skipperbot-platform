import { useRef, useEffect, useCallback } from "react";
import { EditorState, StateField, StateEffect } from "@codemirror/state";
import { EditorView, keymap, placeholder as cmPlaceholder, lineNumbers, Decoration } from "@codemirror/view";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { defaultKeymap, indentWithTab } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import {
  syntaxHighlighting,
  defaultHighlightStyle,
  HighlightStyle,
  bracketMatching,
} from "@codemirror/language";
import { tags } from "@lezer/highlight";

/* ── Diff highlight decorations for review mode ── */

const setDiffHighlights = StateEffect.define();

const diffAddMark = Decoration.mark({ class: "cm-diff-add" });
const diffRemoveMark = Decoration.mark({ class: "cm-diff-remove" });

const diffHighlightField = StateField.define({
  create() {
    return Decoration.none;
  },
  update(decorations, tr) {
    for (const e of tr.effects) {
      if (e.is(setDiffHighlights)) {
        const highlights = e.value;
        if (!highlights || highlights.length === 0) return Decoration.none;
        const marks = [];
        for (const h of highlights) {
          if (h.from >= h.to) continue;
          const mark = h.type === "add" ? diffAddMark : diffRemoveMark;
          marks.push(mark.range(h.from, h.to));
        }
        return Decoration.set(marks, true);
      }
    }
    return decorations;
  },
  provide: (f) => EditorView.decorations.from(f),
});

/* ── Dark theme matching the app's slate palette ── */

const darkTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "transparent",
      color: "#e2e8f0",
      fontSize: "14px",
      fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
      lineHeight: "1.6",
    },
    ".cm-content": {
      padding: "16px",
      caretColor: "#e2e8f0",
    },
    ".cm-cursor": {
      borderLeftColor: "#e2e8f0",
    },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
      backgroundColor: "#334155",
    },
    ".cm-activeLine": {
      backgroundColor: "#1e293b40",
    },
    ".cm-gutters": {
      backgroundColor: "transparent",
      color: "#475569",
      border: "none",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "transparent",
      color: "#94a3b8",
    },
    ".cm-lineNumbers .cm-gutterElement": {
      padding: "0 8px 0 12px",
      minWidth: "32px",
    },
    ".cm-scroller": {
      overflow: "auto",
    },
    ".cm-placeholder": {
      color: "#475569",
      fontStyle: "italic",
    },
    /* Search panel */
    ".cm-panels": {
      backgroundColor: "#1e293b",
      color: "#e2e8f0",
      borderBottom: "1px solid #334155",
    },
    ".cm-panels input, .cm-panels button": {
      color: "#e2e8f0",
    },
    ".cm-searchMatch": {
      backgroundColor: "#854d0e60",
      outline: "1px solid #a16207",
    },
    ".cm-searchMatch.cm-searchMatch-selected": {
      backgroundColor: "#854d0e90",
    },
    /* Diff review decorations */
    ".cm-diff-add": {
      backgroundColor: "rgba(34, 197, 94, 0.2)",
      borderBottom: "1px solid rgba(34, 197, 94, 0.4)",
    },
    ".cm-diff-remove": {
      backgroundColor: "rgba(239, 68, 68, 0.2)",
      textDecoration: "line-through",
      color: "#f87171",
      opacity: "0.7",
    },
  },
  { dark: true }
);

/* ── Syntax highlighting for markdown tokens ── */

const markdownHighlighting = HighlightStyle.define([
  { tag: tags.heading1, color: "#f1f5f9", fontWeight: "bold", fontSize: "1.4em" },
  { tag: tags.heading2, color: "#e2e8f0", fontWeight: "bold", fontSize: "1.2em" },
  { tag: tags.heading3, color: "#cbd5e1", fontWeight: "bold", fontSize: "1.1em" },
  { tag: tags.heading4, color: "#94a3b8", fontWeight: "bold" },
  { tag: tags.strong, color: "#f8fafc", fontWeight: "bold" },
  { tag: tags.emphasis, color: "#c4b5fd", fontStyle: "italic" },
  { tag: tags.link, color: "#818cf8", textDecoration: "underline" },
  { tag: tags.url, color: "#6366f1" },
  { tag: tags.monospace, color: "#34d399", backgroundColor: "#1e293b", padding: "1px 4px", borderRadius: "3px" },
  { tag: tags.quote, color: "#94a3b8", fontStyle: "italic", borderLeft: "2px solid #475569" },
  { tag: tags.list, color: "#f59e0b" },
  { tag: tags.processingInstruction, color: "#475569" }, // markdown markers like #, *, -
]);

/**
 * MarkdownEditor — shared CodeMirror 6 markdown editing component.
 *
 * Props:
 *   value        - string content
 *   onChange      - (newValue: string) => void
 *   readOnly     - boolean (default false)
 *   placeholder  - placeholder text
 *   showLineNumbers - show gutter line numbers (default false)
 *   className    - additional CSS classes on the wrapper div
 *   onSelectionChange - (selectedText: string) => void, called when selection changes
 *   onEditorReady - (view: EditorView) => void, called once when editor mounts
 *   diffHighlights - Array<{from, to, type: 'add'|'remove'}> for inline diff review
 */
export default function MarkdownEditor({
  value = "",
  onChange,
  readOnly = false,
  placeholder = "Start writing...",
  showLineNumbers = false,
  className = "",
  onSelectionChange,
  onEditorReady,
  diffHighlights,
}) {
  const containerRef = useRef(null);
  const viewRef = useRef(null);
  const onChangeRef = useRef(onChange);
  const onSelectionChangeRef = useRef(onSelectionChange);
  const syncingRef = useRef(false); // suppress onChange during programmatic value syncs

  // Keep callback refs current without rebuilding the editor
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  useEffect(() => { onSelectionChangeRef.current = onSelectionChange; }, [onSelectionChange]);

  // Create the editor once on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const extensions = [
      darkTheme,
      syntaxHighlighting(markdownHighlighting),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      markdown({ base: markdownLanguage }),
      bracketMatching(),
      highlightSelectionMatches(),
      keymap.of([...defaultKeymap, indentWithTab, ...searchKeymap]),
      EditorView.lineWrapping,
      diffHighlightField,
      // Dispatch listener for content changes + selection changes
      EditorView.updateListener.of((update) => {
        if (update.docChanged && !syncingRef.current) {
          const newVal = update.state.doc.toString();
          onChangeRef.current?.(newVal);
        }
        if (update.selectionSet || update.docChanged) {
          const sel = update.state.selection.main;
          const selectedText = sel.empty ? "" : update.state.sliceDoc(sel.from, sel.to);
          onSelectionChangeRef.current?.(selectedText);
        }
      }),
    ];

    if (showLineNumbers) {
      extensions.push(lineNumbers());
    }

    if (placeholder) {
      extensions.push(cmPlaceholder(placeholder));
    }

    if (readOnly) {
      extensions.push(EditorState.readOnly.of(true));
    }

    const state = EditorState.create({
      doc: value,
      extensions,
    });

    const view = new EditorView({
      state,
      parent: containerRef.current,
    });

    viewRef.current = view;
    onEditorReady?.(view);

    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Only run on mount — value/readOnly updates handled via transactions below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync external value changes into the editor (e.g. doc reload after save)
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const currentValue = view.state.doc.toString();
    if (value !== currentValue) {
      syncingRef.current = true;
      view.dispatch({
        changes: { from: 0, to: currentValue.length, insert: value },
      });
      syncingRef.current = false;
    }
  }, [value]);

  // Apply diff highlight decorations when diffHighlights prop changes
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      effects: setDiffHighlights.of(diffHighlights || []),
    });
  }, [diffHighlights]);


  return (
    <div
      ref={containerRef}
      className={`flex-1 min-h-0 overflow-hidden ${className}`}
    />
  );
}

/**
 * Get the currently selected text from an editor view.
 * Useful for "Quote to Chat" style features.
 */
export function getSelection(view) {
  if (!view) return "";
  const sel = view.state.selection.main;
  return sel.empty ? "" : view.state.sliceDoc(sel.from, sel.to);
}
