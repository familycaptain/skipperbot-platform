"""Bound test for CROSS-CUTTING.md §4 — stored text must not reach the DOM as markup.

Six app UIs interpolate stored text into HTML: three render markdown through
`dangerouslySetInnerHTML` in the main window, three build a print document for
`document.write()` on a `window.open("")` page, which inherits this origin. In every case the
text can come from outside the household — pages the document curator fetched, recipe text the
model was told to "parse aggressively", Trello card names synced in — so markup in a field would
execute as script with the signed-in user's session.

This asserts the shape of the fix rather than the absence of a sink, because the sinks are
legitimate: markdown rendering and printing both have to emit HTML. What must hold is that the
untrusted text is escaped BEFORE the transforms run (so markdown still works and only literal
angle brackets stop being markup), and that hrefs built from stored URLs are scheme-checked.

The behaviour itself is covered offline by the harness in the audit; this test guards the seam so
a seventh instance cannot appear without someone noticing.
"""
import os
import re
import unittest

def _repo_root():
    """Walk up to the repo root rather than counting directories.

    Counting `dirname()` levels breaks the moment a test file moves — which is exactly what
    happened to this file when the tests were re-homed by subject.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("could not locate the repo root from " + __file__)


REPO = _repo_root()

# Renders markdown into dangerouslySetInnerHTML — must escape its source and guard link schemes.
MARKDOWN_RENDERERS = [
    "apps/documents/ui/DocumentEditor.jsx",
    "apps/timeline/ui/TimelineApp.jsx",
    "apps/brainstorming/ui/BrainstormDetailApp.jsx",
]

# Builds a document for document.write() — must escape every interpolated field.
PRINT_BUILDERS = [
    "apps/recipes/ui/RecipeDetailApp.jsx",
    "apps/todo/ui/TodoApp.jsx",
    "apps/lists/ui/ListsApp.jsx",
]


def _read(rel):
    with open(os.path.join(REPO, rel), "r", encoding="utf-8") as fh:
        return fh.read()


class MarkdownRenderersEscapeTheirSource(unittest.TestCase):
    def test_source_is_escaped_before_any_transform(self):
        for rel in MARKDOWN_RENDERERS:
            src = _read(rel)
            self.assertIn(
                "md = escapeHtml(md);", src,
                f"{rel}: markdownToHtml must escape its SOURCE before transforming. Escaping only "
                f"the code-fence branch leaves headings, paragraphs, list items and links raw.")

    def test_code_fence_is_not_escaped_twice(self):
        # The fence branch used to escape on its own; with the source escaped up front, escaping
        # again renders "&amp;lt;" to the reader inside code blocks.
        for rel in MARKDOWN_RENDERERS:
            self.assertNotIn(
                "escapeHtml(code.trim())", _read(rel),
                f"{rel}: double-escapes code fences")

    def test_link_hrefs_are_scheme_checked(self):
        # Escaping the text does not stop a javascript: URL, because the URL is consumed as an
        # attribute rather than as text.
        for rel in MARKDOWN_RENDERERS:
            src = _read(rel)
            self.assertIn("function safeUrl", src, f"{rel}: no href scheme guard")
            # A raw `href="$N"` is only acceptable when the pattern on that same line constrains
            # the scheme itself — which the bare-URL autolink does (it matches `https?://`).
            for i, line in enumerate(src.splitlines(), 1):
                if re.search(r'href="\$\d"', line) and "https?:" not in line:
                    self.fail(f"{rel}:{i}: href interpolated with no scheme guard — "
                              f"{line.strip()[:120]}")


class PrintBuildersEscapeEveryField(unittest.TestCase):
    def test_an_escape_helper_exists(self):
        for rel in PRINT_BUILDERS:
            self.assertIn(
                "const esc = (v)", _read(rel),
                f"{rel}: builds a document.write() page with no escape helper")

    def test_no_bare_field_interpolation_in_the_written_document(self):
        # Every ${...} inside the print document must be esc()'d, a computed number, or a piece
        # already assembled from escaped parts.
        allowed = re.compile(
            r"\besc\b|\bidx\b|\bi \+ 1\b|\btotal\b|\bmeta\b|\bcats\b|\bchef\b|\bsource\b|"
            r"\bingredients\b|\bsteps\b|\brows\b|\bmetaParts\b|\bactiveItems\b|\bparts\.join\b|"
            r"new Date\(\)|\.length|\bnow\b")  # `now` is a locally formatted date, not stored text
        for rel in PRINT_BUILDERS:
            src = _read(rel)
            # The print block runs from the escape helper (placed immediately above it) to the
            # print() call. Scoping to exactly that avoids matching unrelated template literals
            # elsewhere in the same component.
            start = src.find("const esc = (v)")
            end = src.find("win.print()", start)
            self.assertGreater(start, 0, f"{rel}: no escape helper found")
            self.assertGreater(end, start, f"{rel}: no win.print() after the escape helper")
            for expr in re.findall(r"\$\{([^}]{1,80})\}", src[start:end]):
                if not allowed.search(expr):
                    self.fail(f"{rel}: unescaped interpolation in the printed document: ${{{expr}}}")


if __name__ == "__main__":
    unittest.main()
