# Finora — Handoff / Continue Here

> Living status doc. If you're a fresh session: read [`CLAUDE.md`](CLAUDE.md) (the locked
> spec) first, then this file for *where we actually are*. Last updated: **2026-07-05**.

## TL;DR

- **Build-order step 1 is DONE and green:** the multi-tenant isolation foundation + a runnable
  monorepo skeleton (Django backend, Next.js frontend, Docker Compose).
- **Build-order step 2 is DONE and green:** `Expense` / `Receipt` models (both tenant-scoped) +
  `ExpenseService` (create/update/get/list/delete, HTTP-free).
- **Build-order step 3 is DONE and green:** `LLMProvider` Protocol + `FakeLLMProvider` +
  `ReceiptExtraction` Pydantic schema (the validate-or-reject safety boundary).
- **Real provider added (revises the "fake-only" decision):** `GeminiProvider`
  (`apps/agents/providers/gemini.py`) implements `LLMProvider` against Google's Gemini API
  (`google-genai` SDK). `FakeLLMProvider` remains what automated tests inject — `GeminiProvider`
  is unit-tested against a fake `genai.Client` stand-in, never a real network call. **A real
  `GEMINI_API_KEY` still needs to be set locally** (see "How to run / verify") before step 4's
  Celery task can call it for real.
- **Build-order step 4 is DONE and green:** `AgentWorkflow` model (full status state machine) +
  `ReceiptProcessorService` (LLM call → validate → land in `needs_review`) + the Celery task that
  runs it, using the real `GeminiProvider` with a live key.
- **All work is on branch `feat/tenant-foundation`**, **not merged to `main`**, **no git remote** configured.
- **Backend tests: 55/55 passing.** Frontend builds clean.
- **Next up:** build-order step 5 — receipt upload endpoint (thin viewset → serializer →
  `ExpenseService`), which is also where a "confirm"/"reject" endpoint will need to exist so the
  frontend (step 6) can act on a `needs_review` workflow.

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
│  ├─ apps/expenses/         # Expense/Receipt models + ExpenseService (step 2) + schemas.py (step 3)
│  ├─ apps/agents/           # LLMProvider + GeminiProvider (step 3) + AgentWorkflow +
│  │                         # ReceiptProcessorService + Celery task (step 4)
│  ├─ tests/                 # pytest suite + throwaway ScopedThing model + factories.py
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

### Expenses (`backend/apps/expenses/`) — step 2

| File | Responsibility |
|---|---|
| `models.py` | `Receipt` (uploaded file + who/when) and `Expense` (vendor/amount/currency/category/date), both inherit `TenantScopedModel`. `Expense.receipt` is an optional one-to-one link back to the `Receipt` it was created from. |
| `services.py` | `ExpenseService` — `create`, `update`, `get`, `list`, `delete`. Plain data in, model instances out, no `request`/`Response`. Rejects amounts `<= 0`. |

**Plain-English version:** an `Expense` is one line-item cost (who it was paid to, how much, what
category). A `Receipt` is just the uploaded proof file — it can exist on its own (uploaded, not yet
turned into an expense) or be attached to the `Expense` it produced. All the create/edit/delete
rules live in one place (`ExpenseService`) so that later, when the AI agent processes a receipt in
the background, it calls the exact same code path a human clicking "save" would — no duplicated
rules to drift out of sync.

### Agents / LLM boundary (`backend/apps/agents/llm.py`, `backend/apps/expenses/schemas.py`) — step 3

| File | Responsibility |
|---|---|
| `apps/agents/llm.py` | `LLMProvider` — a `Protocol` (structural interface, not a base class) any concrete provider must satisfy. `LLMMessage` / `LLMResponse` are the plain data shapes that cross that boundary. `FakeLLMProvider` — the only concrete provider right now; returns a canned string (or a queue of them) instead of calling a real API, and records every call so tests can assert on it. |
| `apps/expenses/schemas.py` | `ReceiptExtraction` — a Pydantic model describing exactly what a valid receipt extraction looks like (vendor, amount, currency, date, line items, a confidence score, and a `missing_fields` list the agent can use instead of guessing). |

