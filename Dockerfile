# =============================================================================
# Skipperbot Platform — Dockerfile
# =============================================================================
# Single supported Python version: 3.12.
#
# Image bakes in the platform code, required apps, and an initial web bundle
# so a fresh `docker compose up` boots fast. At runtime, docker-compose
# bind-mounts ./apps and ./web/dist from the host so the user can install
# optional apps with `cd apps && git clone ...` and the entrypoint script
# rebuilds the web bundle in place if it detects new app UI components.

# Pin to Debian Bookworm explicitly. `python:3.12-slim` floats — when
# the upstream rolled to Debian Trixie (Aug 2025) the apt package
# `libgdk-pixbuf2.0-0` was renamed and our build broke. Bookworm
# is supported for security updates until ~June 2028. Re-pin to
# `python:3.12-slim-trixie` (and update the libgdk-pixbuf name
# below) when we're ready to move.
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# OS deps:
#   - postgresql-client-18    for pg_dump (used by the backups app). Pinned to 18
#                             from the PGDG repo: bookworm's default client is 15,
#                             and pg_dump refuses to dump a NEWER server, so a v15
#                             client cannot back up the bundled PG18 database.
#   - weasyprint deps         for PDF rendering in the print pipeline
#   - curl, ca-certificates   for HTTPS fetch tools + healthcheck
#   - Node 24 LTS             for the web UI build (build-time + runtime via entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
    # PGDG apt repo (for postgresql-client-18 — see note above)
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    # Node 24 LTS apt repo
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client-18 \
        nodejs \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libffi-dev \
        libgdk-pixbuf2.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ----- Python dependencies -----
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ----- Web dependencies (cached separately so changes to JSX/code don't
#       force a full npm reinstall) -----
COPY web/package.json web/package-lock.json* ./web/
RUN cd web && npm ci

# ----- Application source -----
# Includes platform code (agent, app_platform, data_layer, tools, prompts,
# scripts, deploy, migrations) and apps/ (required apps baked in for a fast
# first boot; docker-compose bind-mount of ./apps on the host can override
# at runtime).
COPY . .

# ----- Initial web build -----
# Produces /app/web/dist with the required apps' UI components bundled.
# At runtime the entrypoint will rebuild this in place if the host has
# installed/removed optional apps since the last build.
#
# Baked-in apps (e.g. weather) may import npm packages that aren't in
# web/package.json — they declare them in apps/<id>/ui/package.json instead.
# Install that union into node_modules first (same step the entrypoint runs at
# container start, see deploy/entrypoint.sh), otherwise the Vite build fails
# with "Could not load .../node_modules/<pkg>" (e.g. leaflet for weather).
RUN cd web && node packaged-app-deps.mjs --install && npm run build && mkdir -p /app/web/dist && touch /app/web/dist/.last-build-stamp

# Health check — agent should respond on /api/health. Uses SKIPPERBOT_PORT
# (default 8000); the shell form expands the env var at container runtime.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS "http://localhost:${SKIPPERBOT_PORT:-8000}/api/health" || exit 1

EXPOSE 8000

# Entrypoint runs the rebuild-if-needed logic, then exec's the agent.
# Using ENTRYPOINT (not CMD) so SIGTERM still reaches python via the
# `exec` at the end of the script.
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
