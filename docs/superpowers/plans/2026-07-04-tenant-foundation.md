# Finora Tenant Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a one-command-up Finora monorepo whose backend enforces multi-tenant isolation in exactly one place, proven by tests and a `whoami` endpoint.

**Architecture:** Django 5 + DRF backend, thin views → services → models. Tenant identity travels in a `contextvars.ContextVar` set by middleware (from a JWT claim) and by a Celery task base, so the same code path is tenant-safe in HTTP requests and background workers. A `TenantManager` auto-filters scoped models and fails loud when no tenant is in context. Next.js 15 app shell alongside. Everything runs under Docker Compose.

**Tech Stack:** Django 5, djangorestframework, djangorestframework-simplejwt, Celery, Redis, PostgreSQL (pgvector image), django-environ, pydantic, pytest + pytest-django + factory_boy; Next.js 15 (App Router) + TypeScript.

## Global Constraints

- Backend framework: **Django 5 + DRF**, dependency flow **ViewSet → Serializer → Service → Model**. Views thin; services never touch `request`/`Response`; serializers validate/shape only.
- Multi-tenancy: **shared schema**, every tenant-owned row has `tenant_id`; isolation logic in **exactly one place** — never scatter `.filter(tenant=...)`.
- Tenant context carrier: **`contextvars.ContextVar`** (not thread-locals).
- Missing tenant on a scoped query: **raise `TenantContextRequired`** (fail loud). Cross-tenant access only via explicit `all_tenants` manager / `unscoped()`.
- Tenant resolution: **JWT `tenant_id` claim** only (no subdomain this round).
- File storage: Django default storage → local `MEDIA_ROOT` (no MinIO).
- No LangChain/CrewAI/etc., no separate vector DB, no schema-per-tenant, no `drf-spectacular`, no websockets. (None are introduced this round anyway.)
- Testing: **pytest + pytest-django + factory_boy**.
- Python 3.12+, Node 20+.

---

## File Structure

**Backend**
- `backend/pyproject.toml` — deps + pytest config.
- `backend/manage.py` — Django entrypoint.
- `backend/config/settings/base.py` — shared settings (env-driven).
- `backend/config/settings/dev.py` — dev overrides.
- `backend/config/urls.py` — root URLconf.
- `backend/config/wsgi.py`, `backend/config/asgi.py` — servers.
- `backend/config/celery.py` — Celery app.
- `backend/config/__init__.py` — load Celery app on Django start.
- `backend/apps/tenancy/context.py` — ContextVar + get/set/clear + `unscoped()` + `TenantContextRequired`.
- `backend/apps/tenancy/models.py` — `Tenant`, `TenantScopedModel`.
- `backend/apps/tenancy/managers.py` — `TenantManager`, `AllTenantsManager`.
- `backend/apps/tenancy/middleware.py` — `TenantMiddleware`.
- `backend/apps/tenancy/tasks.py` — `TenantBoundTask` base.
- `backend/apps/tenancy/serializers.py` — `TenantAwareTokenObtainPairSerializer`.
- `backend/apps/tenancy/permissions.py` — `IsTenantMember`.
- `backend/apps/tenancy/views.py` — `whoami`.
- `backend/apps/tenancy/urls.py` — auth + whoami routes.
- `backend/apps/tenancy/apps.py`, `__init__.py`.
- `backend/tests/` — `conftest.py`, `factories.py`, `models.py` (throwaway scoped test model), test modules.
- `backend/Dockerfile`.

**Infra / root**
- `docker-compose.yml`, `.env.example`, `README.md`, `CLAUDE.md`.

**Frontend**
- `frontend/` — Next.js 15 app shell (create-next-app output; single home page).

---

## Task 1: Backend project boots

**Files:**
- Create: `backend/pyproject.toml`, `backend/manage.py`, `backend/config/__init__.py`, `backend/config/settings/__init__.py`, `backend/config/settings/base.py`, `backend/config/settings/dev.py`, `backend/config/urls.py`, `backend/config/wsgi.py`, `backend/config/asgi.py`, `backend/apps/__init__.py`, `backend/apps/tenancy/__init__.py`, `backend/apps/tenancy/apps.py`, `backend/.env` (local, gitignored), root `.env.example`.

