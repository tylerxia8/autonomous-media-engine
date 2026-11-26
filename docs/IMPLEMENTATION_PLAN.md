# Implementation and critical path

Platform evidence checked November 26, 2026. Build YouTube Shorts first. The November 2 YouTube Data API change removed the private-only restriction on uploads from unverified projects. Set visibility explicitly and confirm observed visibility and processing before handing off a URL. Instagram Reels is secondary. TikTok Direct Post is excluded for AAME's internal account-management use. [Capability matrix](CAMPAIGN_FEASIBILITY.md) · [YouTube revision history](https://developers.google.com/youtube/data/revision_history) · [TikTok guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)

## First cash

Qualify a signed fixed-fee direct pilot for one business with an ongoing owned video feed. Require zero view threshold and objective delivery acceptance without per-post human review. Obtain explicit editing, commercial rights, automated publishing and automated delivery grants. Prefer a buyer-authorized channel so the offer depends on useful deliverables and avoids an audience-size gate. Keep discovery and contract approval as one-time operator actions. Rank agreements by downside net cash and time to cleared cash. AAME has no verified buyer or signed agreement.

First-cash sequence: confirm buyer and signed scope → verify funds and source grant → simulate one authorized clip → pass technical and contextual checks → publish through a cleared adapter or deliver to the agreed endpoint → receive delivery acknowledgement → match cleared cash. A production dispatcher and settlement adapter must pass acceptance before unattended live work. [Direct pilot feasibility](CAMPAIGN_FEASIBILITY.md)

| Day | Work and exit |
|---|---|
| 1 | AAME-002 records a single candidate's signed rights, offer evidence, cleared-cash timeline and per-action permissions. If no offer clears, record blocker and run fixture. |
| 2 | Implement atomic budget reservations, durable state and fail-closed rights, owner and shutdown gates (AAME-003–007). Start at $0 approved spend. |
| 3–4 | Run authorized fixture through local transcription, deterministic moment selection, vertical render, captions and independent QA (AAME-008–011). |
| 5 | Extend the mock-tested YouTube adapter into a separately reviewed integration. Add authorized OAuth, durable idempotency, resumable upload and processing/visibility reconciliation. Implement the approved direct delivery receipt and enforce contracted deadlines (AAME-012–013). |
| 6 | Replay approval, withdrawal, duplicate receipts, reversals, ambiguous uploads and shutdown offline. Produce a local cash report (AAME-014–015, 026–027). |
| 7 | Pipeline readiness target. A future pilot requires explicit live authorization and all current evidence. Track cash through clearing, which can occur after day seven. |

Preserve $30 first-week, $50 initial cumulative capital-at-risk and $300 monthly ceiling. Enforce any lower owner-approved limit. Unlock the full monthly ceiling only after verified cash break-even and affirmative owner authorization. No increase occurs automatically. [Financial policy](FINANCIAL_MODEL.md)

Keep advanced ML and dashboards off the critical path. Use a deterministic ranker, local tools and a compact cash report. Evaluate Instagram only after the YouTube workflow or when an evidenced fixed-payment opportunity justifies it. Assign workstreams on separate branches and review contracts independently. [Collaboration](../AGENTS.md)
