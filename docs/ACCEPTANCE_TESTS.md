# Acceptance test plan

These are specified cases for implementation. Fixtures must run offline and exercise the normal orchestration entry point. Live checks require documented permission and a separately enabled environment.

| Case | Requirement | Test evidence |
|---|---|---|
| AT-001 | AAME-001 | Reviewer checks clause-to-ID reconciliation against supplied V2.0 and signs off differences. |
| AT-002 | AAME-002 | Record an active campaign or signed direct pilot and independently confirm account, asset, deadline, terms and payment. Blank each mandatory field and assert deny. |
| AT-003 | AAME-003 | Table-test missing, expired, revoked and mismatched grants at ingestion and side-effect boundary. |
| AT-004 | AAME-004 | Parallel requests at each cap admit only permitted amounts. Crash/restart preserves reservations, stale unknown holds freeze exposure and unsigned unlock fails. |
| AT-005 | AAME-005 | Replay approval, partial payout split, duplicate import, fee and reversal fixtures. Prove balance and cleared cash against statement. |
| AT-006 | AAME-006 | CI spy sees zero external mutations or paid calls in dry-run and after kill switch. Dev credentials fail production access. |
| AT-007 | AAME-007 | Inject crash between remote success and local receipt, then reconcile exactly once or escalate. |
| AT-008 | AAME-008 | Test licensed fixture, bad MIME, corrupt container, oversized file and traversal. Verify hash and monotonic source timestamps. |
| AT-009 | AAME-009 | Repeat ranking with fixed artifacts and config and compare results. Count extraction and render invocations for top-K limits. |
| AT-010 | AAME-010 | Probe output for profile constraints, subtitle bounds and timestamps. Compare golden render with pinned build and recipe. |
| AT-011 | AAME-011 | Exercise misleading context, duplicate, invalid captions, audio faults and post-QA artifact alteration. Verify each blocks. |
| AT-012 | AAME-012 | Mock permission, expiry, duplicate retry, private visibility and manual receipt. Live verification checks actual permitted visibility. |
| AT-013 | AAME-013 | Exercise pre-post review, rejection, manual receipt, approval, under-threshold, payout and reversal. |
| AT-014 | AAME-014 | Run fixture to fake bank reconciliation with no network. Live evidence links an authorized job to a unique cleared receipt. |
| AT-015 | AAME-015 | Golden weekly report matches ledger/control totals, outstanding receipts and owner time. |
| AT-016 | AAME-016 | Audit twelve dispositions and independently verify unresolved rights remain blocked. |
| AT-017 | AAME-017 | Inject stale, sparse and unauthorized trend data. Verify neutral fallback and as-of snapshots. |
| AT-018 | AAME-018 | Replay seeded spike against matched cohorts. Missing or below-floor cohorts yield unavailable. |
| AT-019 | AAME-019 | Benchmark local measurements against the job reservation and latency budget. Check missing-modality fallback. |
| AT-020 | AAME-020 | Compare approved hook treatments for retention and context preservation. Unsupported retention yields null. |
| AT-021 | AAME-021 | Replay assignments across retry and dropout. Verify treatment propensities, denominator and cost. |
| AT-022 | AAME-022 | Rank test campaigns with identical views and different fees and settlement odds. Pause on negative value or stale inputs. |
| AT-023 | AAME-023 | Replay ≥20 stream events including disconnect and revocation. Verify 120-second p95, fixed ring buffer and blocked publish. |
| AT-024 | AAME-024 | Run temporal and unseen creator splits with leakage, calibration, rare-event lift and mature cash checks. Fail closed on weak evidence. |
| AT-025 | AAME-025 | Reproduce holdout economics, stop unsafe exploration and restore control within one scheduler poll. |
| AT-026 | AAME-026 | Inspect PR scope, separate branch, passed CI and reviewer identity before owner merge. |
| AT-027 | AAME-027 | Exercise egress deny, secrets redaction, hostile media and heartbeat loss. Run containment and restore drill. |
