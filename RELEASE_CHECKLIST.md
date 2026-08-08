# MEMESCOPE Release Checklist

Use this template for every sprint or release. Complete it with evidence, dates, commands, and measured results. Do not mark a release complete from intention alone.

## Release identity

- [ ] Sprint / release name:
- [ ] Date and UTC release window:
- [ ] Commit hash:
- [ ] Branch:
- [ ] Release owner:
- [ ] Scope summary:
- [ ] Linked decision records:

## Repository and migration safety

- [ ] Working tree reviewed; unrelated changes excluded.
- [ ] Application-code, test, API, and migration changes enumerated.
- [ ] Alembic migration identifier(s):
- [ ] Migration reviewed as forward-only and reversible operationally through backup/roll-forward plan.
- [ ] Database backup/restore procedure verified for the target environment.
- [ ] Migration upgrade check passed:
- [ ] Migration/schema-drift check passed:
- [ ] Rollback commit identified:
- [ ] Rollback procedure and owner:

## Backend validation

- [ ] Backend unit tests: command / result
- [ ] Backend integration tests: command / result
- [ ] Backend contract/purity tests: command / result
- [ ] Ruff lint: command / result
- [ ] Ruff format check: command / result
- [ ] Mypy: command / result
- [ ] Backend production image/build: command / result
- [ ] Feature-flag defaults and environment templates reviewed.
- [ ] API behavior and error/absence semantics verified.

## Frontend validation

- [ ] Frontend tests: command / result
- [ ] TypeScript typecheck: command / result
- [ ] ESLint: command / result
- [ ] Frontend production build: command / result
- [ ] Protected/public route behavior verified.
- [ ] Reduced-motion and historical/live-state presentation reviewed where applicable.
- [ ] No client-side duplication of server-derived values introduced.

## Data sources and operations

- [ ] Provider availability/rate-limit status:
- [ ] Data-source incidents since the previous release:
- [ ] Dead-letter/requeue state:
- [ ] Scanner, enrichment, scoring, Radar, opportunity, paper, and priority worker status:
- [ ] Feature flags enabled in target environment:
- [ ] Secrets/configuration reviewed without logging sensitive values.
- [ ] Monitoring, logs, Sentry, backups, TLS, and host/domain status:

## Performance and behavior evidence

| Metric | Before | After | Dataset/environment | Method | Result / interpretation |
|---|---:|---:|---|---|---|
| API/read latency | | | | | |
| Worker throughput/lag | | | | | |
| Error/retry/dead-letter rate | | | | | |
| Frontend load/render | | | | | |
| Database query/migration duration | | | | | |
| Other release-specific metric | | | | | |

- [ ] Before/after measurements use comparable environments and datasets.
- [ ] No unmeasured claim is presented as a production metric.
- [ ] Historical metrics are labeled with their collection date and commit.

## Release decision

- [ ] Known issues:
- [ ] Launch blockers:
- [ ] Accepted risks and owner:
- [ ] Deployment status: not started / staging / production / rolled back
- [ ] Deployment timestamp (UTC):
- [ ] Post-deploy validation command/results:
- [ ] Documentation updated: AI_CONTEXT.md, PROJECT_STATE.md, SPRINT_HISTORY.md, DECISIONS.md
- [ ] Next sprint:

## Sign-off

- [ ] Engineering:
- [ ] Product:
- [ ] Operations:
- [ ] Final release decision and rationale:
