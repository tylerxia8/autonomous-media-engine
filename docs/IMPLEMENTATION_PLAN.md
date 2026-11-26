# Implementation and critical path

Shortest credible path is one authorized, fixed-fee direct paid pilot using existing accounts if a verified payer accepts prompt terms. Use a qualifying, funded marketplace campaign if it clears sooner. Neither route has account-level evidence yet. No new production infrastructure is needed for the first local pilot.

| Day | Work and exit criterion |
|---|---|
| 1 | Integrations clears one opportunity and action matrix (AAME-002). Review authoritative PRD if supplied (AAME-001). Backend and QA settle job, rights and adapter interfaces. Exit live-path discovery if no eligible payer or source is evidenced. |
| 2 | Finance and Infrastructure implement atomic reservations and dry-run, and QA implements evidence gating. Backend implements state machine and audit (AAME-003–007). |
| 3 | Video processes a licensed fixture locally through timestamped transcript and ranking (AAME-008–009). |
| 4 | Video produces one conformant render and independent QA tests context/rights (AAME-010–011). |
| 5 | Integrations verifies cleared publishing and submission adapters or approved receipt-based manual handoffs (AAME-012–013). |
| 6 | Run fixture end to end including crash/replay, cash statement and shutdown checks (AAME-014, 015, 026, 027). |
| 7 | With production authorization and all evidence, process one eligible clip through delivery/submission. Track payout through actual clearance and reconcile. A day-seven payout is conditional on payer timeline. |

AAME-002 is the recommended first implementation task. Build a structured opportunity/evidence record with action-specific permission expiry and a qualification command. Validate against one existing authorized route and an offline incomplete-evidence fixture. Work on core offline interfaces in parallel using separate branches as described in [AGENTS](../AGENTS.md). Keep fallback manual steps explicit and measure owner time. After the first-cash workflow is stable, implement P1 signal snapshots, experiments, optimization and bounded live ingest. P2 is gated on mature evidence and does not block monetization.
