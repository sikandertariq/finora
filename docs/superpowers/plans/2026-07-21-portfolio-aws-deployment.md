# Finora Portfolio AWS Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Finora deployable as a secure, manually startable AWS portfolio demo with Vercel serving the frontend.

**Architecture:** A production Django configuration and Docker Compose stack run on one EC2 instance. Vercel rewrites browser `/api/*` requests to the HTTPS Elastic-IP origin. GitHub Actions validates every change, ships a GHCR backend image, and uses AWS OIDC plus SSM for deployment and power control.

**Tech Stack:** Django 5.2, DRF, SimpleJWT, Celery, Redis, PostgreSQL/pgvector, Gunicorn, WhiteNoise, Nginx, Certbot, Docker Compose, GitHub Actions, GHCR, AWS CloudFormation/SSM/EC2, Vercel, Next.js, TypeScript.

## Global Constraints

- Keep viewsets thin: ViewSet → Serializer → Service → Model.
- Every tenant-owned model continues to inherit `TenantScopedModel`; never add ad-hoc tenant filters.
- Every LLM output remains Pydantic-validated before database writes.
- Do not commit secrets, `.env` files, AWS credentials, or Gemini credentials.
- Use one `t3.micro`, one 30 GB gp3 volume, and no managed AWS database, cache, NAT gateway, load balancer, or paid domain.
- Test backend behavior with pytest; frontend changes must pass lint and production build.

---

### Task 1: Production Django configuration and health endpoint

**Files:**
- Create: `backend/config/settings/production.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/test_production_settings.py`
- Modify: `backend/tests/test_auth.py`

**Interfaces:**
- Produces `config.settings.production`, selected by `DJANGO_SETTINGS_MODULE`.
- Produces unauthenticated `GET /api/health/` returning `{"status": "ok"}` only when Django can query the configured database.

- [ ] **Step 1: Write failing production-settings and health tests**

```python
def test_health_endpoint_is_public_and_reports_ok(api_client):
    response = api_client.get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_production_settings_require_a_secret_key(monkeypatch):
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured):
        reload_production_settings()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && python -m pytest tests/test_production_settings.py -q`

Expected: FAIL because neither the endpoint nor production module exists.

- [ ] **Step 3: Implement production-only security settings and health view**

```python
# config/settings/production.py
from .base import *  # noqa

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
```

Add WhiteNoise immediately after `SecurityMiddleware`, add a database-checking
health view under `/api/health/`, and add `gunicorn` plus `whitenoise` to the
runtime dependencies.

- [ ] **Step 4: Run targeted tests and Django production checks**

Run: `cd backend && python -m pytest tests/test_production_settings.py tests/test_auth.py -q && DJANGO_SETTINGS_MODULE=config.settings.production DJANGO_SECRET_KEY=test-secret-key-which-is-long-enough DJANGO_ALLOWED_HOSTS=example.test DATABASE_URL=sqlite:///:memory: python manage.py check --deploy`

Expected: tests pass; check output contains no deployment errors.

- [ ] **Step 5: Commit**

```bash
git add backend/config backend/pyproject.toml backend/tests/test_production_settings.py backend/tests/test_auth.py
git commit -m "feat: add production Django configuration"
```

### Task 2: Upload and API abuse controls

**Files:**
- Modify: `backend/apps/expenses/serializers.py`
- Modify: `backend/apps/expenses/views.py`
- Modify: `backend/config/settings/base.py`
- Create: `backend/tests/test_receipt_upload_limits.py`

**Interfaces:**
- `ReceiptUploadSerializer` accepts JPEG, PNG, WEBP, and PDF only when its file
  size is no more than `MAX_RECEIPT_UPLOAD_BYTES`.
- `ReceiptUploadView` uses the `receipt_upload` DRF throttle scope.

- [ ] **Step 1: Write failing validation and throttle tests**

```python
def test_receipt_upload_rejects_oversized_file(authenticated_client, uploaded_file):
    response = authenticated_client.post("/api/receipts/", {"file": uploaded_file(size=6 * 1024 * 1024)})
    assert response.status_code == 400
    assert "5 MB" in str(response.data)

def test_receipt_upload_rejects_unsupported_mime_type(authenticated_client, uploaded_file):
    response = authenticated_client.post("/api/receipts/", {"file": uploaded_file(name="ledger.exe", content_type="application/octet-stream")})
    assert response.status_code == 400
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `cd backend && python -m pytest tests/test_receipt_upload_limits.py -q`

Expected: FAIL because arbitrary files are currently accepted.

- [ ] **Step 3: Implement serializer validation and scoped throttling**

```python
class ReceiptUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        if value.size > settings.MAX_RECEIPT_UPLOAD_BYTES:
            raise serializers.ValidationError("Receipt files must be 5 MB or smaller.")
        if value.content_type not in settings.ALLOWED_RECEIPT_MIME_TYPES:
            raise serializers.ValidationError("Upload a JPEG, PNG, WEBP, or PDF receipt.")
        return value
```

Configure `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` for `login` and
`receipt_upload`, then add `throttle_scope = "receipt_upload"` to the upload
view. Keep creation and workflow dispatch inside existing services.

- [ ] **Step 4: Run focused tests**

Run: `cd backend && python -m pytest tests/test_receipt_upload_limits.py tests/test_receipt_upload_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/expenses backend/config/settings/base.py backend/tests/test_receipt_upload_limits.py
git commit -m "feat: harden receipt uploads for public demo"
```

### Task 3: Demo tenant seed/reset and startup recovery

**Files:**
- Create: `backend/apps/tenancy/demo.py`
- Create: `backend/apps/tenancy/management/commands/reset_demo_data.py`
- Modify: `backend/apps/agents/tasks.py`
- Modify: `backend/config/settings/base.py`
- Create: `backend/tests/test_demo_data_service.py`

**Interfaces:**
- `DemoDataService.reset(*, password: str) -> Tenant` removes and recreates only
  the `finora-demo` tenant and returns it.
- `reset_demo_data` management command invokes the service using
  `DEMO_USER_PASSWORD`.
- `recover_demo` Celery task resets demo data and dispatches one overdue scan.

- [ ] **Step 1: Write failing tenant-isolation tests**

```python
def test_demo_reset_does_not_delete_another_tenant(db, other_tenant):
    DemoDataService.reset(password="demo-password")
    assert Tenant.objects.filter(id=other_tenant.id).exists()

