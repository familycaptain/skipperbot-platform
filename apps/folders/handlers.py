"""Folders — event + job-handler registrations.

Registers the ``folder_intelligence`` job handler with the platform
jobs dispatcher so the runner can fire it whenever a folder item
changes. The doc-update hook in ``apps.documents.store`` submits
these jobs through ``app_platform.jobs.submit_job`` and the folder
store's intelligence-trigger does the same when items are added or
moved.

Handler config (set by ``submit_job``)::

    {"folder_id": "fld-…", "entity_id": "d-… | a-…"}
"""

from __future__ import annotations

from app_platform.jobs import register_handler, JobContext
from apps.folders.intelligence import process_folder_item


def _handle_folder_intelligence(job: dict, ctx: JobContext) -> str:
    """Run the folder intelligence pipeline for one folder/item pair.

    Sync — runs in the dispatcher's thread pool.
    """
    config = job.get("config") or {}
    folder_id = config.get("folder_id", "")
    entity_id = config.get("entity_id", "")
    if not folder_id or not entity_id:
        return "Missing folder_id or entity_id in job config"
    ctx.update_progress(10, f"Processing {entity_id} in {folder_id}...")
    result = process_folder_item(folder_id, entity_id)
    if result.get("error") and result["error"] != "skipped:unchanged":
        return f"Failed: {result['error']}"
    return f"Done: {result['chunks']} chunks, {result['facts']} facts"


register_handler(
    "folder_intelligence", _handle_folder_intelligence,
    max_concurrent=2, cancel_on_shutdown=True,
)