**Plain-English version:** `LLMProvider` is a contract, not a specific AI vendor — anything that can
take a list of messages and hand back text satisfies it, whether that's today's fake, or OpenAI/
Anthropic later. Because `ExpenseService` and future agent code will depend on this *contract*
rather than a concrete class, switching providers is a one-line config change, and tests never make
a real network call. `ReceiptExtraction` is the "safety gate": raw text out of an LLM is just a
string until it's been squeezed through this schema — if it doesn't fit (missing vendor, a
negative amount, confidence outside 0–1), Pydantic refuses it before it ever reaches the database.
`tests/test_llm_to_extraction_pipeline.py` proves both pieces work together: a well-formed fake
response becomes a validated `ReceiptExtraction`; a malformed one raises and stops cold.

**`GeminiProvider`** (`apps/agents/providers/gemini.py`) is the first real (non-fake)
implementation of `LLMProvider`. It wraps `google.genai.Client`, translating this project's plain
`LLMMessage` list into Gemini's `Content`/`Part` shape and its `"assistant"` role into Gemini's
`"model"` role, and folding any `role="system"` messages into `system_instruction` (Gemini has no
"system" turn in the message list itself). The constructor takes an already-built client, not an
API key, specifically so `tests/test_gemini_provider.py` can inject a fake stand-in — the real
`genai.Client(api_key=...)` is only constructed by `GeminiProvider.from_settings()`, which reads
`GEMINI_API_KEY` / `GEMINI_MODEL` from Django settings. `LLMMessage` also carries an optional
`image` (bytes) + `image_mime_type`, since a receipt is useless to extract from as text alone —
`GeminiProvider` sends that as an extra `Part.from_bytes(...)` alongside the text part.

### Agent workflow / Receipt Processor (`backend/apps/agents/models.py`, `services.py`, `tasks.py`) — step 4

| File | Responsibility |
|---|---|
| `models.py` | `AgentWorkflow` (`TenantScopedModel`) — the reviewable, reversible row for one agent run. `status` is the state machine from CLAUDE.md (`pending → running → needs_review → approved/rejected`), exposed as small methods (`mark_running`, `mark_needs_review`, `mark_approved`, `mark_rejected`) rather than letting callers poke `.status` directly. `receipt` is a direct FK (not a generic relation) — deliberately not generalized to the other three agents yet. |
| `services.py` | `ReceiptProcessorService.run(workflow)` — the actual agent: builds a prompt + the receipt's image bytes, calls the injected `LLMProvider`, strips a markdown code fence if Gemini adds one, parses the result through `ReceiptExtraction`. Any failure (bad JSON, failed validation) still lands the workflow in `needs_review` with `error_message` set — **there is no separate "failed" status**, on purpose (see below). |
| `tasks.py` | `run_receipt_processor(workflow_id)` — a `TenantBoundTask` Celery task. Thin: fetch the row, build a real `GeminiProvider` from settings, hand off to the service. All the actual logic is in the service, so it's unit-tested with zero Celery machinery. |

**Plain-English version:** uploading a receipt creates a `AgentWorkflow` row that starts `pending`.
A Celery task flips it to `running`, sends the receipt's image + a prompt to Gemini, and validates
whatever comes back through the same `ReceiptExtraction` safety gate from step 3. Whether that
succeeds or fails, the row ends up in `needs_review` — a clean extraction carries the data for a
human to confirm; a failure carries an explanation instead, so "the AI couldn't read this" is
something a human sees and acts on, not a silent crash. `approved`/`rejected` are defined on the
model now (full state machine, per CLAUDE.md) but nothing transitions to them yet — that's step 5+,
once there's an endpoint for a human to actually confirm or reject.

**Why no "failed" status:** CLAUDE.md's spec names exactly four states
(`pending/running/needs_review/approved/rejected`). Rather than quietly adding a fifth, a
processing failure is treated as just another reason a human needs to look at this receipt —
which is what `needs_review` already means. The failure is visible via `error_message`, not a new
enum value.

