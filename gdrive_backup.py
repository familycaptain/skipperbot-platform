"""Google Drive Backup — Upload backup artifacts to Skipper's Google Drive.

Uses a GCP service account with domain-wide delegation to impersonate
Skipper's Google Workspace account.  Files are uploaded to a
"Backups/<date>" folder and count against Skipper's Drive quota.

Env vars:
    BACKUP_GOOGLE_KEY_FILE   — path to the service account JSON key file
    GDRIVE_IMPERSONATE_EMAIL — Skipper's Workspace email to impersonate
"""

import os
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_FOLDER_NAME = "Backups"


def _build_service():
    """Build a Google Drive API service via service account with delegation."""
    key_file = os.getenv("BACKUP_GOOGLE_KEY_FILE", "").strip()
    impersonate_email = os.getenv("GDRIVE_IMPERSONATE_EMAIL", "").strip()

    if not key_file:
        return None
    if not os.path.isfile(key_file):
        logger.error("GDRIVE: Key file not found: %s", key_file)
        return None
    if not impersonate_email:
        logger.error("GDRIVE: GDRIVE_IMPERSONATE_EMAIL not set")
        return None

    creds = Credentials.from_service_account_file(key_file, scopes=SCOPES)
    creds = creds.with_subject(impersonate_email)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_folder(service, folder_name: str) -> str | None:
    """Find a shared folder by name. Returns folder ID or None."""
    resp = service.files().list(
        q=f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    return None


def _find_or_create_subfolder(service, parent_id: str, name: str) -> str:
    """Find or create a subfolder inside parent_id."""
    resp = service.files().list(
        q=f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=5,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    # Create it
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _upload_file(service, folder_id: str, local_path: str, dest_name: str) -> dict:
    """Upload a file into a Drive folder. Returns file metadata."""
    media = MediaFileUpload(local_path, resumable=True)
    meta = {"name": dest_name, "parents": [folder_id]}
    f = service.files().create(body=meta, media_body=media, fields="id,name,size").execute()
    return f


def upload_backup_to_gdrive(
    date_str: str,
    dump_file: str,
    zip_file: str,
    restore_file: str,
) -> dict:
    """Upload backup artifacts to Google Drive / Backups / <date_str>.

    Returns dict with status info. Non-fatal — logs warnings on failure.
    """
    service = _build_service()
    if service is None:
        logger.info("GDRIVE: Skipping upload — BACKUP_GOOGLE_KEY_FILE not configured")
        return {"status": "skipped", "reason": "not configured"}

    try:
        # Find the shared Backups folder
        root_id = _find_folder(service, DRIVE_FOLDER_NAME)
        if not root_id:
            logger.error("GDRIVE: Shared '%s' folder not found — is it shared with the service account?", DRIVE_FOLDER_NAME)
            return {"status": "error", "reason": f"'{DRIVE_FOLDER_NAME}' folder not found"}

        # Create date subfolder
        date_folder_id = _find_or_create_subfolder(service, root_id, date_str)
        logger.info("GDRIVE: Uploading to %s/%s (folder_id=%s)", DRIVE_FOLDER_NAME, date_str, date_folder_id)

        # Upload each file
        uploaded = []
        for local_path, dest_name in [
            (dump_file, "skipperbot_db.dump"),
            (zip_file, "skipperbot_files.zip"),
            (restore_file, "RESTORE.md"),
        ]:
            if not os.path.isfile(local_path):
                logger.warning("GDRIVE: File not found, skipping: %s", local_path)
                continue
            size = os.path.getsize(local_path)
            logger.info("GDRIVE: Uploading %s (%.1f MB)...", dest_name, size / 1048576)
            result = _upload_file(service, date_folder_id, local_path, dest_name)
            uploaded.append({"name": dest_name, "id": result["id"], "size": size})
            logger.info("GDRIVE: Uploaded %s → %s", dest_name, result["id"])

        # Prune old date folders beyond retention
        _prune_gdrive_folders(service, root_id)

        return {"status": "ok", "folder_id": date_folder_id, "files": uploaded}

    except Exception as e:
        logger.error("GDRIVE: Upload failed — %s", e)
        return {"status": "error", "reason": str(e)[:500]}


def _prune_gdrive_folders(service, root_id: str, keep: int = 0):
    """Remove old date-named subfolders beyond retention.

    Uses BACKUP_RETENTION env var (default 5).
    """
    import re
    keep = int(os.getenv("BACKUP_RETENTION", "5"))

    resp = service.files().list(
        q=f"'{root_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=100,
    ).execute()

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    folders = sorted(
        [f for f in resp.get("files", []) if date_pattern.match(f["name"])],
        key=lambda f: f["name"],
        reverse=True,
    )

    if len(folders) <= keep:
        return

    for folder in folders[keep:]:
        try:
            service.files().delete(fileId=folder["id"]).execute()
            logger.info("GDRIVE: Pruned old backup folder %s", folder["name"])
        except Exception as e:
            logger.warning("GDRIVE: Failed to prune %s: %s", folder["name"], e)
