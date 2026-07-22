# Observable Backend Deployment Design

## Problem

The backend deployment workflow runs for every push to `main`. Two frontend-only
proxy commits therefore built backend images and redeployed the EC2 host even
though no backend or production-deployment artifact changed. The last redundant
run timed out after polling an SSM Run Command invocation for six minutes. The
invocation still reported `InProgress`, exposed no output, and the workflow had
not printed its command ID. Production remained healthy.

The workflow also gives the remote command the `AWS-RunShellScript` default
execution timeout of one hour. Several remote operations can wait indefinitely,
so the GitHub polling deadline can expire long before SSM reaches a terminal
state.

## Design

### Trigger scope

Automatic backend deployments run only when a push to `main` changes one of
these production inputs:

- `.github/workflows/deploy-backend.yml`
- `backend/**`
- `deploy/**`
- `docker-compose.production.yml`
- `infra/aws/**`

`workflow_dispatch` remains available for deliberate redeployments. Frontend,
documentation, and other unrelated commits no longer publish backend images or
touch EC2.

### Deployment serialization

All production backend runs share one GitHub Actions concurrency group with
`cancel-in-progress: false`. A running deployment is allowed to finish before a
new one starts. This avoids concurrent database backups, image pulls, and
container recreation on the single `t3.micro` host.

### Bounded SSM lifecycle

The workflow sends one POSIX shell command through `AWS-RunShellScript` with:

- a 60-second SSM delivery timeout;
- a 600-second `executionTimeout` document parameter;
- a 15-minute GitHub job timeout;
- a polling window long enough to observe SSM's combined delivery and execution
  deadline.

The remote command enables fail-fast shell behavior before fetching `main` and
calling the existing `deploy-remote.sh` entry point. Business and deployment
logic stays in the versioned shell scripts rather than moving into workflow
YAML.

### Observability and failure handling

The workflow prints the non-secret SSM command ID immediately and reports each
status transition. Terminal output includes status details, response code,
stdout, and stderr. If SSM has not reached a terminal state by the workflow's
own final polling deadline, the workflow requests cancellation, prints the last
known invocation state, and fails.

### Tests

Repository artifact tests read the workflow as text and enforce the stable
contract:

- unrelated frontend-only pushes are excluded by explicit backend path filters;
- production deployments are serialized without cancelling the active run;
- SSM delivery and execution deadlines are both configured;
- the command ID and status details are emitted for future diagnosis.

The workflow is additionally checked with a YAML parser and `git diff --check`.
The resulting GitHub Actions run is the end-to-end test: it must complete, and
both the direct backend and Vercel proxy health endpoints must return HTTP 200.

## Non-goals

- No migration to CodeDeploy, SSM Automation, or another deployment platform.
- No changes to application behavior or production secrets.
- No automatic EC2 start/stop behavior.
