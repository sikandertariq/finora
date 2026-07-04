# Finora — Skeleton + Tenant Foundation (Design)

**Date:** 2026-07-04
**Status:** Approved
**Scope:** Build-order step 1 from `CLAUDE.md` — runnable monorepo skeleton + the multi-tenant isolation layer. No agent, no receipt, no expense logic yet.

---

## 1. Goal & non-goals

**Goal:** A one-command-up monorepo whose backend enforces tenant isolation in exactly one place, proven by tests and a `whoami` endpoint. This is the load-bearing base every later slice sits on.

**In scope**
- Monorepo layout (`backend/`, `frontend/`, `docker-compose.yml`).
- Docker Compose: `postgres` (pgvector image), `redis`, `django`, `celery-worker`, `celery-beat` — one `up`.
- Django 5 + DRF project wiring; split settings (`base` / `dev`); `django-environ` config.
- Celery app wired to Redis (broker + result backend).
- `tenancy` app: `Tenant`, `TenantScopedModel`, `TenantManager`, tenant context, `TenantMiddleware`, Celery tenant binding.
- Tenant-aware JWT (`tenant_id` claim) + `IsTenantMember` permission + `whoami` endpoint.
- Next.js 15 App Router + TS app **shell only** (runnable, no feature UI).
- pytest + pytest-django + factory_boy with the isolation test suite.

**Out of scope (later build-order steps)**
- `Expense` / `Receipt` models & services.
- `LLMProvider` / `FakeLLMProvider`, `ReceiptExtraction`, `AgentWorkflow`, agent Celery tasks.
- `AuditLog`.
- Receipt upload UI, review/confirm UI.
- Real LLM API wiring, subdomain tenant resolution, MinIO/S3.

---

## 2. Decisions (locked with user)

| Decision | Choice | Why |
|---|---|---|
| Session scope | Skeleton + tenant foundation only | Reviewable base before agent complexity |
| LLM provider | Deferred (fake-only later) | No API keys/cost needed for step 1 |
| Tenant resolution | JWT `tenant_id` claim | Simplest; subdomain layers on later without touching call sites |
| File storage | Django default storage → local `MEDIA_ROOT` | Swappable to S3 via config; no extra service now |
| Tenant context carrier | `contextvars.ContextVar` | Propagates correctly in sync requests **and** Celery workers; thread-locals would break service reuse |
| Missing tenant on scoped query | Raise `TenantContextRequired` (fail loud) | Silent-all = data leak; silent-none = hidden bugs |
| Cross-tenant escape hatch | Explicit `all_tenants` manager + `unscoped()` context manager | Legitimate jobs (migrations, admin, per-tenant beat tasks) opt out on purpose |
| Repo | Monorepo, name `finora` | One place for the tenant contract; two deploy targets later |

---

## 3. Repo layout

```
finora/
├─ backend/
│  ├─ config/
│  │  ├─ settings/  base.py, dev.py
│  │  ├─ urls.py
│  │  ├─ celery.py
│  │  ├─ asgi.py / wsgi.py
│  ├─ apps/
│  │  └─ tenancy/
│  │     ├─ context.py      # ContextVar + get/set/clear + unscoped()
│  │     ├─ models.py       # Tenant, TenantScopedModel
│  │     ├─ managers.py     # TenantManager, AllTenantsManager
│  │     ├─ middleware.py   # TenantMiddleware
│  │     ├─ tasks.py        # tenant_bound task base/decorator
│  │     ├─ permissions.py  # IsTenantMember
│  │     ├─ serializers.py  # TenantAwareTokenObtainPairSerializer
│  │     ├─ views.py        # whoami
│  │     └─ urls.py
│  ├─ tests/
│  ├─ pyproject.toml
│  ├─ manage.py
│  └─ Dockerfile
├─ frontend/                # Next.js 15 app shell
├─ docker-compose.yml
├─ .env.example
├─ CLAUDE.md                # project guardrails (copied from spec)
└─ README.md
```

---

## 4. Tenant isolation mechanism (the core)

### 4.1 Context carrier
`apps/tenancy/context.py` holds `_current_tenant_id: ContextVar[int | None]`.

- `set_current_tenant(tenant_id)` / `get_current_tenant_id()` / `clear_current_tenant()`.
- `unscoped()` — a context manager that flags "cross-tenant access intended", so `TenantManager` skips filtering inside the block.

### 4.2 Models
- `Tenant` — **not** scoped (must be queryable to resolve context). `id`, `name`, `slug`, timestamps.
- `TenantScopedModel(models.Model)` — abstract; `tenant = FK(Tenant)`; `objects = TenantManager()`; `all_tenants = AllTenantsManager()`.

### 4.3 Managers
- `TenantManager.get_queryset()`:
  - if inside `unscoped()` → return unfiltered queryset;
  - elif `get_current_tenant_id()` is set → `.filter(tenant_id=...)`;
  - else → raise `TenantContextRequired`.
- Auto-stamp `tenant_id` on create when context is set (so services don't hand-set it).
- `AllTenantsManager` — never filters (explicit cross-tenant).

### 4.4 Middleware
`TenantMiddleware`: after auth, read `tenant_id` from the validated JWT, `set_current_tenant(...)`; `clear_current_tenant()` in a `finally`. No tenant claim on a protected route → 403.

### 4.5 Celery binding
`tenant_bound` task base (or decorator) takes `tenant_id`, sets the contextvar in a `try/finally` around `run()`. Agent code later calls the *same* services with the *same* isolation guarantees. (No agent tasks this round — the base class + a trivial test task to prove it.)

---

## 5. Auth surface (this round)
- `TenantAwareTokenObtainPairSerializer` embeds `tenant_id` in the JWT.
- `IsTenantMember` permission — trusts middleware-set context; rejects when absent.
- `GET /api/whoami/` — returns the authenticated user + resolved tenant. Exists to prove the whole chain (JWT → middleware → context → response) works end to end.
- No registration/login UI. Users/tenants created via factory/`manage.py` for tests and manual poking.

---

## 6. Testing (this round)
pytest + pytest-django + factory_boy. Load-bearing cases:
1. Scoped query returns only the current tenant's rows.
2. Scoped query with no tenant context raises `TenantContextRequired`.
3. `all_tenants` / `unscoped()` sees across tenants.
4. Create auto-stamps the current tenant.
5. `TenantMiddleware` sets context during a request and clears it after.
6. `tenant_bound` Celery task sets/clears context around execution.

A throwaway scoped model (or a minimal real one) may live in the test app to exercise the base class without depending on later feature models.

---

## 7. Definition of done (this round)
- `docker compose up` brings all five services healthy.
- Migrations apply; `Tenant` + a test scoped model exist.
- Isolation test suite green.
- `whoami` returns correct tenant for a tenant-scoped JWT; 403 without one.
- Frontend shell serves a page.
- `README` documents one-command run.
