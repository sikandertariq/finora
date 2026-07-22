# Observable Backend Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent unrelated pushes from redeploying the backend and make every SSM deployment bounded and diagnosable.

**Architecture:** Keep deployment behavior in the existing remote scripts while tightening the GitHub Actions orchestration around them. The workflow filters production inputs, serializes runs, gives SSM an explicit execution deadline, and exposes command lifecycle details.

**Tech Stack:** GitHub Actions YAML, AWS Systems Manager Run Command, Bash, pytest.

## Global Constraints

- Automatic deployment remains restricted to pushes on `main`.
- Manual `workflow_dispatch` deployment remains available.
- Secrets stay in AWS Systems Manager Parameter Store and must never be printed.
- The EC2 host remains the single backend, worker, PostgreSQL, Redis, and Nginx host.
- `AGENTS.md` remains local-only and must not be staged.

---

### Task 1: Lock the backend deployment contract with a failing test

**Files:**
- Modify: `backend/tests/test_deployment_artifacts.py`
- Test: `backend/tests/test_deployment_artifacts.py`

**Interfaces:**
- Consumes: `.github/workflows/deploy-backend.yml` as repository text.
- Produces: regression assertions for trigger scope, concurrency, deadlines, and diagnostics.

- [ ] **Step 1: Write the failing tests**

```python
def test_backend_deploy_only_runs_for_production_inputs():
    workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()

    for path in (
        ".github/workflows/deploy-backend.yml",
        "backend/**",
        "deploy/**",
        "docker-compose.production.yml",
        "infra/aws/**",
    ):
        assert f"- {path}" in workflow

    assert "frontend/**" not in workflow


def test_backend_deploy_is_serialized_bounded_and_observable():
    workflow = (ROOT / ".github/workflows/deploy-backend.yml").read_text()

    assert "group: finora-production-backend" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "--timeout-seconds 60" in workflow
    assert 'executionTimeout: ["600"]' in workflow
    assert 'echo "SSM command ID: $COMMAND_ID"' in workflow
    assert "StatusDetails:StatusDetails" in workflow
    assert "aws ssm cancel-command" in workflow
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend && uv run pytest tests/test_deployment_artifacts.py -q`

Expected: the two new tests fail because the workflow lacks path filters,
concurrency, explicit SSM deadlines, command-ID output, and cancellation.

- [ ] **Step 3: Commit only after Task 2 is green**

The test and implementation belong in the same focused fix commit after Task 2.

---

### Task 2: Bound and expose the SSM deployment lifecycle

**Files:**
- Modify: `.github/workflows/deploy-backend.yml`
- Test: `backend/tests/test_deployment_artifacts.py`

**Interfaces:**
- Consumes: GitHub repository variables, GitHub's OIDC credentials, and `deploy/production/deploy-remote.sh IMAGE_REF BACKEND_PUBLIC_IP`.
- Produces: one serialized SSM invocation with a 60-second delivery deadline and 600-second execution deadline.

- [ ] **Step 1: Scope and serialize workflow runs**

Add production path filters and workflow-level concurrency:

```yaml
on:
  push:
    branches: [main]
    paths:
      - .github/workflows/deploy-backend.yml
      - backend/**
      - deploy/**
      - docker-compose.production.yml
      - infra/aws/**
  workflow_dispatch:

concurrency:
  group: finora-production-backend
  cancel-in-progress: false
```

- [ ] **Step 2: Add job and SSM deadlines**

Set `timeout-minutes: 15` on `build-and-deploy`. Build the SSM parameters with
`jq` so the remote command and `executionTimeout` are encoded safely:

```bash
REMOTE_COMMAND=$(printf '%s\n' \
  'set -eu' \
  'export HOME=/root' \
  "if [ ! -d /srv/finora/.git ]; then git clone https://github.com/${{ github.repository }}.git /srv/finora; fi" \
  'git config --global --add safe.directory /srv/finora' \
  'cd /srv/finora' \
  'git fetch origin main' \
  'git switch main' \
  'git pull --ff-only origin main' \
  "./deploy/production/deploy-remote.sh '$IMAGE_REF' '${{ vars.BACKEND_PUBLIC_IP }}'")
PARAMETERS=$(jq -nc --arg command "$REMOTE_COMMAND" \
  '{commands: [$command], executionTimeout: ["600"]}')
COMMAND_ID=$(aws ssm send-command \
  --document-name AWS-RunShellScript \
  --instance-ids "${{ vars.AWS_INSTANCE_ID }}" \
  --timeout-seconds 60 \
  --parameters "$PARAMETERS" \
  --query 'Command.CommandId' --output text)
```

- [ ] **Step 3: Report and terminate command lifecycle cleanly**

Print the command ID, include `StatusDetails` and `ResponseCode` in final output,
report status transitions, poll for 144 five-second intervals, and call
`aws ssm cancel-command` before failing the final workflow deadline.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `cd backend && uv run pytest tests/test_deployment_artifacts.py -q`

Expected: all deployment artifact tests pass.

- [ ] **Step 5: Run repository-level static verification**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/deploy-backend.yml"); puts "workflow yaml ok"'
bash -n deploy/production/bootstrap-host.sh deploy/production/deploy-remote.sh
git diff --check
```

Expected: each command exits zero and prints no syntax or whitespace errors.

- [ ] **Step 6: Commit the workflow fix**

```bash
git add .github/workflows/deploy-backend.yml backend/tests/test_deployment_artifacts.py docs/superpowers/specs/2026-07-22-observable-backend-deployment-design.md docs/superpowers/plans/2026-07-22-observable-backend-deployment.md DEPLOYMENT_HANDOFF.md
git commit -m "fix: bound backend deployments"
```

---

### Task 3: Publish and verify production

**Files:**
- Modify: `DEPLOYMENT_HANDOFF.md`

**Interfaces:**
- Consumes: the pushed `main` branch and its GitHub Actions run.
- Produces: a green deployment run plus current operator handoff evidence.

- [ ] **Step 1: Update the handoff before publishing**

Record the diagnosed trigger problem, the workflow safeguards, and the local
verification commands in `DEPLOYMENT_HANDOFF.md`. Do not claim the live run is
green until GitHub reports success.

- [ ] **Step 2: Push `main`**

Run: `git push origin main`

Expected: `origin/main` advances to the fix commit and starts `Deploy backend`
because the workflow file itself is included in the path filters.

- [ ] **Step 3: Monitor the exact deployment run**

Run: `gh run watch <run-id> --repo sikandertariq/finora --exit-status`

Expected: image build, SSM deployment, and public HTTPS verification all finish
successfully.

- [ ] **Step 4: Verify all public endpoints**

Run:

```bash
curl -fsS --max-time 20 https://52.73.119.50/api/health/
curl -fsS --max-time 20 https://finora-tbll.vercel.app/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' --max-time 20 https://finora-tbll.vercel.app/
```

Expected: both health requests return `{"status": "ok"}` and the frontend
returns `200`.

- [ ] **Step 5: Report residual risk accurately**

If the run fails, use the printed command ID and terminal SSM details to diagnose
the bounded failure. If it passes, report the run URL, commit, branch, test
counts, and endpoint results.
