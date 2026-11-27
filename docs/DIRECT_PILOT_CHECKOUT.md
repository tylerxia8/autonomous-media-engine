# First-cash direct pilot: checkout and clearing

Status: offline candidate only, 2026-11-27. Supports AAME-002/005/007/014. No merchant account verified or activated, no live charges, no customer commitment. Existing direct bundle and finance ledger remain authoritative for their respective stages.

## Minimal payment path

Prefer an existing authorized US merchant account with known settlement schedule over creating a new one. Stripe standard domestic card pricing currently lists 2.9% + $0.30, no setup or monthly fee (https://stripe.com/pricing). Actual account pricing, taxes, refunds, dispute costs and all outstanding commitments must be confirmed and bounded before accepting a paid order. Stripe's initial payout typically takes 7–14 days (https://docs.stripe.com/payouts); do not promise cash break-even within 48 hours. No paid add-ons, subscriptions, international cards, currency conversion or instant payouts in this candidate.

Illustrative domestic card economics, before fulfillment, tax, refund/dispute and other costs, rounding fees upward to the nearest cent:

| Pilot | Gross | Fee estimate | Net |
|---|---:|---:|---:|
| One clip | $25 | $1.03 | $23.97 |
| Three clips | $75 | $2.48 | $72.52 |

A $75 pilot could cover $50 of cumulative expense only if total actual costs including payment fees are covered and earned cash clears. Do not double count a fee withheld from a net receipt. Do not use an estimate as ledger evidence.

1. Establish authorized seller identity, customer order and source/edit/delivery permissions, scope, refund terms, deadline, cost cap, and trusted private destination. No binding offers or acceptance of material terms without appropriate approval.
2. If using Stripe Checkout, create a unique one-time session from a trusted order, using the immutable order reference, exact amount, merchant account, and persisted idempotency key. Reserve the bounded exposure first. A reusable payment link alone is insufficient order binding.
3. Use signed webhook as a wake-up signal, not a payment or delivery permission; retrieve current Session, PaymentIntent and Charge using restricted authorized credentials in approved secret storage. Verify merchant identity, environment, order, exact amount, currency, capture, refunds and disputes. Keep private identifiers and payloads out of Git.
4. The offline inspect_checkout helper validates Session binding and classifies payment reports; it deliberately returns no fulfillment authority, earned revenue or cash verification. Deduplicate by provider account + payment intent + order (not webhook event alone); claim fulfillment transactionally before any side effect. Check current rights, STOP, budget and independent QA; use existing bundle manifest and authenticated delivery receipt.
5. Track prepayment as a liability until contractually earned, then reconcile actual fee, payout allocation and corresponding bank-cleared deposit. A checkout success or payout initiation does not establish verified cash break-even. Post reversals and freeze expanded spending when required. Use existing ledger, no parallel balance.
6. Before enabling any transport, demonstrate signed event validation, fresh retrieval, duplicate and out-of-order delivery, pending payments, refunds/disputes, immutable order, test/live isolation, exact payout allocation and bank deposit matching. If automated access is unavailable, a single verified owner-approved dashboard handoff may be preferable for the first order; do not exceed labor constraints or fake authorization.

References: https://docs.stripe.com/checkout/fulfillment ; https://docs.stripe.com/webhooks ; https://docs.stripe.com/payouts ; https://stripe.com/pricing .

Rollback: remove the candidate module and its tests; no migrations, no external mutations.
