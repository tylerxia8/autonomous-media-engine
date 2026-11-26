# Internal API contracts

Initial implementation exposes typed local commands. Names below are interface names. Provider methods are implementation-dependent and require proof.

| Command | Required fields | Result |
|---|---|---|
| qualify | campaign_ref, evidence_refs | versioned snapshot and action capabilities |
| enqueue | asset_ref, rights_id, campaign_version, destination, mode, idempotency_key | job_id, state |
| reserve | job_id, purpose, max_usd_cents, idempotency_key | reservation_id or budget_deny |
| acquire | job_id, grant_version, source_ref | asset_hash, timings, provenance |
| select | asset_hash, feature_version, as_of, selection_config | ordered candidates with start_ms, end_ms, score and reasons |
| render | candidate_id, recipe_version, reservation_id | artifact_hash and probe result |
| review | artifact_hash, campaign_version, evidence_refs, policy_version | decision_id, status, reasons, expiry |
| publish | decision_id, artifact_hash, destination, idempotency_key | remote_post_id, observed visibility or manual task |
| submit | job_id, post_receipt or draft_hash, campaign_version, idempotency_key | submission_ref and status or manual task |
| reconcile | provider, external_event_id, evidence_ref, kind, amount_minor, currency, settled_at | ledger references and match status |
| stop | operator_identity, reason | shutdown epoch and affected jobs |
| report | date_range | audited aggregates and exceptions |

Use UTC instants, integer milliseconds and minor currency units. Idempotency keys scope to environment, operation and account. Conflicting payload reuse returns conflict. Common errors are denied_rights, missing_capability, budget_deny, needs_review, stale_evidence, rate_limited and ambiguous_remote_result. Only transient known-safe failures retry with bounded backoff. Provider adapters declare supported actions, scopes, costs, quota behavior, permission source and evidence TTL. Sign and deduplicate supported webhooks or use permitted polling. Manual receipts identify operator, time, evidence and external reference.
