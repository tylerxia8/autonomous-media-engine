# Agent collaboration

Use one branch and isolated worktree per backlog assignment. Name branches workstream/requirement-short-name. The coordinator owns sequencing and interface changes. Each PR states requirement and acceptance IDs, migrations, fixtures, test results, dependencies and rollback. A reviewer independent of the author checks every PR. Require independent QA/Security review for publishing, rights, secrets and budget changes. Configure branch checks and protections when supported. Keep merge manual.

| Workstream | Interface ownership | Independent reviewer |
|---|---|---|
| Backend | Workflow, job and adapter contracts | Infrastructure |
| Video | Media ingest, extraction, recipes and render | QA/Security |
| Research | Evidence registry, trend and benchmark inputs | Quant |
| Quant | Ranking, models and experiments | Research |
| Integrations | Campaign, publishing and analytics providers | QA/Security |
| Finance | Ledger, reservations, cash optimization | QA/Security |
| QA/Security | Policy decisions, sandbox, adversarial fixtures | Backend |
| Infrastructure | Environments, deployment controls and alerts | QA/Security |

Keep CI fixture-only, with synthetic credentials and no provider network calls. Plan contract tests, deterministic replay, concurrency checks and integration fakes. Keep vendor data, credentials and real media out of Git. Resolve interface conflicts through coordinator-reviewed contract PRs. External side effects require applicable authorization and an enabled production capability.
