# Finora Deployment Handoff

> Continue here for deployment work. Last verified: **2026-07-22, 15:30 PKT**.
> Read `AGENTS.md` first for architecture/engineering rules, then this file.

## Current goal

Finish and verify the public, zero/low-cost portfolio deployment:

- Next.js frontend on Vercel.
- Django, Celery worker/beat, PostgreSQL, Redis, Nginx, and Certbot on one
  manually controlled AWS EC2 `t3.micro`.
- GitHub Actions deploys the backend through AWS OIDC + Systems Manager (no
  long-lived AWS access keys and no SSH).
- The browser uses Vercel's same-origin `/api` proxy to reach Django.
- Keep secrets only in AWS Systems Manager Parameter Store. Never print or
  commit their values.

The user explicitly wants a free-tier portfolio setup and plans to stop EC2
when the demo is not being used.

## Public resources and identifiers

| Resource | Value |
|---|---|
| GitHub repository | `https://github.com/sikandertariq/finora` |
| Default deployment branch | `main` |
| Vercel project/domain | `https://finora-tbll.vercel.app` |
| AWS region | `us-east-1` |
| CloudFormation stack | `Finora` |
| EC2 instance | `i-06276f9ce11ec07b8` (`finora-portfolio-demo`) |
| Elastic/public backend IP | `52.73.119.50` |
| Direct backend health | `https://52.73.119.50/api/health/` |
| Vercel proxy health | `https://finora-tbll.vercel.app/api/health` |

Do not put the AWS role ARN, AWS account number, Parameter Store values,
Gemini key, Django secret, database password, or demo password in this file.
They already exist in the relevant private cloud settings.

## Exact current state

At the time this file was written:

- Vercel production deployment for commit `128cae5` completed successfully for
  both Vercel projects reported on the GitHub commit.
- `https://finora-tbll.vercel.app/` returns HTTP `200`.
- The Vercel proxy routing fix is deployed.
- Backend deployment run `29911168068` completed successfully, including its
  Systems Manager step and public HTTPS health check:
  `https://github.com/sikandertariq/finora/actions/runs/29911168068`.
- A later, redundant backend run was automatically triggered by the final
  frontend-only commit: run `29911508445`:
  `https://github.com/sikandertariq/finora/actions/runs/29911508445`.
- Run `29911508445` ended as `failure` because the GitHub job's six-minute SSM
  polling window expired while the invocation still reported `InProgress` with
  empty stdout/stderr. This was a workflow timeout, not a demonstrated
  application failure. The public-health verification step was skipped.
- Fresh checks after the workflow ended returned HTTP `200` for all three
  public paths. Both health endpoints returned `{"status": "ok"}`:
  `https://52.73.119.50/api/health/`,
  `https://finora-tbll.vercel.app/api/health`, and the Vercel frontend root.

## First actions for the next agent

The deployment is currently serving successfully. Run these from
`/Users/sikandert/Projects/finora` to reconfirm before changing anything:

```bash
curl -fsS --max-time 20 https://52.73.119.50/api/health/
curl -fsS --max-time 20 https://finora-tbll.vercel.app/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' --max-time 20 \
  https://finora-tbll.vercel.app/
```

Expected output:

```text
{"status": "ok"}
{"status": "ok"}
200
```

Then perform a browser smoke test: load the Vercel site, use the public demo
login already configured in Vercel, confirm invoices/workflows load, and test
one harmless receipt upload/review cycle.

Before dispatching another backend deploy, inspect whether the SSM command from
run `29911508445` has reached a terminal state in AWS Systems Manager Run
Command. The GitHub log captured only this final result:

```json
{
  "Status": "InProgress",
  "StandardOutputContent": "",
  "StandardErrorContent": ""
}
```

The corresponding failed-step log is available with:

```bash
gh run view 29911508445 --repo sikandertariq/finora \
  --job 88895290521 --log-failed
```

Do not redeploy merely to clear the red GitHub badge: the application is
currently healthy. Diagnose why the remote command remained `InProgress` after
the services recovered, then either increase/fix the workflow's polling logic
or remove the command-side hang before the next real backend change.

## Deployment failures already diagnosed and fixed

These are historical. Do not reintroduce old fixes or repeat their diagnosis
unless the same error text returns.

1. **GitHub OIDC could not assume the AWS role.**
   The actual GitHub `sub` claim included repository-owner and repository IDs.
   `infra/aws/finora.yaml` now accepts both the standard subject and the exact
   ID-bound subject, still restricted to `main`. CloudFormation was updated and
   the role change completed without replacement. Commit: `8bfbf60`.

2. **Fresh EC2 host lacked Docker Compose/AWS CLI.**
   `deploy/production/bootstrap-host.sh` installs Docker from Docker's official
   Ubuntu repository and AWS CLI v2 from AWS's official zip installer. Commits:
   `cba94dd`, `5074201`, `5f1ad7b`.

