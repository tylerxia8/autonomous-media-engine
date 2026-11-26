# Implementation and critical path

Platform evidence checked November 26, 2026. Build YouTube Shorts first. The November 2 YouTube Data API change removed the private-only restriction on uploads from unverified projects. Set visibility explicitly and confirm observed visibility and processing before handing off a URL. Instagram Reels is secondary. TikTok Direct Post is excluded for AAME's internal account-management use. [Capability matrix](CAMPAIGN_FEASIBILITY.md) · [YouTube revision history](https://developers.google.com/youtube/data/revision_history) · [TikTok guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)

## First cash

Qualify a funded flat-fee YouTube Shorts campaign with no or low minimum views and the shortest conservative time to cleared cash. Compare it with a signed fixed-fee direct pilot using the same criteria. Prefer per-post approval over multi-deliverable retainers or variable CPM/pool payouts. Verify the campaign accepts YouTube Shorts and the specific channel. Confirm creative rights, account/KYC, disclosure, review order, submission SLA, remaining funding, fee, minimum eligible views and measurement window, validation hold, withdrawal threshold and bank arrival. Rank eligible offers by downside net cash and time to clearing. An unevidenced input blocks the live route.

First-cash sequence: qualify → acquire authorized source → produce and independently approve one Short → complete required draft review → publish through an authorized adapter → confirm processing and required visibility → operator submits through permitted UI → reconcile approval, wallet settlement and cleared receipt separately. No payer, channel, source grant or active campaign has been verified for AAME. Unattended Content Rewards submission is blocked pending documented creator API and explicit permission for the exact experience and action. Current scope is offline only.

| Day | Work and exit |
|---|---|
| 1 | AAME-002 records a single candidate's signed rights, offer evidence, cleared-cash timeline and per-action permissions. If no offer clears, record blocker and run fixture. |
| 2 | Implement atomic budget reservations, durable state and fail-closed rights, owner and shutdown gates (AAME-003–007). Start at $0 approved spend. |
| 3–4 | Run authorized fixture through local transcription, deterministic moment selection, vertical render, captions and independent QA (AAME-008–011). |
| 5 | Extend the mock-tested YouTube adapter into a separately reviewed integration. Add authorized OAuth, durable idempotency, resumable upload and processing/visibility reconciliation. Prepare the operator handoff and enforce campaign deadlines (AAME-012–013). |
| 6 | Replay approval, withdrawal, duplicate receipts, reversals, ambiguous uploads and shutdown offline. Produce a local cash report (AAME-014–015, 026–027). |
| 7 | Pipeline readiness target. A future pilot requires explicit live authorization and all current evidence. Track cash through clearing, which can occur after day seven. |

Preserve $30 first-week, $50 initial cumulative capital-at-risk and $300 monthly ceiling. Enforce any lower owner-approved limit. Unlock the full monthly ceiling only after verified cash break-even and affirmative owner authorization. No increase occurs automatically. [Financial policy](FINANCIAL_MODEL.md)

Keep advanced ML and dashboards off the critical path. Use a deterministic ranker, local tools and a compact cash report. Evaluate Instagram only after the YouTube workflow or when an evidenced fixed-payment opportunity justifies it. Assign workstreams on separate branches and review contracts independently. [Collaboration](../AGENTS.md)
