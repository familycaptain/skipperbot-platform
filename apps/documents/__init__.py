"""Documents — required core app.

Owns the ``app_documents.documents`` table (markdown bodies with
``vector(1536)`` embeddings for semantic search) and the LLM-driven
**document** thinking domain that organizes accumulated memories into
readable docs.

Other apps that create or read docs (research, refine, print, folders,
goals' linked docs) go through the ``app_platform.documents`` shim.
"""
