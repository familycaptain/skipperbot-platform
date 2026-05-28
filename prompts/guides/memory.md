# Memory Guide

## Remember with provenance
- Learn something → remember(content, tags, about, source_chat_id=c-*)
- Memory traceable back to exact conversation

## Recall
- recall(query="bob birthday", about="bob") → finds relevant memories
- recall(query="", entity_id=p-*) → all memories referencing that project

## Forget outdated info
- forget(m-*) → deletes specific memory

## Auto-memories
- System auto-creates m-* tagged [auto] on every entity CRUD operation
- Searchable: recall(query="", entity_id=t-*) returns creation, updates, status changes

## Multi-entity references
- remember(content="Decided to merge these two tasks", related_entities="t-abc,t-def", source_chat_id=c-*)

## Decision tracking pattern
1. User and agent discuss options in conversation (c-*)
2. Remember the decision (m-* with source_chat_id=c-*)
3. Link memory to affected entities via related_entities
4. Later: "Why did we choose option B?" → recall finds memory → c-* traces to conversation