Real Gemini calls were smoke-tested against the live API (multimodal image input included) using
the key you provided — see the "How to run / verify" section below for the exact commands if you
want to re-run them yourself.

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
7. **Gemini, not OpenAI/Anthropic, for the first real provider.** CLAUDE.md's example code names
   OpenAI/Anthropic, but the architecture point — depend on the `LLMProvider` Protocol, not a
   vendor — holds regardless of which SDK sits behind it. User supplied a Gemini key, so
   `GeminiProvider` (`apps/agents/providers/gemini.py`, `google-genai` SDK) is the first concrete
   implementation. Also had to add `[tool.setuptools] packages = []` to `backend/pyproject.toml` —
   without it, `pip install -e .` broke (setuptools couldn't guess a single package between
   `apps/` and `config/`); this project was never meant to be an installable package, just a
   dependency list, so telling setuptools to stop guessing was the fix, not a workaround.

## How to run / verify

**Backend tests (fast, no services needed):**
```bash
cd backend
source .venv/bin/activate          # venv already created on this machine
python -m pytest -q                # expect: 55 passed
python manage.py check             # expect: no issues
```

**A real Gemini key is already set** in `backend/.env` and the repo-root `.env` (both gitignored —
**never paste a real key into chat/commits**). If it ever needs replacing, edit those files
directly:
```bash
# backend/.env (read by manage.py / pytest locally) and repo-root .env (read by docker-compose):
GEMINI_API_KEY=your-real-key-here
GEMINI_MODEL=gemini-2.5-flash        # already the default, override if needed
```
Get a key from Google AI Studio. Smoke-test it without writing any new code — text-only, and then
multimodal (this is what actually proves the Receipt Processor's image path works):
```bash
python manage.py shell -c "
from django.conf import settings
from apps.agents.llm import LLMMessage
from apps.agents.providers.gemini import GeminiProvider
p = GeminiProvider.from_settings(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
print(p.complete([LLMMessage(role='user', content='Say hi in 3 words.')]).content)
"

python manage.py shell -c "
import base64
from django.conf import settings
from apps.agents.llm import LLMMessage
from apps.agents.providers.gemini import GeminiProvider
png_1x1 = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
p = GeminiProvider.from_settings(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
r = p.complete([LLMMessage(role='user', content='What color is this? One word.', image=png_1x1, image_mime_type='image/png')])
print(r.content)
"
```
**Sandbox quirk, not a code bug:** the first real call from this dev sandbox can take 1-2 minutes
to resolve because `generativelanguage.googleapis.com` has IPv6 addresses and this environment
silently drops outbound IPv6 (no fast failure) before the SDK falls back to IPv4. A plain `curl`
to the same host over IPv4 responds instantly. If a real call ever seems to hang, it's this, not
a broken key or a broken `GeminiProvider`.
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

- [x] **Step 2** — `Expense` / `Receipt` models (both inherit `TenantScopedModel`) + `ExpenseService`
      (HTTP-free business logic; thin viewset → serializer → service → model).
- [x] **Step 3** — `LLMProvider` Protocol + a `FakeLLMProvider` (decided: fake-only first, no real API
      keys yet) + a `ReceiptExtraction` Pydantic schema (the validate-or-reject safety boundary).
- [x] **Step 4** — `AgentWorkflow` model with status state machine
      (`pending → running → needs_review → approved/rejected`) + a Celery task (use `TenantBoundTask`)
      that runs the processor and lands in `needs_review`.
- [ ] **Step 5** — receipt upload endpoint (thin) → serializer → `ExpenseService`. This is also the
      natural place for a confirm/reject endpoint (not explicitly named in the build order, but
      step 6's frontend needs something to call, and step 7 wires `AuditLog` to it) — it would call
      `AgentWorkflow.mark_approved()` + `ExpenseService.create()`, or `mark_rejected()`.
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
2. Skim `backend/apps/tenancy/`, `backend/apps/expenses/`, and `backend/apps/agents/` (`llm.py`,
   `models.py`, `services.py`, `tasks.py`) to load the isolation model, expense domain, and the
   agent/LLM boundary into context.
3. Start step 5 (receipt upload endpoint + a confirm/reject endpoint, thin viewset → serializer →
   `ExpenseService` / `AgentWorkflow`) with the design/plan skills, following the same TDD +
   small-commit rhythm.