**Interfaces:**
- Produces: a Django project importable as `config.settings.dev`; app label `tenancy`; env vars `DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `DJANGO_DEBUG`.

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "finora-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "django>=5.0,<5.2",
    "djangorestframework>=3.15",
    "djangorestframework-simplejwt>=5.3",
    "celery>=5.4",
    "redis>=5.0",
    "psycopg[binary]>=3.2",
    "django-environ>=0.11",
    "pydantic>=2.7",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-django>=4.8",
    "factory-boy>=3.3",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.dev"
python_files = ["test_*.py"]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `backend/config/settings/base.py`**

```python
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.tenancy",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.tenancy.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

DATABASES = {"default": env.db("DATABASE_URL", default="postgres://finora:finora@localhost:5432/finora")}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
```

- [ ] **Step 3: Create `backend/config/settings/dev.py`**

```python
from .base import *  # noqa

DEBUG = True
```

Also create `backend/config/settings/__init__.py` (empty).

- [ ] **Step 4: Create `backend/config/urls.py`**

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.tenancy.urls")),
]
```

- [ ] **Step 5: Create `backend/config/wsgi.py` and `backend/config/asgi.py`**

```python
# wsgi.py
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_wsgi_application()
```

```python
# asgi.py
import os
from django.core.asgi import get_asgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_asgi_application()
```

- [ ] **Step 6: Create `backend/manage.py`**

```python
#!/usr/bin/env python
import os
import sys

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Create app stub + package files**

`backend/apps/__init__.py` (empty), `backend/apps/tenancy/__init__.py` (empty), `backend/config/__init__.py` (empty for now — Celery added in Task 3).

`backend/apps/tenancy/apps.py`:

```python
from django.apps import AppConfig

class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenancy"
    label = "tenancy"
```

`backend/apps/tenancy/urls.py` (placeholder, filled in Task 8):

```python
urlpatterns = []
```

`backend/apps/tenancy/middleware.py` (placeholder, filled in Task 6):

```python
class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
```

- [ ] **Step 8: Create env files**

`backend/.env` (gitignored):

```
DJANGO_SECRET_KEY=dev-insecure-change-me
DJANGO_DEBUG=True
DATABASE_URL=postgres://finora:finora@localhost:5432/finora
REDIS_URL=redis://localhost:6379/0
```

Root `.env.example` (committed):

```
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=True
POSTGRES_USER=finora
POSTGRES_PASSWORD=finora
POSTGRES_DB=finora
DATABASE_URL=postgres://finora:finora@postgres:5432/finora
REDIS_URL=redis://redis:6379/0
```

- [ ] **Step 9: Verify project boots**

Run (from `backend/`, with a local venv + deps, or defer to Task 2 Docker):
`python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 10: Commit**

```bash
git add backend .env.example
git commit -m "feat(backend): Django 5 + DRF project skeleton"
```

---

## Task 2: Docker Compose brings up all services

**Files:**
- Create: `backend/Dockerfile`, `docker-compose.yml`.

**Interfaces:**
- Consumes: `backend/` project (Task 1), env vars from `.env`.
- Produces: services `postgres`, `redis`, `django`, `celery-worker`, `celery-beat`; DB reachable at host `postgres`, Redis at `redis`.

- [ ] **Step 1: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-finora}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-finora}
      POSTGRES_DB: ${POSTGRES_DB:-finora}
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-finora}"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  django:
    build: ./backend
    env_file: [.env]
    volumes: ["./backend:/app"]
    ports: ["8000:8000"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}

  celery-worker:
    build: ./backend
    command: celery -A config worker -l info
    env_file: [.env]
    volumes: ["./backend:/app"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}

  celery-beat:
    build: ./backend
    command: celery -A config beat -l info
    env_file: [.env]
    volumes: ["./backend:/app"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}