def test_demo_reset_creates_shared_login_and_overdue_invoice(db):
    tenant = DemoDataService.reset(password="demo-password")
    assert TenantMembership.objects.get(tenant=tenant).user.username == "demo"
    assert Invoice.all_tenants.filter(tenant=tenant, due_date__lt=timezone.localdate()).exists()
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `cd backend && python -m pytest tests/test_demo_data_service.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement demo service, command, task, and beat schedule**

Create records via unscoped model managers only at the reset boundary, then set
tenant context before creating tenant-scoped expenses, invoices, workflows, and
audit rows. Seed one overdue invoice so the recovery scan produces a reviewable
Invoice Chaser workflow. Add a daily `reset-demo-data` Celery Beat entry and a
thin task that calls the service then `scan_overdue_invoices.delay()`.

- [ ] **Step 4: Run service, task, and regression tests**

Run: `cd backend && python -m pytest tests/test_demo_data_service.py tests/test_scan_overdue_invoices_task.py tests/test_scoping.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/tenancy backend/apps/agents/tasks.py backend/config/settings/base.py backend/tests/test_demo_data_service.py
git commit -m "feat: seed and reset portfolio demo data"
```

### Task 4: Persistent browser session, demo login, and backend-offline UI

**Files:**
- Modify: `frontend/src/lib/auth.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/login-form.tsx`
- Modify: `frontend/src/app/page.tsx`
- Create: `frontend/src/components/backend-status.tsx`
- Modify: `frontend/next.config.ts`
- Modify: `frontend/.env.local.example`

**Interfaces:**
- `useAuth()` returns `token`, `signIn({access, refresh})`, and `signOut()`.
- `request()` refreshes once through `/token/refresh/` after a `401`.
- Production uses `/api` as the browser API base; local development uses
  `NEXT_PUBLIC_API_BASE_URL`.
- `next.config.ts` rewrites `/api/:path*` to `BACKEND_ORIGIN/api/:path*` when
  `BACKEND_ORIGIN` is present at Vercel build time.

- [ ] **Step 1: Add build-time type checks for the changed client interfaces**

```ts
const session = await login("demo", "demo-password");
signIn(session);
await refreshAccessToken(session.refresh);
```

- [ ] **Step 2: Verify the current build does not support the new interface**

Run: `cd frontend && npm run build`

Expected: current build succeeds but lacks refresh storage, demo button, and
rewrites; add the type assertions in the implementation branch before coding.

- [ ] **Step 3: Implement session refresh and portfolio UX**

Store access and refresh tokens under separate `finora.*` localStorage keys.
On `401`, refresh one time and repeat the original request with the new access
token. Keep the refresh request itself non-retrying. The login form presents a
button that fills public `NEXT_PUBLIC_DEMO_USERNAME` and
`NEXT_PUBLIC_DEMO_PASSWORD` values. Add a health query that displays a concise
offline banner without blocking the Vercel-hosted shell. Add a demo-data warning
and no-sensitive-receipts notice.

- [ ] **Step 4: Run lint and production build**

Run: `cd frontend && npm run lint && npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/next.config.ts frontend/.env.local.example
git commit -m "feat: add portfolio demo session and offline UX"
```

### Task 5: Production image, Compose stack, HTTPS, and host scripts

**Files:**
- Modify: `backend/Dockerfile`
- Create: `docker-compose.production.yml`
- Create: `deploy/ec2/compose.env.example`
- Create: `deploy/ec2/deploy.sh`
- Create: `deploy/ec2/recover.sh`
- Create: `deploy/ec2/nginx.conf`
- Create: `deploy/ec2/renew-ip-certificate.sh`
- Create: `deploy/ec2/finora-certbot.timer`
- Create: `deploy/ec2/finora-certbot.service`
- Create: `backend/tests/test_production_artifacts.py`

**Interfaces:**
- Production image runs `gunicorn config.wsgi:application` by default.
- Production Compose receives secrets only through `/srv/finora/.env`.
- `deploy.sh <image-tag>` pulls, migrates, restarts, recovers demo state, and
  checks `https://<elastic-ip>/api/health/`.

- [ ] **Step 1: Write failing artifact assertions**

```python
def test_production_compose_never_binds_postgres_or_redis_publicly():
    compose = Path("../docker-compose.production.yml").read_text()
    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose

def test_production_dockerfile_uses_gunicorn():
    assert "gunicorn" in Path("../backend/Dockerfile").read_text()
```

- [ ] **Step 2: Run artifact tests to verify failure**

Run: `cd backend && python -m pytest tests/test_production_artifacts.py -q`

Expected: FAIL because production artifacts do not exist.

- [ ] **Step 3: Build production stack**

Use no source bind mounts, no public database/cache ports, persistent bind
mounts below `/srv/finora/data`, Redis AOF, one Celery worker, `restart:
unless-stopped`, health checks, and log rotation. Configure Nginx to expose only
`/api/` and ACME challenge paths. Certbot must request a short-lived IP
certificate with `--preferred-profile shortlived --ip-address "$ELASTIC_IP"`
and reload Nginx after renewal. `recover.sh` runs the management command then
dispatches recovery only after worker health is available.

- [ ] **Step 4: Validate artifacts locally**

Run: `docker compose -f docker-compose.production.yml --env-file deploy/ec2/compose.env.example config && cd backend && python -m pytest tests/test_production_artifacts.py -q`

