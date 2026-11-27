# Upload-Post request planning

The local planner supports one YouTube Short or Instagram Reel per operation. It reads an approved local MP4, checks its digest, and produces the request ID and exact plan fingerprint. Submit and poll are dry-run only from the CLI. An injected fixture tests multipart construction, authentication format and status handling offline. The planner accepts only the connected-profile label today. [Upload API](https://docs.upload-post.com/api/upload-video) · [Status API](https://docs.upload-post.com/api/upload-status/)

Keep real plans, approval records and account details outside Git. Populate a JSON plan with these fields:

```json
{
  "operation_id": "production:campaign:job-123:youtube",
  "profile": "approved-profile",
  "platform": "youtube",
  "artifact_sha256": "<SHA-256 of approved MP4>",
  "title": "Approved title",
  "description": "Approved description",
  "visibility": "public",
  "made_for_kids": false,
  "paid_partnership": false,
  "synthetic_media": false
}
```

Use a stable, unique operation ID per destination upload. Review the exact plan fingerprint and preserve it alongside the request ID.

```sh
python -B -m aame.upload_post submit /private/plan.json /private/clip.mp4
python -B -m aame.upload_post poll /private/plan.json
```

## Prerequisites for an authenticated worker

1. Bind a trusted, expiring approval record to the campaign version, source rights, QA evidence, exact artifact and metadata, owner authorization, and immutable platform account/channel ID. Verify the active Upload-Post profile resolves to that same ID through an official account endpoint. A reconnected profile can change destinations. Disable production dispatch if the provider cannot guarantee the bound destination through request execution.
2. Persist the operation ID, plan fingerprint, request ID and exact destination in a durable write-ahead journal. Under the same dispatch claim, verify emergency STOP and the budget reservation. Check fresh authorization immediately before possible mutation. Once an attempt begins, use status-only recovery after timeout or restart. A missing status requires operator reconciliation.
3. Load the key from the worker's secret manager. Use `Authorization: Apikey …` and fixed HTTPS endpoints, strict TLS, bounded response handling and timeouts. Ensure the client cannot forward the key or media by following redirects or relying on ambient proxies.
4. Reconcile the provider's result to its echoed request ID, fingerprint and platform. Independently verify the published account and visibility before creating a campaign receipt. Keep campaign submission separate. Instagram paid partnerships require a separate authorized path with native disclosure.

Run offline tests with `python -B -m unittest discover -s tests -p 'test_upload_post.py' -v`.
