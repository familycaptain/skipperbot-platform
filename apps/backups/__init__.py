"""Backups app.

Owns the ``app_backups.backups`` audit table and the backup runner
that produces three artifacts per run — a ``pg_dump`` of the
database, a project zip, and a ``RESTORE.md`` set of recovery
instructions — and optionally copies them to one or more
destinations.

Two destinations are supported and are *independently* toggled via
the manifest's ``config:`` schema:

- **Filesystem** (``filesystem_enabled`` + ``filesystem_path``) — copy
  artifacts under a local path / mounted network share.
- **Google Drive** (``gdrive_enabled`` + ``gdrive_key_file`` +
  ``gdrive_impersonate_email``) — upload to a shared "Backups/<date>"
  folder via a service account with domain-wide delegation.

If neither destination is enabled, the runner still writes a DB
audit row and produces the artifacts in a staging directory, but
nothing is persisted off-machine — useful for testing the dump
path without standing up a destination. If the whole app is
disabled (``enabled=false``), scheduled job runs short-circuit
with a ``skipped`` status; on-demand runs still execute so the
user can produce a one-off artifact.

Required core app per the open-source release plan, but the
platform must still boot cleanly when neither destination is
configured — every cross-app caller goes through
``app_platform.backups``.
"""