volumes:
  pgdata:
```

- [ ] **Step 3: Create root `.env` from example**

Copy `.env.example` → `.env` (gitignored) and set a real `DJANGO_SECRET_KEY`.

- [ ] **Step 4: Verify django + infra come up**

Run: `docker compose up -d postgres redis django`
Then: `docker compose exec django python manage.py check`
Expected: no issues. (Celery services verified in Task 3.)

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile docker-compose.yml
git commit -m "feat(infra): docker compose for django/postgres/redis/celery"
```

---

## Task 3: Celery app wired

**Files:**
- Create: `backend/config/celery.py`.
- Modify: `backend/config/__init__.py`.
- Test: `backend/tests/test_celery.py`.

**Interfaces:**
- Consumes: `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` settings (Task 1).
- Produces: `config.celery.app` (Celery instance, name `finora`), autodiscovers `apps.*.tasks`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_celery.py`:

```python
def test_celery_app_configured():
    from config.celery import app
    assert app.main == "finora"
    assert "config.settings" in app.conf.get("beat_scheduler", "") or app.conf.broker_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_celery.py -v`
Expected: FAIL — `ModuleNotFoundError: config.celery`.

- [ ] **Step 3: Create `backend/config/celery.py`**

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("finora")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

- [ ] **Step 4: Load Celery on Django start — `backend/config/__init__.py`**

```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_celery.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/config/celery.py backend/config/__init__.py backend/tests/test_celery.py
git commit -m "feat(backend): wire Celery app to Redis"
```

---

## Task 4: Tenant context module

**Files:**
- Create: `backend/apps/tenancy/context.py`.
- Test: `backend/tests/test_context.py`.

**Interfaces:**
- Produces:
  - `set_current_tenant(tenant_id: int) -> None`
  - `get_current_tenant_id() -> int | None`
  - `clear_current_tenant() -> None`
  - `unscoped()` — context manager; inside it `is_unscoped()` returns `True`.
  - `is_unscoped() -> bool`
  - `class TenantContextRequired(Exception)`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_context.py`:

```python
import pytest
from apps.tenancy import context

def teardown_function():
    context.clear_current_tenant()

def test_set_and_get():
    context.set_current_tenant(7)
    assert context.get_current_tenant_id() == 7

def test_default_is_none():
    assert context.get_current_tenant_id() is None

def test_clear():
    context.set_current_tenant(7)
    context.clear_current_tenant()
    assert context.get_current_tenant_id() is None

def test_unscoped_flag():
    assert context.is_unscoped() is False
    with context.unscoped():
        assert context.is_unscoped() is True
    assert context.is_unscoped() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.tenancy.context`.

- [ ] **Step 3: Create `backend/apps/tenancy/context.py`**

```python
from contextlib import contextmanager
from contextvars import ContextVar

_current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)
_unscoped: ContextVar[bool] = ContextVar("tenant_unscoped", default=False)


class TenantContextRequired(Exception):
    """Raised when a tenant-scoped query runs with no tenant in context."""


def set_current_tenant(tenant_id: int) -> None:
    _current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> int | None:
    return _current_tenant_id.get()


def clear_current_tenant() -> None:
    _current_tenant_id.set(None)


def is_unscoped() -> bool:
    return _unscoped.get()


@contextmanager
def unscoped():
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_context.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/tenancy/context.py backend/tests/test_context.py
git commit -m "feat(tenancy): tenant context var + unscoped escape hatch"
```

---

## Task 5: Tenant model, TenantScopedModel, managers (the core)

**Files:**
- Create: `backend/apps/tenancy/managers.py`, `backend/apps/tenancy/models.py`.
- Create: `backend/tests/models.py` (throwaway scoped model for the test app), `backend/tests/factories.py`, `backend/tests/conftest.py`.
- Test: `backend/tests/test_scoping.py`.

