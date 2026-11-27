# Operations runbook

## Start a pilot

1. Review active rights, current campaign, account credentials, permitted actions and approved spend limit.
2. Run dry-run on authorized fixture. Check independent QA, ledger totals and emergency stop. Clear all ambiguities.
3. In production only, record explicit operator enablement and scope. Start one eligible job and capture receipts. Retain approved evidence and schedule payout follow-up.
4. Import matched bank evidence and reconcile. Flag stale approvals, disputed funds, reversals and thresholds. Reconcile even after posting stops.

## Weekly owner report

Send an authorized digest or show locally until a delivery channel is cleared. Include received cash, estimated and approved earnings, expenses, cash net, incurred costs, commitments, budget remaining by cap, profit/day, owner minutes, clip cohort results, payout aging, experiment impact and decisions needing approval. Target under 15 minutes of weekly routine time. Escalate permission changes, rejected payouts or financial exposure immediately.

## Stop and recover

Activate persistent emergency stop, pause acquisition/publish/submission/paid dispatch, and freeze reservations for uncertain calls. Record incident scope and revoke affected credentials where authorized. Reconcile external IDs before retrying. Handle rights withdrawal through the permitted removal path and record evidence. Restore from encrypted backups and revalidate current rights, budget, provider receipts, queues and environment identity. Require authenticated owner re-enable after reviewing incident. Track checks for policy expiry, quota, stuck jobs, disk, reconciliation and worker heartbeat.

## Run and inspect the local simulation

1. Run `python -B -m aame demo /tmp/aame-demo` with an unused path. Review the report and play `/tmp/aame-demo/output/fixture.mp4`.
2. For a separate local exercise, use the qualification packet described in [the API spec](API_SPEC.md). Bind the source SHA-256 in `asset_id`. Supply timestamped transcript JSON with start/end in milliseconds and text for each cue. The optional local Whisper command can generate that file with preinstalled Whisper, NumPy, a patched weights-only PyTorch build, and trusted local weights. Run the Whisper worker in a host sandbox without egress before processing external material.
3. Run `python -B -m aame prepare --help` for inputs. Pass the same UTC launch instant when reopening a workflow. Review the output visually, then pass its exact digest to `review`. The simulated publish stage requires an automated fixture grant and the simulated submit stage requires a manual grant. Use the report's `published_at` and the supported 30-minute fixture deadline when exercising submit. Real campaign deadline rules require their own verified adapter.
4. Use `approve` or `reject` to record the simulated campaign decision, then `reconcile` for an approved fixture. Run `report` to inspect durable status, payout aging and simulated cash over the trailing seven days. Record owner involvement with `owner-time` and a unique entry key. `stop` blocks new workflow actions and `revoke` blocks the affected job. Existing simulated submissions can still reconcile under a current dedicated grant. Interrupted renders need operator inspection. Keep fixture and future production databases separate and keep runtime files outside Git.

The [official YouTube resumable protocol](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol) is represented by offline request and response contracts. A future production dispatcher must authenticate the channel, persist the session before transfer, recheck rights and budget at dispatch, resolve ambiguous outcomes through the same session, and independently confirm processing/visibility. The transport and session journal are available as separately tested library components. The workflow CLI stays simulated. A production caller must supply scoped OAuth and a fresh authorization callback for every request, and keep the session journal on a private filesystem. A live pilot still requires an independently verified campaign or signed payer, a licensed source, a cleared destination account, a permitted submission workflow and bank settlement evidence.

## YouTube OAuth and dry-run validation (live execution blocked)

**Release hold:** the standalone entry point does not yet resolve durable workflow authorization, QA, rights, budget, quota, and the shared emergency stop. `--execute` is intentionally rejected before reading credentials or calling providers. Do not schedule live uploads or invoke the internal transport candidate. OAuth setup is separate from live release approval.

Use a Google Cloud project you control, enable the YouTube Data API v3, and configure a Desktop OAuth client. On the channel owner's workstation, install `google-auth-oauthlib` and run `python -B -m aame.youtube_live authorize CLIENT_JSON TOKEN_JSON`. Google opens consent in the local browser. Select the actual upload channel and authorize upload and read-only channel verification. Keep the Desktop client JSON and generated token owner-only, outside Git and chat. Google documents that external OAuth apps in Testing can issue refresh tokens that expire after seven days when requesting YouTube scopes. Configure an appropriate production consent setup for ongoing use. [Google desktop authorization](https://developers.google.com/identity/protocols/oauth2/native-app) · [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)

Provide an owner-only JSON approval file with this shape. Replace example values with actual verified evidence and a UTC approval window.

```json
{
  "verified": true,
  "owner_enabled": true,
  "reference": "private owner approval reference",
  "reviewer": "owner",
  "rights_reference": "private source rights reference",
  "observed_at": "2026-11-27T00:00:00Z",
  "expires_at": "2026-11-28T00:00:00Z",
  "category_id": "22",
  "contains_synthetic_media": false,
  "upload": {
    "channel_id": "UC followed by the exact channel identifier",
    "campaign_version": "approved cut revision",
    "artifact_hash": "lowercase SHA-256 of the approved MP4",
    "title": "Approved title",
    "description": "Approved description with source credit",
    "visibility": "private",
    "made_for_kids": false,
    "paid_product_placement": false
  }
}
```

Run `python -B -m aame.youtube_live advance --approval APPROVAL_JSON --video CLIP_MP4 --credentials TOKEN_JSON --journal PRIVATE_DIRECTORY` for local validation. Do not append `--execute` until the durable release gate is implemented, independently tested, and reviewed. The offline transport candidate exercises channel confirmation, resumable sessions, processing and visibility; none of these tests establish production authorization. A future scheduler must use a trusted, current durable job and recheck all policy controls at every provider boundary. Keep the workstation OAuth token on that workstation. Place a file named `STOP` in the journal directory to block new requests. Withdraw or expire the approval to revoke a specific video. The simulation CLI is separate. [Channels: list](https://developers.google.com/youtube/data/reference/rest/v3/channels/list) · [YouTube resumable upload](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
