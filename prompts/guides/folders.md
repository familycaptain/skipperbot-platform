# Folders Guide

## What Are Folders?

Folders (`fld-*`) organize **documents** (`d-*`) and **artifacts** (`a-*`) into named collections.
They can be nested (subfolders), owned by a specific user or shared, and linked to other entities.

**Key feature: Folder Intelligence.** When content is added to a folder, Skipper automatically
extracts facts and creates embeddings — making everything in folders searchable by meaning
and recallable during future conversations.

## Creating Folders

- "Create a folder for tax documents" → create_folder(name="Tax Documents")
- "Make a medical folder for Eve" → create_folder(name="Eve Medical", owner="eve")
- "Create a subfolder for 2026 returns inside the tax folder" → create_folder(name="2026 Returns", parent_folder="fld-...")

## Adding Content to Folders

Two workflows:

**Add existing content:**
- "Put that document in the medical folder" → add_to_folder(folder_id="fld-...", entity_id="d-...")
- "File the PDF in the tax folder" → add_to_folder(folder_id="fld-...", entity_id="a-...")

**Create new document in folder:**
- "Write up Eve's ER visit and put it in the medical folder" → create_doc_in_folder(folder_id="fld-...", title="Eve ER Visit", content="...")
- "Create a new document in the investment folder" → create_doc_in_folder(folder_id="fld-...", title="...")

Prefer `create_doc_in_folder` when the user wants to create AND file in one step.

## Browsing & Searching

- "Show me all folders" → list_folders()
- "What's in the medical folder?" → get_folder(folder_id="fld-...")
- "Show Alice's folders" → list_folders(owner="alice")
- "Search folders for tax" → search_folders(query="tax")

## Moving & Removing

- "Move the W-2 doc from tax to the 2026 subfolder" → move_to_folder(entity_id="d-...", from_folder="fld-...", to_folder="fld-...")
- "Remove the old receipt from the tax folder" → remove_from_folder(folder_id="fld-...", entity_id="a-...")
  - Note: this does NOT delete the document/artifact, just removes it from the folder

## Folder Intelligence

When content is added to a folder, the intelligence pipeline automatically:
1. Chunks the raw text and creates embeddings for semantic search
2. Extracts structured facts via LLM (who, what, when, where, details)
3. Makes everything searchable and recallable during chat

**This means:** If a user files a document about Eve's allergies in the medical folder,
Skipper can later answer "What are Eve's food allergies?" from the extracted facts —
even months later.

Editing a document that lives in a folder triggers re-processing after a 5-minute debounce.

## Ownership & Visibility

- All folders are visible to everyone ("no secrets")
- `owner` is for filtering ("show me MY folders"), not access control
- Leave owner empty for shared/family folders

## Natural Language Patterns

- "create a folder for X" / "make a folder called X" → create_folder
- "put this in the X folder" / "file this in X" / "add to the X folder" → add_to_folder
- "write up X and put it in the Y folder" → create_doc_in_folder
- "show me the X folder" / "what's in X?" → get_folder
- "show all folders" / "my folders" → list_folders
- "move this to the X folder" → move_to_folder
- "take this out of the folder" → remove_from_folder
- "delete the X folder" → delete_folder (contents preserved)
- "search folders for X" → search_folders
