import tempfile

from .dev import *  # noqa

# Register the throwaway app that holds test-only models (e.g. ScopedThing).
INSTALLED_APPS = INSTALLED_APPS + ["tests"]

# Keep test-uploaded files (Receipt.file) out of the real media/ dir.
MEDIA_ROOT = tempfile.mkdtemp(prefix="finora-test-media-")

# SQLite keeps the unit/integration loop dependency-free and fast. The tenancy
# layer uses only plain ORM features, so this is a faithful substrate. The real
# runtime (and pgvector work later) uses Postgres via Docker/CI.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
