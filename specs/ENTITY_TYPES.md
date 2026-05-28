# Skipperbot — Entity Types

> **Placeholder.** Full content lands in Chunk 2+.

## Scope

Every entity in Skipperbot has a prefixed ID (`re-1234abcd`, `g-89efabcd`, etc.).
Prefixes are registered in `public.entity_types` at load time.

Coverage:

- The `public.entity_types` table (prefix, name, table, app_id).
- How an app declares its prefixes in `manifest.yaml`:
  ```yaml
  entity_types:
    - prefix: re
      name: Recipe
      table: recipes
  ```
- ID generation pattern: `f"{prefix}-{uuid.uuid4().hex[:8]}"`.
- How `platform.links` uses the prefix to resolve which schema and table the target lives in.
- Prefix conflicts — the loader fails loudly if two apps claim the same prefix.
- Platform-owned prefixes (`m-` memory, `k-` knowledge, `a-` artifact, etc.).
- App-owned prefixes (`re-` recipe, `mp-` meal plan, `veh-` vehicle, etc.).
- The chat agent's awareness of entity types and how it parses references.
