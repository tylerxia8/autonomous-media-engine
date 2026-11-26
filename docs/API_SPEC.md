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

## YouTube Shorts simulation

The offline adapter makes an injected simulation call after explicit owner enablement, same-request authorization, expiry, rights, QA, channel OAuth and quota checks. This contract sends explicit privacy, audience and paid-placement settings. A receipt requires processed media and matching visibility. Unknown outcomes block replay. Production must resolve evidence at dispatch, conform to OAuth and upload UX requirements, account for paid work through the ledger, use durable attempts and verify the processed remote status before generating a campaign handoff.

## Offline opportunity qualification

Run `python -B -m aame.qualification /path/to/evidence.json`. Keep actual evidence and account identifiers outside Git. The command reads a local operator-reviewed packet and emits a point-in-time decision. Exit 0 means the required evidence fields and permission scopes passed. Exit 1 means blocked. Exit 2 means the packet could not be read or parsed.

- Identify the exact snapshot with nonempty `campaign_id`, `version`, `platform`, `account_id` and `asset_id`.
- Add `facts` records for `eligibility`, `active_funding`, `commercial_rights` and `payment`. Each record requires a reviewer, a reference to reviewed evidence, literal `verified: true`, UTC `observed_at` and `expires_at` timestamps, and a `scope` object containing the five exact identifiers.
- Add `fixed_payment` with `fee_usd_cents`, `max_deductions_usd_cents`, `minimum_views`, `max_clearing_days`, `review_order` (`pre_then_post` or `post_only`), `submission_deadline_rule` and `withdrawal_terms`. For a positive view minimum include `view_metric_and_window`. The payment fact's `terms` must match the full payment object.
- Add `permissions` keyed by action. Each record uses the same evidence fields plus the exact `action` and `mode` of `manual` or `automated`. A missing or expired grant yields `disabled`. A manual grant supports only a separately authorized operator handoff. Follow the [platform capability matrix](CAMPAIGN_FEASIBILITY.md) when reviewing grants, including the pending Content Rewards automation restriction.

The command checks attestations and always emits `live_enabled: false`. Production requires a trusted evidence store, independent review, fresh dispatch gates and owner authorization.
