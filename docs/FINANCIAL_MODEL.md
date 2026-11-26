# Financial controls and optimization

Use integer cents for USD policy. Record original currency, actual clearing FX and fees when applicable. Cap non-USD exposure with a conservative evidenced conversion bound or defer. Use UTC with a recorded launch instant. Proposed week one is the first rolling 168 hours after launch. Monthly cap applies per UTC calendar month. Owner approves effective caps before any paid call. Default approved spend is $0.

| Guardrail | Enforcement |
|---|---|
| $50 maximum initial capital at risk | Before break-even, bound outstanding commitments plus paid outflows less reconciled net receipts, floored at zero. Preserve historical risk peaks and block new exposure on breach. |
| $30 first-week expense ceiling | Count committed and incurred spend with linked reservations and charge allocation. Carry uncertain commitments until reconciled. |
| $300 monthly ceiling | Apply paid, accrued and reserved spend with no double count. Require evidence of verified break-even plus explicit authorization before full ceiling can be enabled. |
| Concurrent spending | Reserve worst case including fees and retries in one transaction across all constraints. Reject unbounded calls. Release confirmed unused amounts only. |

Expenses are distinct from cash paid when incurred but unsettled. Cleared cash includes matched bank or equivalent receipts. Segregate estimates, approvals, cleared cash and expenses and post reversals explicitly. Define verified cash break-even as at least one legitimate reconciled receipt and cumulative cleared net receipts ≥ cumulative operating cash paid. Show pending liabilities separately and require coverage of open commitments before proposing higher spend. A later reversal that removes break-even triggers a freeze on expanded spend and owner review. Owner funds and transfers do not count as revenue.

Rank eligible work by expected collectible net cash less marginal costs, adjusted for rejection, payout thresholds, funding, time and fees. For unknown probabilities use conservative scenarios. Gross rate × eligible views does not override a cap, cutoff, threshold or settlement risk. Fixed-fee opportunities reduce view risk when terms and payer are verified.

Proposed initial incremental operating estimate using existing hardware. Local tool licenses and hosting are $0 in this plan. Allow $0–$5 incremental electricity/storage for a small pilot pending a measured run and local tariff. Unknown payment, rights and provider fees must be verified before commitment. No paid services assumed. Example planning case $15 cleared revenue − $3 cash cost = $12 net cash. Baseline revenue is $0 until a payment is evidenced.
