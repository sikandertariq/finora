# CLAUDE.md — Finora (Multi-Tenant AI-Agentic Finance OS)

Project context and engineering guardrails for Claude Code. Read this before writing or changing anything.

## What we're building

A multi-tenant SaaS where agencies, small businesses, and freelancers manage invoicing, expenses, and financial workflows. The differentiator is **AI agents** that do the repetitive work (extract receipts, chase overdue invoices, route approvals, run monthly close) and surface everything as **reviewable, reversible, logged suggestions**.

Core principle for the whole product: **the agent proposes, the human disposes.** Finance is a trust domain — no agent silently sends emails, approves expenses, or writes to the ledger without a human-approvable step and an audit trail.

## Build philosophy

- **SOLID, single responsibility, modularity** are the point of this project, not decoration. Every decision below serves testability and clean boundaries.
- **This is a large scope. Build a vertical slice first** (see Build Order). Do not scaffold all four agents up front.
- Prefer the finishable, well-understood choice over the buzzword-maximal one.

---

## Tech stack (LOCKED — do not substitute without asking)

### Backend
- **Django 5 + Django REST Framework** — viewsets, serializers, services pattern.
- **PostgreSQL** as the single source of truth. Use **`pgvector`** for embeddings — do NOT add a separate vector DB (no Pinecone/Weaviate).
- **Celery + Redis** for background tasks and all agent runs. Agent/LLM calls are slow and must never block a request. Redis is also cache + Celery broker.
- **Auth:** `djangorestframework-simplejwt`, with tenant-aware permissions.
- **Config:** `django-environ`. **LLM output validation:** `pydantic`.

### Frontend
- **Next.js 15 (App Router) + TypeScript.**
- **shadcn/ui + Tailwind CSS.**
- **Zustand** — UI/ephemeral state ONLY (open modals, tenant switcher, co-pilot conversation draft).
- **React Query** — ALL server state. Keep this split disciplined; do not mix.
- **react-hook-form + zod** for forms and client validation.
- **Tremor** for dashboards/charts, **TanStack Table** for invoice/expense tables.
- **Hand-written TypeScript interfaces.** (See Explicit Non-Goals.)

### DevOps
- **Docker Compose** locally: django, celery worker, celery beat, postgres, redis — one command up.
- **GitHub Actions** for lint/test/build.
- Deploy: **Vercel** (frontend) + **Render or Fly.io** (backend, workers, managed Postgres/Redis).
- **Testing:** pytest + pytest-django + factory_boy.

---

## Architecture rules

### Dependency flow (one-directional)
```
ViewSet  →  Serializer (validate/shape)  →  Service (business logic)  →  Model
```

- **ViewSets are thin.** Parse, delegate to a service, return. No business logic.
- **Services never touch `request`/`Response`.** They take plain data, return plain data. This makes them unit-testable without HTTP AND reusable from Celery tasks — the agents call the *same* `ExpenseService.create()` a user does. This reuse is non-negotiable; do not duplicate business logic between API and agent paths.
- **Serializers validate and shape only.** No business rules in serializers.

### Multi-tenancy (DECIDED: shared schema, single isolation layer)
- Shared schema. Every tenant-owned row has a `tenant_id`.
- A **`TenantScopedModel` base class** + a manager that **auto-filters by the current tenant**, which is set via **middleware** from the JWT (and/or subdomain).
- The isolation logic lives in exactly ONE place. Do NOT scatter `.filter(tenant=...)` across views.
- Do NOT use schema-per-tenant / `django-tenants`. (Architecture should keep storage strategy swappable in principle, but we implement shared-schema.)

### Agent layer (DECIDED: no heavy framework)
- Do NOT use LangChain / LlamaIndex / CrewAI / AutoGen for the core workflows. Write the agent loop directly against the **provider SDK's native tool-calling** (OpenAI / Anthropic).
- **Every LLM output is validated into a Pydantic model before it touches the DB.** This is the safety boundary (e.g., a `ReceiptExtraction` schema either parses or it doesn't).
- **Dependency inversion for LLM providers.** Services depend on a protocol, not a concrete client:
  ```python
  class LLMProvider(Protocol):
      def complete(self, messages, tools=None) -> LLMResponse: ...
  ```
  Concrete `OpenAIProvider` / `AnthropicProvider` implement it. `AIAgentService` depends on the protocol. Swapping models = config change; tests inject a fake.
- Model workflows **explicitly**: an `AgentWorkflow` row with a status state machine (`pending → running → needs_review → approved / rejected`), driven by Celery tasks. Human-in-the-loop is just a status the UI acts on.
- **Co-pilot chat streaming:** Server-Sent Events via `StreamingHttpResponse` (not websockets). Consume on the frontend in a custom hook that feeds Zustand.

---

## Key models
`Tenant`, `Invoice`, `Expense`, `Receipt`, `AgentWorkflow`, `AuditLog`. Everything tenant-owned inherits `TenantScopedModel`. `AuditLog` records every agent action (reviewable + reversible).

## The four agents
1. **Receipt/Invoice Processor** — extract vendor/amount/date/line items, suggest category, flag duplicates, ask for missing info. User confirms. *(Build this one first.)*
2. **Invoice Chaser** — watch overdue invoices, draft reminders, escalate on schedule. User approves send.
3. **Expense Approver** — route by rule, flag policy violations/anomalies, learn from past approvals.
4. **Monthly Close** — aggregate, reconcile, draft report with plain-language insights.

Plus an **AI Co-Pilot** chat: natural-language queries + proactive nudges.

---

## Explicit non-goals (do NOT add these)

- **No `drf-spectacular` / OpenAPI schema generation.** TS interfaces are hand-written next to their React Query hooks. Do not introduce a codegen pipeline.
- **No agent framework** (LangChain/CrewAI/etc.) in core workflows.
- **No separate vector database.** Use `pgvector`.
- **No schema-per-tenant multi-tenancy.**
- **No business logic in viewsets or serializers.**
- **No websockets** for the co-pilot (use SSE).

---

## Build order (do this, in order)

Build the **Receipt Processor as a full vertical slice** through every layer before generalizing:

1. `Tenant` + `TenantScopedModel` + tenant middleware + tenant-aware JWT permissions.
2. `Expense` / `Receipt` models + `ExpenseService`.
3. `LLMProvider` protocol + one concrete provider + `ReceiptExtraction` Pydantic schema.
4. `AgentWorkflow` model + Celery task that runs the Processor and lands in `needs_review`.
5. `ExpenseViewSet` / receipt upload endpoint (thin) → serializer → service.
6. Frontend: upload zone → React Query mutation → workflow status polling → review/confirm UI → Zustand only for ephemeral UI.
7. `AuditLog` wired to the confirm action.

Only after this slice works end-to-end, generalize to the other three agents.

## Testing expectations
Because services are HTTP-free, unit-test them directly with pytest + factory_boy. Inject a fake `LLMProvider` for agent tests. Aim for services and the tenant-isolation layer to be well covered.

## Definition of done for any feature
Thin viewset, logic in a service, LLM output Pydantic-validated, tenant isolation enforced through the base layer (not ad hoc), agent actions written to `AuditLog`, human-in-the-loop where the action is side-effectful (send/approve/write), and tests on the service.
