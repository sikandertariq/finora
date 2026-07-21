# Finora

Multi-tenant AI-agentic finance OS. Agents propose, humans dispose — every
agent action is reviewable, reversible, and logged.

- Engineering guardrails: [`CLAUDE.md`](CLAUDE.md)
- Designs & plans: [`docs/superpowers/`](docs/superpowers/)
- Public deployment: [`docs/deployment/aws-portfolio.md`](docs/deployment/aws-portfolio.md)

## Status

**Build-order steps 1-7 complete — the Receipt Processor vertical slice is done.**
The multi-tenant isolation layer; `Expense`/`Receipt` models + `ExpenseService`;
an `LLMProvider` protocol with a real `GeminiProvider`; an `AgentWorkflow` state
machine + Celery task that runs the Receipt Processor against Gemini; thin REST
endpoints for expenses, receipt upload, and confirming/rejecting a workflow; a
working Next.js frontend (sign-in, upload, live-polling review/confirm UI); and
an `AuditLog` recording every approve/reject. Manually verified end-to-end
against a real Gemini call with a real receipt image. See [`HANDOFF.md`](HANDOFF.md)
for the full detail. **Next: generalize to the other three agents + Co-Pilot** —
none of that exists yet.

## Layout

```
backend/   Django 5 + DRF (ViewSet -> Serializer -> Service -> Model)
frontend/  Next.js 15 (App Router) + TypeScript
docker-compose.yml   django, celery-worker, celery-beat, postgres, redis
docker-compose.production.yml   one-host AWS production stack
```

## Run with Docker (real runtime)

```bash
cp .env.example .env          # set a real DJANGO_SECRET_KEY (>=32 chars)
docker compose up             # postgres, redis, django, celery worker + beat
docker compose exec django python manage.py migrate
```

- API: http://localhost:8000/api/
- Frontend (separately): `cd frontend && npm run dev` → http://localhost:3000

## Run without Docker (this sandbox's usual setup)

```bash
bash backend/scripts/dev-server.sh   # SQLite, migrates automatically, :8000
cd frontend && npm run dev           # :3000, reads NEXT_PUBLIC_API_BASE_URL (see .env.local.example)
```
For the AI pipeline to actually run end-to-end (not just sit at `pending`), also run a real Redis
+ Celery worker — see the "Running the full stack without Docker" section in
[`HANDOFF.md`](HANDOFF.md) for the exact commands.

## Backend tests

Tests run on in-memory SQLite (dependency-free, fast) via `config.settings.test`.
Postgres + pgvector is the real runtime; SQLite is a faithful substrate for the
current ORM-only layer.

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e . && pip install pytest pytest-django factory-boy
python -m pytest -q
```

## Portfolio deployment

The public portfolio setup uses Vercel for `frontend/` and one manually
startable AWS EC2 host for Django, Celery, PostgreSQL, and Redis. It has no
RDS, NAT gateway, load balancer, paid domain, or inbound SSH. Follow the
[AWS portfolio deployment guide](docs/deployment/aws-portfolio.md) before
making the repository public; it covers secret storage, CloudFormation, Vercel,
manual start/stop, and the January 2027 cleanup deadline.

## Auth smoke test

```bash
# in the django container / shell:
python manage.py shell -c "
from django.contrib.auth.models import User
from apps.tenancy.models import Tenant, TenantMembership
t = Tenant.objects.create(name='Acme', slug='acme')
u = User.objects.create_user('alice', password='pw12345!')
TenantMembership.objects.create(user=u, tenant=t)
"

curl -s -X POST localhost:8000/api/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"pw12345!"}'

curl -s localhost:8000/api/whoami/ -H "Authorization: Bearer <access-token>"
# -> {"user":"alice","tenant_id":1}
```

## Expense & Receipt Processor smoke test

Using the `<access-token>` from above:

```bash
# a manual expense, no AI involved
curl -s -X POST localhost:8000/api/expenses/ \
  -H "Authorization: Bearer <access-token>" -H 'Content-Type: application/json' \
  -d '{"vendor":"Staples","amount":"42.50","expense_date":"2026-07-01"}'

# upload a receipt -> creates a Receipt + an AgentWorkflow, starts the Celery task
curl -s -X POST localhost:8000/api/receipts/ \
  -H "Authorization: Bearer <access-token>" -F "file=@/path/to/receipt.jpg"
# -> {"id": 1, "status": "pending", "receipt": {...}, ...}   (needs the celery worker running)

# poll it (status moves pending -> running -> needs_review)
curl -s localhost:8000/api/agent-workflows/1/ -H "Authorization: Bearer <access-token>"

# confirm it -> creates the Expense, links it back to the workflow
curl -s -X POST localhost:8000/api/agent-workflows/1/confirm/ \
  -H "Authorization: Bearer <access-token>" -H 'Content-Type: application/json' -d '{}'
# add e.g. {"vendor": "Staples Inc."} instead of {} to correct the AI before saving

# or reject it instead -> no Expense created
curl -s -X POST localhost:8000/api/agent-workflows/1/reject/ \
  -H "Authorization: Bearer <access-token>" -H 'Content-Type: application/json' -d '{}'

# see what got logged for that workflow -- who did what, and (for a confirm) what was saved
curl -s "localhost:8000/api/audit-logs/?workflow=1" -H "Authorization: Bearer <access-token>"
```

## Architecture notes

- **Tenant isolation lives in one place** (`apps/tenancy`). A `contextvars`
  variable carries the current tenant through both HTTP requests (middleware,
  from the JWT `tenant_id` claim) and Celery tasks (`TenantBoundTask`). The
  scoped manager fails loud when no tenant is set; cross-tenant access is opt-in
  via `unscoped()` / the `all_tenants` manager.
- **Why the middleware decodes the JWT itself:** DRF authenticates inside the
  view (after Django middleware), so `request.auth` is unset in middleware. The
  middleware validates the bearer token via SimpleJWT directly to resolve the
  tenant before the view runs.
- **Frontend state split is deliberate:** React Query owns all server state
  (the workflow, its status, its data); Zustand owns exactly one thing —
  which workflow is currently open for review (`activeWorkflowId`). The auth
  token is neither, and gets its own small module (`lib/auth.ts`) instead of
  being forced into one of the two.
