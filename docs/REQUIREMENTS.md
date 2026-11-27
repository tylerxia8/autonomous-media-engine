# Engineering backlog

IDs are stable. P0 ships the minimum viable revenue path, P1 improves it, P2 requires evidence. Dependencies name prerequisites for acceptance. Proposal-level acceptance criteria map one-to-one to AT cases.

| ID | Priority | Workstream | Depends on | Acceptance criterion |
|---|---|---|---|---|
| AAME-001 | P0 | Backend | — | Reconcile standalone V2.0 clauses to IDs and record resolved discrepancies before baseline approval. |
| AAME-002 | P0 | Integrations | — | Record dated evidence for ≥1 payable opportunity covering discovery, current eligibility, campaign status, rights, payment and per-action automation permission. Block every unknown production action. |
| AAME-003 | P0 | QA/Security | — | Deny expired, revoked, missing and destination-mismatched grants at acquisition and every external action. Require positive evidence for editing and monetization. |
| AAME-004 | P0 | Finance | — | Atomically reserve worst-case exposure and enforce $50 initial risk, $30 week-one and $300 monthly ceiling plus approved lower limits under concurrency. |
| AAME-005 | P0 | Finance | AAME-004 | Reconcile estimates, approved amounts, cleared receipts, fees and expenses separately. Duplicate settlement imports create zero extra postings. |
| AAME-006 | P0 | Infrastructure | — | Dev and prod have separate stores, identities and secrets. Default dry-run blocks every external mutation and paid call. Shutdown blocks queued and new side effects. |
| AAME-007 | P0 | Backend | AAME-003, AAME-004, AAME-006 | Workflow transitions are auditable and retry-safe. A timeout after an external side effect enters reconciliation and never blindly retries. |
| AAME-008 | P0 | Video | AAME-003, AAME-007 | Acquire only allowlisted authorized files, hash provenance, reject malformed and oversized media and provide timestamped local transcription. |
| AAME-009 | P0 | Video | AAME-008 | Deterministically return ranked valid spans, reason codes and score versions. Run expensive extraction and rendering only within top-K and cost gates. |
| AAME-010 | P0 | Video | AAME-009 | Render one destination-conformant vertical clip with synced captions and a reproducible versioned recipe. |
| AAME-011 | P0 | QA/Security | AAME-003, AAME-010 | Separate QA approves artifact by hash and blocks unsafe, misleading, near-duplicate, nonconformant or ambiguous clips. |
| AAME-012 | P0 | Integrations | AAME-002, AAME-006, AAME-011 | Publish once via cleared path and save receipt. With no automation grant, produce a manual handoff only when permitted. |
| AAME-013 | P0 | Integrations | AAME-002, AAME-012 | Verify review order and eligibility, submit once via cleared path, track approval, rejection, threshold, settlement and reversal. Support pre-post review when required. |
| AAME-014 | P0 | Backend | AAME-005, AAME-013 | A fixture traverses all stages to reconciled cash. A live pilot aims for pipeline readiness by day seven and records actual first cash separately. |
| AAME-015 | P0 | Finance | AAME-005, AAME-007 | Weekly report shows four financial measures, net cash, profit/day vs $10, owner minutes vs <15/week, payout aging and exceptions. |
| AAME-016 | P1 | Research | — | Record an evidence and adoption decision for all 12 resources with license scope, limitations and costs. |
| AAME-017 | P1 | Research | AAME-002, AAME-016 | Snapshot authorized trend data with times, geography and provenance. Missing or stale signals use baseline. |
| AAME-018 | P1 | Research | AAME-016 | Detect age-adjusted peer outliers from allowed metadata with robust cohort baselines and suppress alerts below sample floor. |
| AAME-019 | P1 | Video | AAME-009, AAME-016 | Extract versioned transcript, audio and sparse visual signals and rank candidates within per-job latency and cost budgets. |
| AAME-020 | P1 | Quant | AAME-011, AAME-019, AAME-021 | Test truthful hook and pacing variants using authorized retention data. Store nulls and unavailable cohorts explicitly. |
| AAME-021 | P1 | Quant | AAME-005, AAME-012 | Log all eligible assignments including rejected and low-view clips. Reproduce assignment, identify attrition, and compute intent-to-treat lift and cost. |
| AAME-022 | P1 | Finance | AAME-015, AAME-021 | Rank eligible jobs by risk-adjusted expected net cash and stop stale or negative-value work. Compare forecasts with realized profit. |
| AAME-023 | P1 | Video | AAME-003, AAME-006, AAME-011 | Produce a reviewable highlight from an authorized simulated stream within a proposed 120 seconds at p95. Stop capture on revocation and bound buffer size. |
| AAME-024 | P2 | Quant | AAME-017–AAME-021 | Produce calibrated fixed-window probabilities for 1M and ≥2M views, passing chronological and creator-holdout gates and positive incremental net cash. |
| AAME-025 | P2 | Quant | AAME-022, AAME-024 | Promote advanced multimodal scoring or contextual bandits independently only after measured incremental financial return. Log propensities and keep a control and rollback. |
| AAME-026 | P0 | Infrastructure | AAME-006 | Require separate branches, contract and fixture tests, independent review and documented rollback for each workstream PR. |
| AAME-027 | P0 | QA/Security | AAME-006, AAME-007 | Verify secret isolation, restricted media sandbox, hostile input handling, alerting and incident recovery before live capability enablement. |
