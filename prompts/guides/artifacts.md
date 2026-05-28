# Artifacts Guide

Use artifacts to attach files or documents to any entity. Provide text content directly
or reference an existing file path. Always set `related_entity_id` when the artifact
belongs to a specific goal, project, task, etc.

- Use `update_artifact` to replace an artifact's content in place (same ID, links, and
  parent registration). Prefer this over delete + recreate when refreshing content
  (e.g. re-crawl manifests, revised documents).

## Workflows

### Attach a text document to a project
- attach_artifact(name="meeting_notes.md", content="...", related_entity_id=p-*)

### Attach an existing file
- attach_artifact(name="screenshot.png", source_path="/path/to/file", related_entity_id=t-*)

### Read artifact content
- read_artifact(a-*) → returns text content (or binary notice)

### List all artifacts for an entity
- list_entity_artifacts(related_entity_id=p-*) → all files attached to that project

### Delete an artifact
- delete_artifact_by_id(a-*)

## Document → Artifact (adding a doc to a project)

When a user creates a document (`d-*`) and asks to "add it to a project", automatically:
1. `get_doc(doc_id)` → read the document content
2. `attach_artifact(name="doc_title.md", content=doc_content, related_entity_id="p-...")`

This puts the content into the project's `artifacts[]` array. Do NOT just use
`link_entities` — that only creates a cross-reference, not a real artifact attachment.

## Combination Patterns

### Artifact handoff between entities
1. Create artifact on project A (a-* related to p-A)
2. Link artifact to project B (link_entities a-*, p-B, relation="shared_doc")
3. Both projects can discover the artifact via get_entity_links

### Artifact version tracking
1. Attach initial version (a-1 on p-*)
2. Attach updated version (a-2 on p-*)
3. Link a-1 and a-2 (lnk-* relation="superseded_by")
4. Remember why the update was made (m-* with related_entities=[a-1, a-2])