**Interfaces:**
- Consumes: `context.get_current_tenant_id`, `context.is_unscoped`, `context.TenantContextRequired` (Task 4).
- Produces:
  - `class Tenant(models.Model)` — fields `name: str`, `slug: str (unique)`, `created_at`. NOT scoped.
  - `class TenantScopedModel(models.Model)` — abstract; `tenant = FK(Tenant, on_delete=CASCADE)`; `objects = TenantManager()`; `all_tenants = AllTenantsManager()`.
  - `class TenantManager(models.Manager)` — filters by current tenant; raises `TenantContextRequired` when unset (unless `unscoped()`); auto-stamps `tenant_id` in `create()`.
  - `class AllTenantsManager(models.Manager)` — never filters.
  - Test model `ScopedThing(TenantScopedModel)` with `name: str` (in `tests` app).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_scoping.py`:

```python
import pytest
from apps.tenancy import context
from apps.tenancy.models import Tenant
from tests.models import ScopedThing

pytestmark = pytest.mark.django_db

def teardown_function():
    context.clear_current_tenant()

def _seed():
    t1 = Tenant.objects.create(name="A", slug="a")
    t2 = Tenant.objects.create(name="B", slug="b")
    ScopedThing.all_tenants.create(tenant=t1, name="a-thing")
    ScopedThing.all_tenants.create(tenant=t2, name="b-thing")
    return t1, t2

def test_scoped_query_returns_only_current_tenant():
    t1, _ = _seed()
    context.set_current_tenant(t1.id)
    names = set(ScopedThing.objects.values_list("name", flat=True))
    assert names == {"a-thing"}

def test_scoped_query_without_context_raises():
    _seed()
    with pytest.raises(context.TenantContextRequired):
        list(ScopedThing.objects.all())

def test_all_tenants_sees_across_tenants():
    _seed()
    assert ScopedThing.all_tenants.count() == 2

def test_unscoped_block_sees_across_tenants():
    _seed()
    with context.unscoped():
        assert ScopedThing.objects.count() == 2

def test_create_autostamps_current_tenant():
    t1, _ = _seed()
    context.set_current_tenant(t1.id)
    thing = ScopedThing.objects.create(name="new")
    assert thing.tenant_id == t1.id
```

- [ ] **Step 2: Create test scaffolding**

`backend/tests/__init__.py` (empty). `backend/tests/models.py`:

```python
from django.db import models
from apps.tenancy.models import TenantScopedModel

class ScopedThing(TenantScopedModel):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"
```

`backend/tests/conftest.py` — register the `tests` app so its model gets a table:

```python
import django
from django.conf import settings

def pytest_configure():
    settings.INSTALLED_APPS = list(settings.INSTALLED_APPS) + ["tests"]
    django.setup()
```

Add `backend/tests/apps.py`:

```python
from django.apps import AppConfig

class TestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests"
    label = "tests"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_scoping.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.tenancy.models`.

- [ ] **Step 4: Create `backend/apps/tenancy/managers.py`**

```python
from django.db import models
from . import context


class TenantQuerySet(models.QuerySet):
    pass


class TenantManager(models.Manager):
    def get_queryset(self):
        qs = TenantQuerySet(self.model, using=self._db)
        if context.is_unscoped():
            return qs
        tenant_id = context.get_current_tenant_id()
        if tenant_id is None:
            raise context.TenantContextRequired(
                f"{self.model.__name__} accessed with no tenant in context. "
                f"Set a tenant or use `unscoped()` / `all_tenants`."
            )
        return qs.filter(tenant_id=tenant_id)

    def create(self, **kwargs):
        if "tenant" not in kwargs and "tenant_id" not in kwargs:
            tenant_id = context.get_current_tenant_id()
            if tenant_id is None:
                raise context.TenantContextRequired(
                    f"Cannot create {self.model.__name__} without a tenant in context."
                )
            kwargs["tenant_id"] = tenant_id
        return super().create(**kwargs)


class AllTenantsManager(models.Manager):
    """Explicit cross-tenant access. Never filters."""
```

- [ ] **Step 5: Create `backend/apps/tenancy/models.py`**

```python
from django.db import models
from .managers import TenantManager, AllTenantsManager


