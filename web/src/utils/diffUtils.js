/**
 * Diff utilities for brainstorming inline diff review.
 *
 * Takes diff-match-patch output (array of [op, text] tuples) and produces:
 * - mergedText: a single string with both additions and deletions inline
 * - highlights: array of {from, to, type: 'add'|'remove'} for CodeMirror decorations
 *
 * Op codes: 0 = equal, 1 = insert, -1 = delete
 */

/**
 * Build a merged document and highlight ranges from diff-match-patch output.
 *
 * @param {Array<[number, string]>} diffs - diff-match-patch diffs
 * @returns {{ mergedText: string, highlights: Array<{from: number, to: number, type: string}> }}
 */
export function buildMergedView(diffs) {
  let mergedText = "";
  const highlights = [];
  let pos = 0;

  for (const [op, text] of diffs) {
    if (op === 0) {
      // Unchanged text — just append
      mergedText += text;
      pos += text.length;
    } else if (op === 1) {
      // Addition — show in green
      mergedText += text;
      highlights.push({ from: pos, to: pos + text.length, type: "add" });
      pos += text.length;
    } else if (op === -1) {
      // Deletion — show in red with strikethrough
      mergedText += text;
      highlights.push({ from: pos, to: pos + text.length, type: "remove" });
      pos += text.length;
    }
  }

  return { mergedText, highlights };
}

/**
 * Extract just the "revised" text from diffs (original without deletions, with additions).
 * @param {Array<[number, string]>} diffs
 * @returns {string}
 */
export function getRevisedText(diffs) {
  return diffs
    .filter(([op]) => op !== -1)
    .map(([, text]) => text)
    .join("");
}

/**
 * Extract just the "original" text from diffs (without additions).
 * @param {Array<[number, string]>} diffs
 * @returns {string}
 */
export function getOriginalText(diffs) {
  return diffs
    .filter(([op]) => op !== 1)
    .map(([, text]) => text)
    .join("");
}

/**
 * Count additions and deletions.
 * @param {Array<[number, string]>} diffs
 * @returns {{ additions: number, deletions: number }}
 */
export function countChanges(diffs) {
  let additions = 0;
  let deletions = 0;
  for (const [op] of diffs) {
    if (op === 1) additions++;
    if (op === -1) deletions++;
  }
  return { additions, deletions };
}
