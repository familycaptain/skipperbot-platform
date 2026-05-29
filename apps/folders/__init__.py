"""Folders — required core app.

Owns the ``app_folders.folders`` / ``folder_items`` / ``folder_knowledge``
tables. Folders organize entities (docs, links, projects, etc.) into a
hierarchical tree with tags, icons, colors, soft delete, and an LLM
intelligence pipeline that extracts facts + embeddings from each
folder's contents into the ``folder_knowledge`` table.

Other apps that want to file an entity into a folder go through the
``app_platform.folders`` shim — same pattern as the previous packaged
apps. The Documents app's update hook in particular calls
``app_platform.folders.get_folders_containing(doc_id)`` to trigger
folder-intelligence reprocessing whenever a doc changes.
"""
