#!/usr/bin/env bash
# Local dev convenience: runs the API against a throwaway file-backed SQLite DB
# instead of Postgres, for environments without Docker running (this sandbox,
# reliably, per HANDOFF.md's notes across every step so far). Not the real
# runtime -- docker-compose + Postgres/pgvector still is. Safe to delete
# dev.sqlite3 any time; migrate re-creates it.
set -euo pipefail
cd "$(dirname "$0")/.."

source .venv/bin/activate
export DJANGO_SETTINGS_MODULE=config.settings.dev
export DATABASE_URL="${DATABASE_URL:-sqlite:///$(pwd)/dev.sqlite3}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-dev-only-not-for-production-please-change}"

python manage.py migrate --noinput
exec python manage.py runserver "0.0.0.0:${PORT:-8000}"
