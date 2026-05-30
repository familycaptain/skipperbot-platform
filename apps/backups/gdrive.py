"""Backups — Google Drive destination.

Optional destination that uploads each backup's three artifacts into
a shared "Backups/<date>" folder on Google Drive via a service
account with domain-wide delegation. Files count against the
impersonated Workspace user's Drive quota.

Configuration (all in ``scope='app:backups'``):

- ``gdrive_enabled`` — boolean toggle.
- ``gdrive_service_account_json`` — service-account JSON content (secret, Settings → Backups).
- ``gdrive_impersonate_email`` — the Workspace account to impersonate.

If the toggle is off or either string is empty, ``upload_to_gdrive``
returns ``{"status": "skipped", "reason": "..."}`` and the rest of
the backup run carries on. If imports fail (the
``google-api-python-client`` package isn't installed), we
gracefully report ``skipped`` rather than crashing — backups should
work even when this optional integration isn't available.
"""

from __future__ import annotations

import logging
import os
import re

from app_platform import config as platform_config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_FOLDER_NAME = "Backups"


def _config(key: str, default=None):
    return platform_config.get(key, default, scope="app:backups")


def _build_service():
    """Build a Google Drive API service via service account with delegation.

    Returns the service object on success, or ``None`` (with a logged
    reason) if the destination is disabled or misconfigured.
    """
    if not _config("gdrive_enabled", False):
        return None

    # Service-account JSON is pasted into Settings → Backups (encrypted at
    # rest); no key file on disk. Same creds the skipper-email sender uses.
    from app_platform import settings as _settings
    raw = _settings.get("gdrive_service_account_json", scope="app:backups", secret=True, default="") or ""
    impersonate_email = (_config("gdrive_impersonate_email", "") or "").strip()

    if not raw.strip():
        logger.warning("GDRIVE: enabled but gdrive_service_account_json is empty — skipping")
        return None
    if not impersonate_email:
        logger.warning("GDRIVE: enabled but gdrive_impersonate_email is empty — skipping")
        return None

    try:
        import json
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        logger.warning("GDRIVE: google-api-python-client not installed (%s) — skipping", e)
        return None

    try:
        info = json.loads(raw)
    except (ValueError, TypeError) as e:
        logger.error("GDRIVE: gdrive_service_account_json is not valid JSON (%s) — skipping", e)
        return None

    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    creds = creds.with_subject(impersonate_email)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_folder(service, folder_name: str) -> str | None:
    resp = service.files().list(
        q=f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _find_or_create_subfolder(service, parent_id: str, name: str) -> str:
    resp = service.files().list(
        q=f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=5,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _upload_file(service, folder_id: str, local_path: str, dest_name: str) -> dict:
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(local_path, resumable=True)
    meta = {"name": dest_name, "parents": [folder_id]}
    return service.files().create(body=meta, media_body=media, fields="id,name,size").execute()


def upload_to_gdrive(
    date_str: str,
    dump_file: str,
    zip_file: str,
    restore_file: str,
    retention: int = 5,
) -> dict:
    """Upload backup artifacts to Google Drive / Backups / <date_str>.

    Returns dict with status info. Non-fatal — logs warnings on failure
    so one bad destination doesn't poison the whole backup run.
    """
    service = _build_service()
    if service is None:
        return {"status": "skipped", "reason": "destination disabled or not configured"}

    try:
        root_id = _find_folder(service, DRIVE_FOLDER_NAME)
        if not root_id:
            logger.error(
                "GDRIVE: shared '%s' folder not found — is it shared with the service account?",
                DRIVE_FOLDER_NAME,
            )
            return {"status": "error", "reason": f"'{DRIVE_FOLDER_NAME}' folder not found"}

        date_folder_id = _find_or_create_subfolder(service, root_id, date_str)
        logger.info(
            "GDRIVE: Uploading to %s/%s (folder_id=%s)",
            DRIVE_FOLDER_NAME, date_str, date_folder_id,
        )

        uploaded = []
        for local_path, dest_name in [
            (dump_file, "skipperbot_db.dump"),
            (zip_file, "skipperbot_files.zip"),
            (restore_file, "RESTORE.md"),
        ]:
            if not os.path.isfile(local_path):
                logger.warning("GDRIVE: file not found, skipping: %s", local_path)
                continue
            size = os.path.getsize(local_path)
            logger.info("GDRIVE: Uploading %s (%.1f MB)...", dest_name, size / 1048576)
            result = _upload_file(service, date_folder_id, local_path, dest_name)
            uploaded.append({"name": dest_name, "id": result["id"], "size": size})
            logger.info("GDRIVE: Uploaded %s → %s", dest_name, result["id"])

        _prune_gdrive_folders(service, root_id, keep=retention)

        return {"status": "ok", "folder_id": date_folder_id, "files": uploaded}

    except Exception as e:
        logger.error("GDRIVE: upload failed — %s", e)
        return {"status": "error", "reason": str(e)[:500]}


def _prune_gdrive_folders(service, root_id: str, keep: int = 5):
    """Remove old date-named subfolders beyond retention."""
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
            logger.info("GDRIVE: pruned old backup folder %s", folder["name"])
        except Exception as e:
            logger.warning("GDRIVE: failed to prune %s: %s", folder["name"], e)
