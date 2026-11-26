# Architecture

Start with a local, single-host modular application using SQLite transactions, a disk-backed content-addressed store, local Whisper and FFmpeg workers, and a command-line operator interface. Agents design modules. Runtime workflow and policy are deterministic software.

| Boundary | Input and output |
|---|---|
| Campaign discovery | Approved campaign sources or permitted manual evidence → structured offer and capability snapshot |
| Orchestrator | Job request → leased stage attempts, transactional outbox and durable audit |
| Acquisition | Explicit rights and allowlisted source → verified immutable asset |
| Viral Intelligence | Asset and as-of signal snapshots → versioned ranked spans and explanations |
| Production | Ranked span and destination profile → immutable render and transcript |
| Independent QA | Artifact, authorization and rules → hash-bound decision with reasons |
| Publishing and submission | QA approval plus current capability grants → provider or operator receipts |
| Accounting | Reservations, statuses and bank evidence → ledger, reconciled cash and reporting |

Workflow runs qualify → authorize → acquire → transcribe → select → reserve render → render → QA → required pre-post review → publish → submit → reconcile. The first reservation precedes any billable work. States include blocked, rejected, deferred, retryable, reconciliation required and terminal. Payout polling continues independently of completed publishing.

Lease stages with fenced workers. Commit state, audit record and outbox in one transaction. A dispatcher rechecks shutdown, evidence, rights and budget immediately before calling a provider. An ambiguous outcome holds its reservation and reconciles by remote ID, permitted lookup or operator review. External systems can commit while a call is interrupted. Track in-flight requests during shutdown.

Local stream ingest is a later allowlisted adapter with bounded ring buffer, source-time mapping and reconnect rules. Feed authorized spans through the same independent QA and publish gates. Keep raw media, metadata and jobs separately deletable subject to legal retention. Upgrade the database or add a broker only once load justifies it.
