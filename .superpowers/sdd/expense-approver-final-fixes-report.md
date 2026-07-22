# Expense Approver Final Fixes Report

Date: 2026-07-22

## Scope

This patch addresses only the final Expense Approver review findings. `AGENTS.md`
was preserved as an unrelated, untracked user file.

## Changes

### Idempotent Celery delivery

- `ExpenseApproverService.run()` now atomically claims a workflow with a conditional
  `pending -> running` update before invoking the provider.
- A delivery for `running`, `needs_review`, `approved`, or `rejected` refetches and
  returns the tenant-scoped row without calling the LLM or mutating it. In particular,
  a late delivery cannot reopen a terminal human decision.
- Provider exceptions now move a successfully claimed workflow to `needs_review` with
  preserved deterministic metadata and the fixed error message:
  `Could not assess this expense because the provider request failed.`

### Human decision locking

- Expense Approver approve/reject operations now enter one transaction, lock and
  refetch the tenant-scoped workflow, then lock/refetch its linked tenant-scoped
  expense.
- The locked workflow must still be `needs_review`; the decision, expense status,
  and audit event are committed together. A stale second reviewer therefore receives
  the existing `needs_review` validation error and cannot reverse the first decision.
- Receipt Processor and Invoice Chaser decision paths remain unchanged.

### Prompt and auth-session isolation

- The Expense Approver prompt now contains the computed deterministic ceiling flag,
  not merely the pre-run policy metadata.
- The application-level provider subscribes to auth-session changes and immediately
  clears the React Query client plus the active workflow selection. This prevents a
  logout/login from showing cached data or a selected workflow from the prior tenant.
- The auth subscription cleanup now returns `void`, satisfying React's effect cleanup
  contract and allowing the production TypeScript build to verify the session boundary.

## Test-first evidence

New backend regression tests were added before production edits and initially failed
for the intended missing behavior:

- deterministic ceiling flag absent from the prompt;
- redeliveries changed `running`/terminal workflows and invoked the fake LLM;
- a provider `RuntimeError` escaped and left the workflow running;
- a stale second approve/reject overwrote the first decision;
- no workflow/expense locks were requested.

After implementation, the focused suite passed:

```text
python -m pytest -q tests/test_expense_approver_service.py tests/test_expense_approval_workflow_service.py
28 passed, 1 warning
```

The new coverage includes all non-pending redelivery states (explicitly approved and
rejected), deterministic provider failure handling, stale contradictory decisions,
and a SQLite-compatible lock/refetch regression test.

## Final verification

```text
cd backend && python -m pytest -q
205 passed, 77 warnings

cd backend && python manage.py makemigrations --check --dry-run
No changes detected

cd backend && python manage.py check
System check identified no issues (0 silenced).

cd frontend && npm run lint
exit 0

cd frontend && npm run build
exit 0; TypeScript and static route generation completed
```

`makemigrations --check --dry-run` emitted the pre-existing warning that the locally
configured PostgreSQL `finora` credentials were rejected while checking migration
history; Django still completed the check successfully and found no migration changes.
The backend suite also retains its existing JWT key-length and provider deprecation
warnings. The frontend package has no configured unit-test script; lint and the full
production build verified the session-cache change.
