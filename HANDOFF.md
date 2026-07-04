# Finora — Handoff / Continue Here

> Living status doc. If you're a fresh session: read [`CLAUDE.md`](CLAUDE.md) (the locked
> spec) first, then this file for *where we actually are*. Last updated: **2026-07-05**.

## TL;DR

- **Build-order step 1 is DONE and green:** the multi-tenant isolation foundation + a runnable
  monorepo skeleton (Django backend, Next.js frontend, Docker Compose).
- **All work is on branch `feat/tenant-foundation`** (8 commits), **not merged to `main`**, **no git remote** configured.
- **Backend tests: 16/16 passing.** Frontend builds clean.
- **Next up:** build-order step 2 — `Expense` / `Receipt` models + `ExpenseService`.

## What exists right now

```
finora/
├─ CLAUDE.md                 # LOCKED spec + guardrails (do not rewrite)
├─ HANDOFF.md                # this file
├─ README.md                 # run instructions
├─ docker-compose.yml        # postgres(pgvector), redis, django, celery-worker, celery-beat
├─ .env.example              # copy to .env for docker
├─ docs/superpowers/
│  ├─ specs/2026-07-04-tenant-foundation-design.md     # approved design
│  └─ plans/2026-07-04-tenant-foundation.md            # the 10-task plan we executed
├─ backend/                  # Django 5.2 + DRF
│  ├─ config/                # settings (base/dev/test), urls, celery, wsgi/asgi
│  ├─ apps/tenancy/          # THE isolation layer (see below)
│  ├─ tests/                 # pytest suite + throwaway ScopedThing model
│  ├─ pyproject.toml         # deps + pytest config
│  └─ .venv/                 # local venv (gitignored)
└─ frontend/                 # Next.js 15 app shell ("Finora — coming soon")
```

### The isolation layer (`backend/apps/tenancy/`) — the heart of step 1

| File | Responsibility |
|---|---|
| `context.py` | Holds "current tenant" in a `ContextVar`; `set/get/clear`, `unscoped()`, `TenantContextRequired` |
| `models.py` | `Tenant`, `TenantScopedModel` (abstract base), `TenantMembership` (user→tenant link) |
| `managers.py` | `TenantManager` (auto-filters by current tenant, **raises if none set**), `AllTenantsManager` |
| `middleware.py` | Reads `tenant_id` from the JWT and sets the context per request |
| `tasks.py` | `TenantBoundTask` base so Celery/agent code sets the same context |
| `serializers.py` | JWT login serializer that embeds `tenant_id` |
| `permissions.py` | `IsTenantMember` |
| `views.py` / `urls.py` | `/api/token/`, `/api/token/refresh/`, `/api/whoami/` |

**Plain-English version of how it works:** a signed-in user gets a "badge" (JWT) naming their
company (`tenant`). A checkpoint (`middleware`) reads it on every request and records the current
tenant; every DB query is then auto-limited to that tenant; the record is cleared when the request
ends. Background robots (Celery tasks) set the same badge. No badge → the app refuses loudly
instead of leaking or silently returning nothing. (Explainer artifact:
https://claude.ai/code/artifact/d29ce788-c26f-4fe6-b27a-ef5db2cdbccf)

## Key decisions & deviations (know these before extending)

1. **Django 5.2** (spec said "Django 5"; plan first said `<5.2`). The only Python on this machine is
   **3.14**, and 5.2 is the LTS with the best 3.14 story. Docker image pinned to **`python:3.13-slim`**
   (officially supported). Local `.venv` runs 3.14 for the fast test loop.
2. **Tests run on SQLite**, wired via `config/settings/test.py`, because the Docker daemon was down
   during the build and the tenancy layer uses only plain ORM features. **Postgres + pgvector remains
   the real runtime** (docker-compose). Later work that uses pgvector will need Postgres-backed tests.
3. **The middleware decodes the JWT itself** (not `request.auth`). DRF authenticates *inside* the
   view, which runs *after* Django middleware, so `request.auth` is unset in middleware. It validates
   the bearer token directly. Trade-off: the token is validated twice (middleware + view) — accepted
   to keep tenant resolution in exactly one place.
4. **Fail-loud manager:** a scoped query with no tenant in context **raises `TenantContextRequired`**
   rather than returning all rows (leak) or none (hidden bug). Cross-tenant access is opt-in via
   `unscoped()` or the `all_tenants` manager.
5. **Tenant resolution is JWT-claim only** for now (no subdomain). Storage is Django default (local
   `MEDIA_ROOT`), not S3/MinIO yet.
6. **Test-only model:** `backend/tests/models.py::ScopedThing` exists purely to exercise the base
   class; it lives in a throwaway `tests` app registered only in test settings.

## How to run / verify

**Backend tests (fast, no services needed):**
```bash
cd backend
source .venv/bin/activate          # venv already created on this machine
python -m pytest -q                # expect: 16 passed
python manage.py check             # expect: no issues
```

**Full stack (real runtime — needs Docker daemon running):**
```bash
cp .env.example .env               # set a real DJANGO_SECRET_KEY (>=32 chars)
docker compose up
docker compose exec django python manage.py migrate
```
API at http://localhost:8000/api/ · frontend: `cd frontend && npm run dev` → http://localhost:3000

**Manual auth smoke test:** see the "Auth smoke test" section in [`README.md`](README.md).

## What's NOT done yet (the remaining build order)

Per [`CLAUDE.md`](CLAUDE.md), build the **Receipt Processor as a vertical slice** next, in order:

- [ ] **Step 2** — `Expense` / `Receipt` models (both inherit `TenantScopedModel`) + `ExpenseService`
      (HTTP-free business logic; thin viewset → serializer → service → model).
- [ ] **Step 3** — `LLMProvider` Protocol + a `FakeLLMProvider` (decided: fake-only first, no real API
      keys yet) + a `ReceiptExtraction` Pydantic schema (the validate-or-reject safety boundary).
- [ ] **Step 4** — `AgentWorkflow` model with status state machine
      (`pending → running → needs_review → approved/rejected`) + a Celery task (use `TenantBoundTask`)
      that runs the processor and lands in `needs_review`.
- [ ] **Step 5** — receipt upload endpoint (thin) → serializer → `ExpenseService`.
- [ ] **Step 6** — frontend: upload zone → React Query mutation → poll workflow status → review/confirm
      UI (Zustand only for ephemeral UI state).
- [ ] **Step 7** — `AuditLog` wired to the confirm action.

Then generalize to the other three agents (Invoice Chaser, Expense Approver, Monthly Close) + Co-Pilot.

## Conventions to keep following

- **Dependency flow:** ViewSet (thin) → Serializer (validate/shape) → Service (logic) → Model.
  Services never touch `request`/`Response` so agents can reuse them.
- **New tenant-owned model?** Inherit `TenantScopedModel` — you get isolation for free; never write
  `.filter(tenant=...)` by hand.
- **TDD:** write the failing test, watch it fail, implement, watch it pass, commit. Small commits.
- **Every LLM output** must be parsed into a Pydantic model before touching the DB.
- **Do a review** and ask a "why this over that?" design question after any non-trivial code (per the
  practice format in the user's global setup).

## Suggested first move in a new session

1. `git branch --show-current` → confirm on `feat/tenant-foundation` (or merge to `main` first).
2. Skim `backend/apps/tenancy/` to load the isolation model into context.
3. Start step 2 with the design/plan skills, following the same TDD + small-commit rhythm.
