# Data model

| Entity | Identity and integrity |
|---|---|
| CampaignVersion and Capability | Campaign ID plus version. Evidence, observed_at, expiry, region, funds, payout formula, terms hash. Capabilities keyed by provider/account/action and revoke independently. |
| RightsGrant | Versioned identity, owner, asset scope, allowed editing, AI processing, platforms, territories, duration, monetize, revoke time, evidence. |
| Asset, Transcript, Candidate | Hash plus provenance. Parent IDs, source timestamps, language, terms, features, feature version and as-of cutoff. |
| Render, QADecision | Artifact hash and recipe. Decision binds artifact, destination, campaign, grant and policy version. |
| Job, Attempt, Outbox, Receipt | Unique scoped operation key, payload digest, lease fence, attempt count, remote ID, state, error and immutable transition audit. |
| MetricSnapshot | Provider/account/post/metric/window/as-of. Distinguish missing, censored and observed zero. Record definition and visibility. |
| ExperimentAssignment, ModelVersion | Experiment unit and assignment probability, treatment, eligibility, training cutoff, calibration, evaluation and promotion state. |
| Estimate, Approval, CashEvent, Expense | Immutable separate event streams. External reference, evidence, amount, currency, timestamps, reversal link and campaign allocation. |
| Reservation, BudgetPolicy | Reserved amount, consumed amount, period exposure, policy revision, signed owner approval, release and reason. |

Record source and observed timestamps for replay. Keep raw receipts access-controlled and redact bank identifiers from operator reports. Schema migrations are transactional and compatibility-tested. A ledger reversal references the original rather than modifying it. Assignments and outcomes include failures, cancellations and holds with reasons. Prevent cross-environment identifiers and credentials from being accepted.