3. **Workflow deployed the full SHA while Docker metadata published a short
   SHA tag.**
   `IMAGE_REF` now uses `steps.image-meta.outputs.version`. Commit: `d794bfe`.

4. **EC2 failed its guest status check after a reboot.**
   A reboot did not immediately recover it; a full stop/start restored the
   instance. The Elastic IP and EBS data remained attached.

5. **PostgreSQL data ownership was corrupted by bootstrap.**
   The old bootstrap recursively ran `chown -R ubuntu:ubuntu /srv/finora`, which
   changed bind-mounted Postgres/Redis files. Bootstrap now avoids recursive
   ownership changes and restores those data directories to UID/GID `999`.
   The deploy script also repairs existing data before backup/start. Commit:
   `79cd0f4`.

6. **Git rejected `/srv/finora` as dubious ownership under SSM.**
   The SSM command now sets `HOME=/root` and adds `/srv/finora` as a global safe
   directory before fetching. Commit: `9ad87e2`.

7. **AWS CLI's built-in SSM waiter timed out at 100 seconds.**
   The workflow now polls SSM status for up to six minutes and always prints
   remote stdout/stderr. Commit: `eec2658`.

8. **Vercel and Django caused an infinite trailing-slash redirect.**
   Next.js/Vercel canonicalized `/api/health/` to `/api/health`, while Django
   redirected it back. `frontend/next.config.ts` preserves slash behavior and
   rewrites Vercel's slashless API route to Django with a trailing slash.
   Commits: `1cc3f60`, `128cae5`.

## Important files

| File | Purpose |
|---|---|
| `.github/workflows/deploy-backend.yml` | Build/publish image, AWS OIDC, SSM deployment, HTTPS verification |
| `.github/workflows/demo-power.yml` | Manually start/stop the demo host |
| `infra/aws/finora.yaml` | CloudFormation infrastructure, instance role, OIDC role, networking, budget |
| `deploy/production/bootstrap-host.sh` | Idempotent host dependency/data ownership setup |
| `deploy/production/deploy-remote.sh` | Fetch parameters, backup DB, pull/start containers, health wait |
| `deploy/production/configure-nginx.sh` | Nginx and IP-address certificate setup |
| `docker-compose.production.yml` | Single-host production services |
| `frontend/next.config.ts` | Server-side Vercel `/api` rewrite |
| `docs/deployment/aws-portfolio.md` | Operator/setup guide |

## Cloud configuration already completed

- CloudFormation stack is created in `us-east-1`.
- GitHub repository variables exist: `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`,
  `AWS_INSTANCE_ID`, and `BACKEND_PUBLIC_IP`.
- Required SSM SecureString parameters exist under `/finora/production/`:
  `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `GEMINI_API_KEY`, and
  `DEMO_USER_PASSWORD`.
- Vercel Root Directory is `frontend` and framework is Next.js.
- Vercel has `BACKEND_ORIGIN=https://52.73.119.50` for the relevant production
  deployment. Do not set `NEXT_PUBLIC_API_BASE_URL` in Vercel production.
- The backend GHCR image/package is publicly pullable by EC2.

## Verification already performed

- Backend test suite previously passed: 131 tests.
- Frontend `npm run lint` and `npm run build` passed after both proxy changes.
- Shell syntax passed for bootstrap/deploy scripts.
- Workflow YAML parsed successfully and `git diff --check` passed.
- Successful backend run `29911168068` proved GitHub OIDC, GHCR image build,
  SSM execution, Docker rollout, and the direct public HTTPS health check.
- Vercel commit status for `128cae5` reported successful deployments for
  `finora` and `finora-tbll`.
- Fresh post-run checks at 15:30 PKT returned `{"status": "ok"}` from both the
  direct backend and Vercel proxy; the Vercel frontend returned HTTP `200`.

## Git/worktree state

- Local branch name: `feat/tenant-foundation`.
- Deployments are pushed to remote `main` with `git push origin HEAD:main`.
- Latest pushed commit when this handoff was written: `128cae5`.
- `AGENTS.md` is an intentional untracked workspace instruction file. Do not
  stage, commit, delete, or overwrite it.
- Check `git status --short` before making changes and preserve unrelated user
  work.

## Recommended follow-up after deployment is green

1. Add path filters so frontend-only commits do not trigger the backend deploy
   workflow. Include backend/deployment/IaC files and the workflow itself; keep
   `workflow_dispatch` for manual restarts.
2. Run the browser smoke test described above.
3. Update this handoff and `HANDOFF.md` to record the final green URL/result.
4. Stop EC2 through `Demo power control` when the demo is not needed. Starting
   later should be: start workflow, wait for all EC2 checks, then run backend
   deploy to renew the short IP certificate and reset disposable demo data.
