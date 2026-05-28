# Documents Guide

## What Are Docs?

Documents (`d-*`) are **living markdown knowledge pages** — first-class entities that are
tagged, full-text searchable, and designed to be curated over time.

Unlike artifacts (opaque file attachments), docs are always markdown, always searchable,
and meant to evolve as knowledge grows.

| | Artifact (`a-*`) | Document (`d-*`) |
|---|---|---|
| **Content** | Any file type | Markdown only |
| **Searchable** | By metadata/tags | Full-text content search |
| **Lifecycle** | Upload once | Edit/append over time |
| **Standalone?** | Needs a parent entity | Yes, first-class |
| **Purpose** | "Attach the mockup" | "Create a research page on X" |

## Creating Documents

- "Write up what we found about solar panels" → create_doc(title, created_by, content, tags)
- "Create a doc for this project" → create_doc(title, created_by, related_entity_id="p-...")
- Tags are comma-separated: "research,solar,home-improvement"

## Reading & Searching

- "Show me the solar research doc" → get_doc(doc_id)
- "Search docs for solar panel costs" → search_docs(query="solar panel costs")
- "List all research docs" → list_docs(tag="research")
- "What docs are linked to the home project?" → list_docs(related_entity_id="p-...")

## Editing Documents

- **Full replace**: update_doc(doc_id, content, updated_by) — rewrites the whole doc
- **Append**: append_to_doc(doc_id, content, updated_by) — adds to the end (preferred for incremental work)
- **Metadata only**: update_doc_meta(doc_id, updated_by, title, tags, related_entity_id)

Prefer `append_to_doc` when adding new sections or findings. Use `update_doc` only when
restructuring the entire document.

## Research Workflow

When asked to research a topic:

1. **Create the doc** first: `create_doc("Solar Panel Options", "alice", tags="research,solar")`
2. **Search the web**: use `internet_search` to find sources
3. **Read sources**: use `curl_request` to fetch page content
4. **Curate findings**: use `append_to_doc` to add summaries, links, tables, key data
5. **Link to project** (if applicable): `update_doc_meta(doc_id, related_entity_id="p-...")`

Structure research docs with clear sections:

```markdown
# Solar Panel Options

## Sources
- [Source 1](url) — summary of what was found
- [Source 2](url) — summary

## Key Findings
- Finding 1
- Finding 2

## Cost Comparison
| Option | Cost | Notes |
|--------|------|-------|
| ...    | ...  | ...   |

## Recommendations
- ...

## Next Steps
- [ ] Get quotes from local installers
- [ ] Check HOA requirements
```

## Linking Docs to Projects

Docs can be linked to any entity via `related_entity_id`:
- On creation: `create_doc(title, user, related_entity_id="p-abc123")`
- After creation: `update_doc_meta(doc_id, user, related_entity_id="p-abc123")`
- The link is bidirectional via `lnk-*` with relation `has_doc`

You can also use `link_entities` for additional relationships:
- `link_entities(doc_id, "t-xyz", relation="research_for")`

## Adding a Document to a Project (as an artifact)

When a user creates a document and then asks to "add it to a project" or "attach it to
the project", they want the document's content attached as a **project artifact**.
This is a two-step process — do both automatically:

1. **Read the document**: `get_doc(doc_id)` → get the content
2. **Create an artifact on the project**: `attach_artifact(name="doc_title.md", content=doc_content, related_entity_id="p-...")`

This registers the content in the project's `artifacts[]` array so it shows up in
`list_entity_artifacts(p-*)`.

**Common phrases that trigger this:**
- "Add that document to the home improvement project"
- "Attach the solar research to project X"
- "Put that doc on the fence project"

**Do NOT just link the doc** — `link_entities` creates a cross-reference but does not
put the content into the project's artifact list. When the user says "add to project",
they want a real artifact attachment.

## Tags Best Practices

Use lowercase, hyphenated tags:
- Topic: `solar`, `home-improvement`, `project-alpha`, `family`
- Type: `research`, `meeting-notes`, `reference`, `how-to`, `decision`
- Status: `draft`, `final`, `archived`

## Enhancing Documents

Use `enhance_doc` when a user wants the AI to expand, improve, or flesh out a
document (or specific sections of it) without manually rewriting content.

**How it works:**
1. The document is split into sections by markdown headings.
2. The LLM identifies which sections are relevant to the user's instructions.
3. Only those sections are enhanced — the rest stay untouched.
4. New sections can be added if the instructions call for it.

**When to use enhance_doc vs update_doc:**
- `enhance_doc` — user wants the AI to *write* improved content ("flesh this out",
  "add more detail", "make it better")
- `update_doc` — user is providing the new content themselves ("replace the intro with this...")
- `append_to_doc` — user wants to add content to the end

**Examples:**
- "Flesh out the introduction" → enhance_doc(doc_id, "flesh out the introduction", user)
- "Add more detail about costs" → enhance_doc(doc_id, "add more detail about costs", user)
- "This doc needs a section about risks" → enhance_doc(doc_id, "add a section about risks", user)
- "Make the whole doc more detailed" → enhance_doc(doc_id, "expand all sections with more detail", user)
- "Polish up that document" → enhance_doc(doc_id, "improve clarity and polish throughout", user)

## Natural Language Patterns

- "research X" / "look into X" / "find out about X" → create doc + web search + curate
- "write up X" / "document X" / "make a doc about X" → create_doc
- "add to the X doc" / "update the research" → append_to_doc
- "find that doc about X" / "search docs for X" → search_docs
- "show me the X doc" → get_doc
- "what docs do we have?" → list_docs
- "flesh out X" / "expand X" / "add more detail" / "make it better" → enhance_doc
- "add a section about X" / "beef up the intro" / "polish that doc" → enhance_doc
- "add that to the project" / "attach it to the project" / "put that on the project" → get_doc → attach_artifact(related_entity_id=p-*)
