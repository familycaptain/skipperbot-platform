# Writing an app's `help.md` (the user manual)

Every app ships **two** docs, and they are NOT the same:

| File | Audience | Purpose |
|---|---|---|
| `apps/<id>/guide.md` | **The agent** | How to operate the app's tools — tool names, arguments, edge cases, routing. Detailed, often several pages. Loaded into the model's context when the app is relevant. |
| `apps/<id>/help.md` | **The user** | A comprehensive **user manual**, shown in-app via the **?** button (a full-width, scrollable panel) and returned by the `get_app_help` chat tool. |

**`help.md` is a full manual, not a blurb.** A one-paragraph summary is not enough.
If the only place a capability is documented for users is `guide.md`, the agent
ends up improvising user help from the agent guide — we don't want that. Pre-write
the real user content here.

## Required structure

Write `help.md` with these sections (in this order). Match the depth of the
app — a tiny app's manual is shorter, but it still has all the parts.

1. **`# <App Name>`** + a one-line summary of what it's for.
2. **`## Overview`** — what the app does and when you'd reach for it, in plain
   language (2–4 short paragraphs).
3. **`## Screens`** (or `## Using <App>`) — walk through each screen/area of the
   UI: what's on it, what each control does, what the user sees.
4. **`## Example workflows`** — several concrete, step-by-step tasks. For each,
   show **both** ways to do it:
   - **In the app:** the click-by-click path.
   - **Through chat:** what to say to Skipper (e.g. *"log an oil change for the
     Honda at 92,000 miles"*). Everything the UI does should be doable in chat.
5. **`## Tips`** — gotchas, shortcuts, and how it pairs with other apps.
6. **`## Your data`** — **REQUIRED, near-verbatim, in every app's help.md:**
   > **Your data.** Everything you enter here is saved as a record in the
   > database **and** pulled into Skipper's memory — so later you can just ask in
   > chat (e.g. "what did I log last week?") and Skipper recalls it. Nothing is
   > shared outside your household.

   (Adjust the example to the app. If an app genuinely stores nothing — e.g. the
   Calculators or Weather app — say that instead: "This app stores nothing.")

## Style
- User-facing voice. No tool names, function signatures, or internal IDs (those
  belong in `guide.md`).
- Use real examples with concrete values.
- Comprehensive but not padded — every line earns its place.
- It renders as Markdown in a scrollable panel, so headings, lists, and tables
  are all fine and encouraged for scannability.

## Tip for filling these in across apps
`guide.md` already contains the per-feature knowledge — translate the
user-relevant parts into plain language here, add the click-by-click screen
walkthrough and the example workflows, and always include the **Your data**
section.