Expected: Compose parses without secrets; tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile docker-compose.production.yml deploy/ec2 backend/tests/test_production_artifacts.py
git commit -m "feat: add production container deployment stack"
```

### Task 6: AWS infrastructure and GitHub delivery workflows

**Files:**
- Create: `infra/aws/finora.yaml`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/deploy-backend.yml`
- Create: `.github/workflows/demo-power.yml`
- Create: `.github/workflows/secret-scan.yml`
- Create: `infra/aws/README.md`

**Interfaces:**
- CloudFormation parameters: `RepositoryOwner`, `RepositoryName`, `GitHubBranch`,
  `NotificationEmail`, and `KeyPairName` only if an emergency SSH fallback is
  deliberately enabled.
- Stack outputs: `InstanceId`, `ElasticIp`, `GitHubDeployRoleArn`, and
  `ParameterPrefix`.
- `deploy-backend.yml` assumes the OIDC role and invokes SSM `AWS-RunShellScript`.
- `demo-power.yml` dispatches start, stop, restart, or status for the output
  instance ID.

- [ ] **Step 1: Write static infrastructure checks**

```python
def test_cloudformation_does_not_open_ssh_or_create_paid_managed_services():
    template = Path("../infra/aws/finora.yaml").read_text()
    assert 'FromPort: 22' not in template
    assert "AWS::RDS::DBInstance" not in template
    assert "AWS::ElastiCache::" not in template
```

- [ ] **Step 2: Run the test to verify failure**

Run: `cd backend && python -m pytest tests/test_production_artifacts.py -q`

Expected: FAIL until the template exists.

- [ ] **Step 3: Implement least-privilege IaC and workflows**

CloudFormation creates one `t3.micro` with standard CPU credits, a 30 GB gp3
root disk, an Elastic IP, a security group limited to 80/443, an EC2 instance
profile with SSM and Parameter Store read access, GitHub OIDC provider and
deploy role restricted to `repo:<owner>/<repo>:ref:refs/heads/main`, and three
budget email thresholds. CI uses Python 3.13 and Node 20, builds the amd64
image to GHCR, and deploys only after tests pass. The manual power workflow
uses the same OIDC role; no AWS static secret is accepted.

- [ ] **Step 4: Validate workflow and template syntax**

Run: `python - <<'PY'
import yaml
for path in ["infra/aws/finora.yaml", ".github/workflows/ci.yml", ".github/workflows/deploy-backend.yml", ".github/workflows/demo-power.yml"]:
    with open(path) as f: yaml.safe_load(f)
print("valid yaml")
PY`

Expected: `valid yaml`.

- [ ] **Step 5: Commit**

```bash
git add infra/aws .github backend/tests/test_production_artifacts.py
git commit -m "feat: add AWS portfolio infrastructure and CI"
```

### Task 7: Documentation, secret audit, and full verification

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`
- Modify: `.env.example`
- Create: `docs/deployment/aws-portfolio.md`

**Interfaces:**
- README links to the AWS provisioning and Vercel setup guide.
- The guide lists exact SSM parameter names, Vercel variables, GitHub setup,
  manual demo controls, smoke tests, and January 2027 cleanup steps.

- [ ] **Step 1: Add deployment documentation and safe environment examples**

Document `/finora/production/DJANGO_SECRET_KEY`,
`/finora/production/GEMINI_API_KEY`,
`/finora/production/POSTGRES_PASSWORD`, and
`/finora/production/DEMO_USER_PASSWORD` as names only. Include the Vercel
`BACKEND_ORIGIN` and public demo variables without adding values to tracked
files.

- [ ] **Step 2: Scan tracked files and history before publication**

Run: `git grep -nE 'AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}' $(git rev-list --all)`

Expected: no output. If output exists, stop and rotate the exposed secret before
creating a public remote.

- [ ] **Step 3: Run full verification**

Run: `cd backend && python -m pytest -q && python manage.py check`

Run: `cd frontend && npm run lint && npm run build`

Run: `docker compose -f docker-compose.production.yml --env-file deploy/ec2/compose.env.example config`

Expected: all commands pass.

- [ ] **Step 4: Commit**

```bash
git add README.md HANDOFF.md .env.example docs/deployment
git commit -m "docs: add portfolio deployment guide"
```