class Tenant(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TenantScopedModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)

    objects = TenantManager()
    all_tenants = AllTenantsManager()

    class Meta:
        abstract = True
```

- [ ] **Step 6: Make migrations for tenancy**

Run: `python manage.py makemigrations tenancy`
Expected: creates `Tenant` migration. (The `tests` app model needs a table only under pytest; pytest-django builds the test DB from models via `--create-db`, so no committed migration for it. If the runner needs it, add `makemigrations tests` in the test env only.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_scoping.py -v`
Expected: PASS (5 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/tenancy/models.py backend/apps/tenancy/managers.py backend/apps/tenancy/migrations backend/tests
git commit -m "feat(tenancy): TenantScopedModel + auto-filtering manager (fail-loud)"
```

---

## Task 6: TenantMiddleware

**Files:**
- Modify: `backend/apps/tenancy/middleware.py`.
- Test: `backend/tests/test_middleware.py`.

**Interfaces:**
- Consumes: `context.set_current_tenant`, `context.clear_current_tenant`, `context.get_current_tenant_id` (Task 4); reads `request.auth` (SimpleJWT validated token) for a `tenant_id` claim.
- Produces: `TenantMiddleware` that sets context from the JWT claim for the request lifetime and clears it after.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_middleware.py`:

```python
from apps.tenancy import context
from apps.tenancy.middleware import TenantMiddleware

class FakeAuth(dict):
    pass

class Req:
    def __init__(self, tenant_id):
        self.auth = FakeAuth({"tenant_id": tenant_id}) if tenant_id else None

def test_middleware_sets_and_clears_context():
    seen = {}
    def get_response(request):
        seen["during"] = context.get_current_tenant_id()
        return "ok"
    mw = TenantMiddleware(get_response)
    result = mw(Req(tenant_id=42))
    assert result == "ok"
    assert seen["during"] == 42
    assert context.get_current_tenant_id() is None  # cleared after

def test_middleware_no_claim_leaves_context_empty():
    def get_response(request):
        return "ok"
    mw = TenantMiddleware(get_response)
    mw(Req(tenant_id=None))
    assert context.get_current_tenant_id() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_middleware.py -v`
Expected: FAIL — `during` is `None` (placeholder middleware doesn't set context).

- [ ] **Step 3: Implement `backend/apps/tenancy/middleware.py`**

```python
from . import context


class TenantMiddleware:
    """Set the current tenant from the validated JWT's `tenant_id` claim."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id = None
        auth = getattr(request, "auth", None)
        if auth is not None:
            try:
                tenant_id = auth.get("tenant_id")
            except AttributeError:
                tenant_id = None
        if tenant_id is not None:
            context.set_current_tenant(tenant_id)
        try:
            return self.get_response(request)
        finally:
            context.clear_current_tenant()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_middleware.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/tenancy/middleware.py backend/tests/test_middleware.py
git commit -m "feat(tenancy): middleware sets tenant context from JWT claim"
```

---

## Task 7: Celery tenant-bound task base

**Files:**
- Create: `backend/apps/tenancy/tasks.py`.
- Test: `backend/tests/test_tasks.py`.

**Interfaces:**
- Consumes: `config.celery.app` (Task 3), `context` (Task 4).
- Produces: `TenantBoundTask(celery.Task)` — a base whose `__call__` pops `tenant_id` from kwargs, sets context around the task body, clears it after. A demo task `echo_current_tenant` registered with this base.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tasks.py`:

```python
from apps.tenancy import context
from apps.tenancy.tasks import echo_current_tenant

def teardown_function():
    context.clear_current_tenant()

def test_task_binds_and_clears_tenant():
    result = echo_current_tenant.apply(kwargs={"tenant_id": 99}).get()
    assert result == 99
    assert context.get_current_tenant_id() is None  # cleared after run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.tenancy.tasks`.

- [ ] **Step 3: Create `backend/apps/tenancy/tasks.py`**

```python
from celery import Task
from config.celery import app
from . import context


class TenantBoundTask(Task):
    """Base task: bind the tenant context from a `tenant_id` kwarg."""

    def __call__(self, *args, **kwargs):
        tenant_id = kwargs.pop("tenant_id", None)
        if tenant_id is not None:
            context.set_current_tenant(tenant_id)
        try:
            return self.run(*args, **kwargs)
        finally:
            context.clear_current_tenant()


@app.task(base=TenantBoundTask, bind=False)
def echo_current_tenant():
    return context.get_current_tenant_id()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tasks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/tenancy/tasks.py backend/tests/test_tasks.py
git commit -m "feat(tenancy): tenant-bound Celery task base"
```

---

## Task 8: Tenant-aware JWT + IsTenantMember + whoami

**Files:**
- Create: `backend/apps/tenancy/serializers.py`, `backend/apps/tenancy/permissions.py`, `backend/apps/tenancy/views.py`.
- Modify: `backend/apps/tenancy/urls.py`, `backend/config/settings/base.py` (add a `TenantMembership` model? No — keep minimal: put `tenant_id` on the user via a profile FK). See Step 1.
- Create: migration for `TenantMembership`.
- Test: `backend/tests/test_auth.py`.

**Interfaces:**
- Consumes: `Tenant` (Task 5), SimpleJWT, `context.get_current_tenant_id` (Task 4).
- Produces:
  - `TenantMembership(models.Model)` — `user = OneToOne(User)`, `tenant = FK(Tenant)`. (Minimal link so a token can carry the right tenant.)
  - `TenantAwareTokenObtainPairSerializer` — adds `tenant_id` claim from the user's membership.
  - `IsTenantMember(BasePermission)` — allows when `context.get_current_tenant_id()` is set.
  - `whoami(request)` — returns `{"user": <username>, "tenant_id": <int>}`.
  - Routes: `POST /api/token/`, `POST /api/token/refresh/`, `GET /api/whoami/`.

- [ ] **Step 1: Add `TenantMembership` to `backend/apps/tenancy/models.py`**

Append:

```python
from django.contrib.auth import get_user_model  # top of file

class TenantMembership(models.Model):
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="tenant_membership")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")

    def __str__(self):
        return f"{self.user} @ {self.tenant}"
```

Run: `python manage.py makemigrations tenancy`

- [ ] **Step 2: Write the failing test**

`backend/tests/test_auth.py`:

```python
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.tenancy.models import Tenant, TenantMembership

pytestmark = pytest.mark.django_db

def _user_with_tenant():
    t = Tenant.objects.create(name="Acme", slug="acme")
    u = User.objects.create_user("alice", password="pw12345!")
    TenantMembership.objects.create(user=u, tenant=t)
    return u, t

def test_token_carries_tenant_and_whoami_resolves_it():
    u, t = _user_with_tenant()
    client = APIClient()
    resp = client.post("/api/token/", {"username": "alice", "password": "pw12345!"}, format="json")
    assert resp.status_code == 200
    access = resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    who = client.get("/api/whoami/")
    assert who.status_code == 200
    assert who.data == {"user": "alice", "tenant_id": t.id}

def test_whoami_without_token_is_401():
    client = APIClient()
    assert client.get("/api/whoami/").status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — 404/500 (routes/serializer/view not implemented).

- [ ] **Step 4: Create `backend/apps/tenancy/serializers.py`**

```python
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class TenantAwareTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        membership = getattr(user, "tenant_membership", None)
        if membership is not None:
            token["tenant_id"] = membership.tenant_id
        return token
```

- [ ] **Step 5: Create `backend/apps/tenancy/permissions.py`**

```python
from rest_framework.permissions import BasePermission
from . import context


class IsTenantMember(BasePermission):
    message = "No tenant context on this request."

    def has_permission(self, request, view):
        return context.get_current_tenant_id() is not None
```

- [ ] **Step 6: Create `backend/apps/tenancy/views.py`**

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from . import context
from .permissions import IsTenantMember
from .serializers import TenantAwareTokenObtainPairSerializer


class TenantTokenObtainPairView(TokenObtainPairView):
    serializer_class = TenantAwareTokenObtainPairSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsTenantMember])
def whoami(request):
    return Response({
        "user": request.user.username,
        "tenant_id": context.get_current_tenant_id(),
    })
```

- [ ] **Step 7: Fill `backend/apps/tenancy/urls.py`**

```python
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import TenantTokenObtainPairView, whoami

urlpatterns = [
    path("token/", TenantTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("whoami/", whoami, name="whoami"),
]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (2 tests).

- [ ] **Step 9: Run the whole suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add backend/apps/tenancy backend/tests/test_auth.py
git commit -m "feat(tenancy): tenant-aware JWT, IsTenantMember, whoami endpoint"
```

---

## Task 9: Frontend Next.js app shell

**Files:**
- Create: `frontend/` via create-next-app (App Router + TS + Tailwind).

**Interfaces:**
- Produces: a runnable Next.js 15 app serving a home page at `/`. No API calls this round.

- [ ] **Step 1: Scaffold**

Run from repo root:
`npx create-next-app@latest frontend --ts --app --tailwind --eslint --src-dir --import-alias "@/*" --no-turbopack --use-npm`

- [ ] **Step 2: Replace home page `frontend/src/app/page.tsx`**

```tsx
export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <h1 className="text-2xl font-semibold">Finora — coming soon</h1>
    </main>
  );
}
```

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "feat(frontend): Next.js 15 app shell"
```

---

## Task 10: README + project CLAUDE.md

**Files:**
- Create: `README.md`.
- Create: `CLAUDE.md` (copy the Finora spec into the repo root).

**Interfaces:** none (docs).

- [ ] **Step 1: Copy the spec into the repo**

Copy the Finora spec (the source `CLAUDE.md` provided) to `finora/CLAUDE.md` so future Claude Code sessions load the guardrails.

- [ ] **Step 2: Write `README.md`**

````markdown
# Finora

Multi-tenant AI-agentic finance OS. See `CLAUDE.md` for engineering guardrails and `docs/superpowers/specs/` for designs.

## Run (Docker)

```bash
cp .env.example .env   # set DJANGO_SECRET_KEY
docker compose up
docker compose exec django python manage.py migrate
```

- API: http://localhost:8000/api/
- Frontend: `cd frontend && npm run dev` → http://localhost:3000

## Test

```bash
cd backend && pytest -v
```

## Auth smoke test

```bash
# create a user + tenant + membership via manage.py shell, then:
curl -s -X POST localhost:8000/api/token/ -d 'username=U&password=P'
curl -s localhost:8000/api/whoami/ -H "Authorization: Bearer <access>"
```
````

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: README + project guardrails"
```

---

## Self-Review Notes

- **Spec coverage:** repo layout (T1,T9), Docker Compose 5 services (T2,T3), dependency-flow scaffolding + tenancy app (T1,T5–T8), contextvar carrier (T4), fail-loud manager + escape hatch (T5), middleware from JWT claim (T6), Celery tenant binding (T7), tenant-aware JWT + IsTenantMember + whoami (T8), storage default (settings T1), tests for all six load-bearing cases (T4–T8). ✅
- **Deferred by design (later steps):** Expense/Receipt, LLMProvider/Fake, ReceiptExtraction, AgentWorkflow, AuditLog, receipt UI. Not in this plan.
- **Type consistency:** `set_current_tenant`/`get_current_tenant_id`/`clear_current_tenant`/`is_unscoped`/`unscoped`/`TenantContextRequired` used identically across T4–T8. Managers `objects`/`all_tenants` consistent T5→tests.
- **Known risk:** the `tests` app model (`ScopedThing`) needs a DB table under pytest. If pytest-django doesn't auto-create it from the app registry, add a `makemigrations tests` step in the test bootstrap (noted in T5 Step 6). Resolve during execution if the migration isn't picked up.
