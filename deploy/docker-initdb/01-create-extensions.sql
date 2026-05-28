-- =============================================================================
-- Docker init — runs ONCE when the Postgres data volume is first created.
-- =============================================================================
-- The official postgres image executes every *.sql / *.sh file in
-- /docker-entrypoint-initdb.d/ at first DB initialization, as the postgres
-- superuser, against the database specified by POSTGRES_DB.
--
-- We use that hook to install pgvector — it requires superuser, so doing it
-- here means the user (skipperbot_user, set by POSTGRES_USER) can use vector
-- types without ever needing to run a manual CREATE EXTENSION command.
--
-- Native installs handle this in step 3 of docs/01-base-platform-setup.md.

CREATE EXTENSION IF NOT EXISTS vector;
