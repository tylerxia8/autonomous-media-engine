# Upload-Post durable dispatch contract (offline)

AAME-007 / AAME-012, partial AT-007 and AT-012. This is a local primitive, not an enabled network worker.

Provider documentation reviewed November 26, 2026: [upload](https://docs.upload-post.com/api/upload-video/), [status](https://docs.upload-post.com/api/upload-status/), [scheduled posts](https://docs.upload-post.com/api/schedule-posts/). Provider deduplication is documented as time-limited (24 hours); external_id is correlation only. Do not depend on either to enforce permanent at-most-once submission. A failed or not-found status is not evidence that no side effect happened.

Before any future authenticated POST, bind the trusted job, approved artifact hash and metadata, current rights and QA, immutable platform account, fresh grant, quota and active reservation; check STOP. Under a fenced dispatcher use the same private SQLite journal across all workers and restarts. Commit the unique claim before POST. A caller that does not win the claim may only poll/reconcile. Never generate a new operation ID for an ambiguous attempt. A crash between claim and POST may sacrifice a publication; correctness is preferable to duplicate spending/posts.

A provider-reported publication is not an independently verified destination or visibility receipt, nor cash evidence. Never erase a reported success on a stale poll; conflicting URLs require reconciliation. Pre-existing uploads made outside the journal must be imported and reconciled separately, not replayed. Multi-platform requests require individual platform bindings; current fixture adapter uses one platform per operation. No raw account IDs, histories, credentials, media, journal databases or customer records in Git.

Remaining gates: trusted destination resolver, private journal lifecycle/backups (restoration cannot silently lose outstanding claims), global STOP and active financial reservation integration, authenticated transport security, official provider permissions, independently verified destination and visibility, and qualified payer/campaign. Do not deploy or schedule this module by itself. In particular, missing external_id on historical uploads is not a reason to weaken binding for future jobs.

Run: python -B -m unittest discover -s tests -p 'test_upload_post_journal.py' -v
