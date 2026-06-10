# Knowledge Base Guide

Use `learn_from_url` to ingest web content into the knowledge base. Each page becomes a
`k-*` source. Use `query_knowledge` to search across all ingested content.

- **Crawl manifests:** When using `follow_links=true`, a `kc-*` crawl manifest is
  automatically created grouping all ingested pages. On re-crawl of the same URL, the
  existing manifest is updated in place (same `kc-*` ID).
- Use `get_knowledge_crawl` to retrieve the full manifest content (crawl ID, stats, all
  source URLs). This is the content to use when creating or updating an artifact for the crawl.
- If an artifact for the crawl already exists on the project, use `update_artifact` to
  refresh it rather than creating a duplicate.

## Workflows

### Ingest a website
- "Learn about example.com" → learn_from_url(url) → creates k-* source, chunks content, embeds

### Re-ingest (refresh content)
- Same URL re-ingested → old source removed, new k-* created

### Crawl with follow_links
- learn_from_url(url, follow_links=True) → ingests main page + linked subpages

### Search knowledge
- "What enemies are in the jungle?" → query_knowledge or auto-injected into chat context

### Link knowledge to a goal
- link_entities(k-*, g-*, relation="reference") → wiki content tied to game dev goal

### List all knowledge sources
- list_knowledge_sources → shows all ingested URLs with chunk counts

## Combination Patterns

### Research workflow
1. Create goal: "Research new HVAC system" (g-*)
2. Ingest manufacturer websites (k-*)
3. Link knowledge sources to goal (lnk-*)
4. Summarize findings → attach as artifact (a-* on g-*)
5. Remember key decisions (m-* with related_entities=[g-*])

### Knowledge-informed task creation
1. Ingest documentation website (k-*)
2. Search knowledge for setup steps
3. Create tasks (t-*) based on documented steps
4. Link knowledge source to parent project (lnk-*)
