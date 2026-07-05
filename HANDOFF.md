# Finora — Handoff / Continue Here

> Living status doc. If you're a fresh session: read [`CLAUDE.md`](CLAUDE.md) (the locked
> spec) first, then this file for *where we actually are*. Last updated: **2026-07-06**.

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
- **Build-order step 5 is DONE and green:** thin REST endpoints — `ExpenseViewSet` (full CRUD),
  `POST /api/receipts/` (upload → starts the agent), and `AgentWorkflowViewSet` (list/retrieve +
  `confirm`/`reject` actions). All business logic stayed in `ExpenseService` /
  `AgentWorkflowService` (new); the view layer only parses/validates/delegates/responds.
- **Build-order step 6 is DONE:** the actual frontend — sign-in, an upload zone, live polling, and
  a review/confirm form, wired to the real API. `django-cors-headers` added to the backend (a
  browser on a different port can't call the API without it). **Manually verified against a real,
  running stack** (real Postgres-alternative SQLite, real Redis, real Celery worker, real Gemini
  call, real synthetic receipt image) — see the writeup below for exactly what that proved.
- **Build-order step 7 is DONE:** `AuditLog` model + wired into `AgentWorkflowService.approve()`/
  `.reject()` + a minimal read-only `GET /api/audit-logs/` (optionally `?workflow=<id>`) so the log
  is actually reviewable, not write-only. Manually verified over real HTTP against the running
  dev stack, not just `pytest`.
- **All work is on branch `feat/tenant-foundation`**, **not merged to `main`**, **no git remote** configured.
- **Backend tests: 82/82 passing.** Frontend builds and lints clean.
- **Next up:** the whole build order (steps 1–7) is done. Per CLAUDE.md, generalize the vertical
  slice to the other three agents (Invoice Chaser, Expense Approver, Monthly Close) + the
  AI Co-Pilot — none of that exists yet.

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
│  │                         # ReceiptProcessorService + Celery task (step 4) +
│  │                         # AgentWorkflowService + REST endpoints (step 5) +
│  │                         # AuditLog + /api/audit-logs/ (step 7)
│  ├─ scripts/dev-server.sh  # runs the API on SQLite, no Docker needed (step 6)
│  ├─ tests/                 # pytest suite + throwaway ScopedThing model + factories.py + conftest.py
│  ├─ pyproject.toml         # deps + pytest config
│  └─ .venv/                 # local venv (gitignored)
├─ .claude/launch.json       # preview_start configs for backend + frontend (step 6)
└─ frontend/                 # Next.js 15 — sign-in, upload zone, live-polling review/confirm UI (step 6)
   └─ src/
      ├─ lib/                # types.ts (hand-written), api.ts (fetch client), auth.ts (token hook)
      ├─ store/               # workflow-ui-store.ts — the one Zustand store (see below)
      ├─ hooks/use-receipts.ts # React Query: upload/poll/confirm/reject
      └─ components/          # login-form, upload-zone, workflow-panel, review-form
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

### REST endpoints (`backend/apps/expenses/views.py`, `apps/agents/views.py`, `serializers.py`) — step 5

| Endpoint | Does |
|---|---|
| `POST /api/expenses/`, full CRUD | `ExpenseViewSet` — thin `ModelViewSet`; `ExpenseSerializer.create()`/`update()` call `ExpenseService`, translating a raised `ValueError` (e.g. non-positive amount) into a DRF `ValidationError` so it's a 400, not a 500. This is the one existing rule (from step 2) actually reachable over HTTP for the first time. |
| `POST /api/receipts/` | `ReceiptUploadView` — validates a `file` was sent, creates the `Receipt`, then hands off entirely to `AgentWorkflowService.start_receipt_processing()`. Returns the new `AgentWorkflow` (status `pending`), not the `Receipt` — that's the resource the client actually needs to poll. |
| `GET /api/agent-workflows/`, `/{id}/` | `AgentWorkflowViewSet` — read-only list/retrieve, for step 6's polling. |
| `POST /api/agent-workflows/{id}/confirm/` | Optional body lets a human correct any field before it's saved (e.g. `{"vendor": "Staples Inc."}`) — everything omitted is taken as-is from what the AI extracted. Calls `AgentWorkflowService.approve()`, which builds `ExpenseService.create()`'s kwargs from `extracted_data` + overrides, then marks the workflow `approved` and links the resulting `Expense`. |
| `POST /api/agent-workflows/{id}/reject/` | Marks `rejected`. No `Expense` is created. |

**New service:** `AgentWorkflowService` (in `apps/agents/services.py`, alongside `ReceiptProcessorService`)
holds `start_receipt_processing()`, `approve()`, `reject()` — the human-facing actions on a
workflow, as opposed to `ReceiptProcessorService`, which is the AI step itself. `approve()` reuses
`ExpenseService.create()` — the exact call a manual "add expense" would make — so a human
confirming an AI's extraction and a human typing an expense by hand are indistinguishable to the
database once they land.

**A real bug the tests caught immediately:** the first draft of both viewsets set
`queryset = Expense.objects.all()` as a class attribute. That expression runs once, at import
time, when Django loads the URLconf — long before any request has set a tenant in context — so it
immediately raised `TenantContextRequired` and broke every test. Fixed by overriding
`get_queryset()` instead, which DRF calls fresh on every request, by which point the middleware has
already set the tenant. Rule of thumb going forward: any queryset built from a `TenantScopedModel`
inside a view must be inside a method, never a bare class attribute.

**A second, more subtle bug the automated tests did *not* catch — a manual smoke test against a
real running server did.** Every existing Celery test called `.apply()` (`echo_current_tenant.apply(...)`,
`run_receipt_processor.apply(...)`) — a synchronous, direct call that never goes through
`apply_async`. The real code path (`AgentWorkflowService.start_receipt_processing`) calls `.delay()`,
which does go through `apply_async`, which runs a pre-flight check validating kwargs against the
task's own `run()` signature *before* `TenantBoundTask.__call__` ever gets a chance to strip
`tenant_id` out. Since `run_receipt_processor(workflow_id)` never declares `tenant_id`, every real
`.delay()` call raised `TypeError: run_receipt_processor() got an unexpected keyword argument
'tenant_id'` — a 500 on the one endpoint this entire slice exists to support, invisible to all 72
tests that existed at the time. **Fixed with `typing = False` on `TenantBoundTask`**
(`apps/tenancy/tasks.py`), which disables that pre-flight check for anything built on this base —
correct, since the base's whole design is to accept a kwarg the concrete task doesn't declare.
Added a regression test (`test_task_can_be_dispatched_via_delay_not_just_apply` in
`tests/test_tasks.py`) that calls `.delay()`, not `.apply()`, and verified it actually fails
without the fix before moving on. **Lesson for future steps: `.apply()` in a test is not a
substitute for at least one `.delay()`/`.apply_async()` call somewhere** — they exercise different
Celery code paths and can diverge exactly like this.

**Why `POST /api/receipts/` returns an `AgentWorkflow`, not a `Receipt`:** the receipt file itself
isn't what the frontend polls or shows a review UI for — the workflow tracking its processing is.
Naming the URL after the resource being uploaded (`receipts`) while returning the resource that
matters next (the workflow) was a deliberate mismatch, not an oversight.

### Frontend (`frontend/src/`) — step 6

| File | Responsibility |
|---|---|
| `lib/types.ts` | Hand-written TS interfaces mirroring the DRF serializers exactly (no OpenAPI codegen, per CLAUDE.md). Keep these in sync by hand when a serializer changes. |
| `lib/api.ts` | Plain `fetch` wrapper — `login`, `uploadReceipt`, `getWorkflow`, `confirmWorkflow`, `rejectWorkflow`. Nothing framework-specific; React Query hooks call these. |
| `lib/auth.ts` | `useAuth()` — the access token, backed by `localStorage`, read via `useSyncExternalStore` (not `useState`+`useEffect`; see "why" below). **Deliberately not the Zustand store** — a session token is persistent app state, not the ephemeral UI-only state Zustand is reserved for here. No refresh-token flow yet (see limitation below). |
| `store/workflow-ui-store.ts` | The **one** Zustand store: `activeWorkflowId` — which workflow is currently open for review. Same shape as CLAUDE.md's own "tenant switcher" example. The workflow's actual data (status, extracted fields) is server state and lives in React Query, keyed off this id — never duplicated into Zustand. |
| `hooks/use-receipts.ts` | React Query: `useUploadReceipt` (mutation), `useWorkflow(id)` (query — polls every 2s while `pending`/`running`, stops once settled), `useConfirmWorkflow`/`useRejectWorkflow` (mutations). |
| `components/` | `login-form.tsx`, `upload-zone.tsx` (drag-drop + file picker), `workflow-panel.tsx` (status badge + routes to the review form), `review-form.tsx` (react-hook-form + zod, pre-filled from `extracted_data`, every field overridable before saving). |

**Why `useSyncExternalStore` for the auth token, not `useState`+`useEffect`:** reading
`localStorage` inside an effect and calling `setState` synchronously is exactly the pattern
React's own lint rule (`react-hooks/set-state-in-effect`) now flags — it causes an extra render
and doesn't handle server/client mismatches cleanly. `useSyncExternalStore` is the primitive React
ships specifically for "a value lives outside React, keep a component in sync with it," and it's
SSR-safe out of the box (no manual "hydrated" flag needed).

**A real bug the tests couldn't have caught, only a live browser could:** `ExpenseViewSet` and
`AgentWorkflowViewSet` both worked fine in `pytest` but the first live upload 500'd —
`django-cors-headers` wasn't installed, so the browser (a different origin/port than the API)
silently blocked the request before Django even logged CORS was the issue clearly. Fixed by adding
`corsheaders` + `CorsMiddleware` + `CORS_ALLOWED_ORIGINS` (defaults to `http://localhost:3000`).
**No Django test would ever catch a missing CORS header** — the Django test client doesn't enforce
browser-origin rules, so this class of bug is invisible to `pytest` by construction, not by
oversight. This is exactly why "run it in an actual browser" matters even after a green test suite.

**Manually verified against a real, fully running stack — not just `pytest` and not just a mocked
preview:**
1. Installed and started real Redis (`brew install redis`) and a real Celery worker consuming the
   real queue — `apps/agents/tasks.py::run_receipt_processor` running for real, not `.apply()`'d
   directly like the automated tests do.
2. Generated a synthetic but genuine receipt image (Pillow, plain text drawn onto a PNG: vendor,
   line items, a total) and uploaded it through the actual browser UI (simulated via
   `DataTransfer`/`File`, since there's no real filesystem dialog to click in this environment).
3. Watched the workflow move `pending` → `running` (polling, live) → `needs_review`, confirmed via
   `lsof` that the delay was the same real IPv6-blackhole-then-IPv4-fallback quirk noted in step 3
   (a `SYN_SENT` connection sitting open to one of Gemini's real IPv6 addresses) — not a bug, just
   this sandbox's networking.
4. Gemini correctly read the image and extracted **the exact vendor name, total, and date** that
   were drawn onto it — proof the multimodal path (image bytes → Gemini → `ReceiptExtraction` →
   review form) genuinely works, not just that it doesn't crash.
5. Clicked "Confirm & save" in the real UI, then fetched `/api/expenses/1/` directly and got back
   a real, correctly-populated `Expense` row linked to the receipt.
6. **Found a real, separate limitation in the process, not injected on purpose:** the default
   SimpleJWT access token lifetime (5 minutes) is shorter than this sandbox's IPv6 delay, so the
   token expired mid-poll. React Query's default behavior (keep showing last-good data on a failed
   background refetch) meant the UI didn't break, just stopped updating — signing in again
   immediately showed the correct, current state. **No refresh-token flow exists yet** — logged as
   a known gap, not fixed now, since building it wasn't in this step's scope.

### AuditLog (`backend/apps/agents/models.py`, `services.py`, `views.py`) — step 7

| File | Responsibility |
|---|---|
| `models.py` | `AuditLog` (`TenantScopedModel`) — `workflow` (FK), `actor` (FK to `User`), `action` (plain string, e.g. `"approved"`/`"rejected"`), `metadata` (JSON, whatever detail that action needs to record). **Append-only by convention** — no `update()` method exists or should exist; a row is written once and never touched again. |
| `services.py` | `AgentWorkflowService.approve()`/`.reject()` each now write exactly one `AuditLog` row as their last step. `approve()`'s metadata captures `resulting_expense_id` and any human `overrides` — enough to answer "what actually got saved, and did a human change anything first?" without a second query. |
| `views.py` | `AuditLogViewSet` — read-only `GET /api/audit-logs/`, optionally `?workflow=<id>`. Nothing ever writes through this endpoint; only the service does. |

**Plain-English version:** every time a human approves or rejects a receipt, one permanent line
gets written down — who did it, to which workflow, and (for an approval) which expense it produced
and whether they changed anything from what the AI suggested first. This is the literal
"logged" half of "the agent proposes, the human disposes, and it's reviewable, reversible, and
logged" — CLAUDE.md's core principle for the whole product, now actually true for one action.

**Why `action` is a plain string, not a choices enum:** same reasoning as `AgentWorkflow.workflow_type`
in step 4 — the other three agents will each introduce their own action names later, and none of
them should need to edit a shared enum in `apps/agents/` to do it.

**Why a read endpoint was added even though the build-order line only said "wired to the confirm
action":** an audit log nobody can ever read isn't "reviewable" in any meaningful sense — write-only
logging satisfies the letter of step 7 but not the principle it exists to serve. The endpoint is
deliberately minimal (list + filter by workflow, no UI for it yet — that's frontend work, out of
scope here).

**Not done in this step, on purpose:** "reversible" (undoing an approval — e.g. deleting the
resulting `Expense` and reopening the workflow) is a real feature with its own business rules and
wasn't part of what step 7 asked for. `AuditLog` records *that* something happened; it doesn't yet
give anyone a button to undo it.

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
python -m pytest -q                # expect: 82 passed
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

**Full stack (real runtime — needs Docker daemon running):**
```bash
cp .env.example .env               # set a real DJANGO_SECRET_KEY (>=32 chars)
docker compose up
docker compose exec django python manage.py migrate
```
API at http://localhost:8000/api/ · frontend: `cd frontend && npm run dev` → http://localhost:3000

**Manual auth smoke test:** see the "Auth smoke test" section in [`README.md`](README.md).

**Running the full stack without Docker (what this sandbox actually uses):**
```bash
# backend (SQLite, no Postgres/Docker needed) + frontend, via the preview tool's launch.json:
#   configuration "backend"  -> backend/scripts/dev-server.sh, port 8000
#   configuration "frontend" -> npm run dev --prefix frontend, port 3000
# or by hand:
bash backend/scripts/dev-server.sh          # migrates dev.sqlite3, runs on :8000
cd frontend && npm run dev                   # :3000

# separately, for the agent pipeline to actually run (not just enqueue and sit pending):
brew install redis && redis-server &         # if not already running
cd backend && source .venv/bin/activate
DJANGO_SETTINGS_MODULE=config.settings.dev DATABASE_URL="sqlite:///$(pwd)/dev.sqlite3" \
  DJANGO_SECRET_KEY="dev-only-not-for-production-please-change" \
  celery -A config worker --loglevel=info
```
Seed a tenant/user the same way as the auth smoke test, then use the app at `localhost:3000`.

## What's NOT done yet (the remaining build order)

Per [`CLAUDE.md`](CLAUDE.md), build the **Receipt Processor as a vertical slice** next, in order:

- [x] **Step 2** — `Expense` / `Receipt` models (both inherit `TenantScopedModel`) + `ExpenseService`
      (HTTP-free business logic; thin viewset → serializer → service → model).
- [x] **Step 3** — `LLMProvider` Protocol + a `FakeLLMProvider` (decided: fake-only first, no real API
      keys yet) + a `ReceiptExtraction` Pydantic schema (the validate-or-reject safety boundary).
- [x] **Step 4** — `AgentWorkflow` model with status state machine
      (`pending → running → needs_review → approved/rejected`) + a Celery task (use `TenantBoundTask`)
      that runs the processor and lands in `needs_review`.
- [x] **Step 5** — receipt upload endpoint (thin) → serializer → `ExpenseService`, plus
      `ExpenseViewSet` (full CRUD) and `AgentWorkflowViewSet`'s `confirm`/`reject` actions
      (not explicitly named in the build order, but step 6's frontend needs something to call,
      and step 7 wires `AuditLog` to it).
- [x] **Step 6** — frontend: upload zone → React Query mutation → poll workflow status → review/confirm
      UI (Zustand only for ephemeral UI state). Manually verified against a real running stack
      (see the writeup above) — real Gemini call, correct extraction, correct saved Expense.
- [x] **Step 7** — `AuditLog` wired into `AgentWorkflowService.approve()`/`.reject()`, plus a
      minimal read-only `GET /api/audit-logs/` (see the writeup above for why the read endpoint
      was added despite not being named explicitly).

**The build order (steps 1–7) is complete.** Next: generalize to the other three agents (Invoice
Chaser, Expense Approver, Monthly Close) + the AI Co-Pilot. None of that exists yet — this vertical
slice (Receipt Processor only) is the whole product so far.

## Conventions to keep following

- **Dependency flow:** ViewSet (thin) → Serializer (validate/shape) → Service (logic) → Model.
  Services never touch `request`/`Response` so agents can reuse them.
- **New tenant-owned model?** Inherit `TenantScopedModel` — you get isolation for free; never write
  `.filter(tenant=...)` by hand.
- **Never set `queryset = Model.objects.all()` as a viewset class attribute** on a
  `TenantScopedModel` — override `get_queryset()` instead (see step 5's writeup above for why).
- **When testing a Celery task, call `.delay()`/`.apply_async()` at least once, not only
  `.apply()`** — they go through different Celery code paths and can diverge (see step 5's
  writeup above for the real bug this caused).
- **TDD:** write the failing test, watch it fail, implement, watch it pass, commit. Small commits.
- **Every LLM output** must be parsed into a Pydantic model before touching the DB.
- **React Query owns all server state; Zustand owns only ephemeral UI state** — don't blur this.
  A session token is neither; it gets its own small module (`lib/auth.ts`), not Zustand.
- **A green `pytest` run does not mean the feature works in a browser.** CORS, token expiry,
  timing, and real third-party API behavior are all invisible to the Django test client. Run it
  for real — see step 6's writeup above for two bugs/gaps this caught that automated tests could
  not have.
- **Any state-changing action a human takes on an agent's output writes an `AuditLog` row** as the
  last step of the service method that performs it (see step 7) — not in the viewset, not as an
  afterthought. When the next agent's approve/reject-equivalent action gets built, it gets this too.
- **Do a review** and ask a "why this over that?" design question after any non-trivial code (per the
  practice format in the user's global setup).

## Suggested first move in a new session

1. `git branch --show-current` → confirm on `feat/tenant-foundation` (or merge to `main` first).
2. Skim `backend/apps/tenancy/`, `backend/apps/expenses/`, `backend/apps/agents/` (`llm.py`,
   `models.py`, `services.py`, `tasks.py`, `views.py`), and `frontend/src/` (`lib/`, `hooks/`,
   `components/`) to load the isolation model, expense domain, agent/LLM/REST boundary, and the
   frontend into context — this is the full Receipt Processor vertical slice, steps 1–7.
3. The locked build order is done. Next real decision: which of the other three agents (Invoice
   Chaser, Expense Approver, Monthly Close) or the Co-Pilot to build next, and whether to first
   generalize any of `AgentWorkflow`/`AgentWorkflowService` (currently receipt-specific in a few
   places — e.g. `AgentWorkflow.receipt` is a direct FK, not generic) before adding a second agent,
   or let the second agent's real needs drive that refactor instead of guessing now. Bring this to
   the user as a real decision point, not something to assume.
