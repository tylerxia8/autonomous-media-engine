# Security

Treat media, transcripts, campaign copy and API payloads as untrusted. Parse schemas and size-cap inputs. Text extracted from files or the web has no authority over tool calls or policy. Run FFmpeg and transcription in patched least-privilege workers without secrets or network, with bounded CPU, memory, disk, duration and time. Pass argument arrays. Restrict protocols, paths, redirects and network egress. Validate MIME and hash, and isolate temporary files.

Keep separate dev and production identities, OAuth scopes, databases, storage, network and credentials. Store secrets out of Git and scrub logs and artifacts. Restrict visibility of media, bank evidence and grant records. Authenticate operators, record owner limit approvals and write tamper-evident audit events for privileged changes.

A persistent global stop defaults to safe on missing control heartbeat. Dispatchers check a current shutdown epoch, production enablement and capability on each side effect. Stop starts no new operations. Cancel jobs where safe and reconcile uncertain in-flight effects. Credentials can be revoked at provider. Recovery requires incident review and an explicit authenticated re-enable. Verify with replay, resource exhaustion, hostile files, credential exposure and restoration drills.
