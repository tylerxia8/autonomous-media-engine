# Autonomous AI Media Engine

AAME turns explicitly authorized source material into short videos and measures success in reconciled cash profit. The first milestone is one eligible clip with an evidenced payout. Dry-run is the default.

Start with the [PRD](docs/PRD.md), [engineering backlog](docs/REQUIREMENTS.md), [implementation plan](docs/IMPLEMENTATION_PLAN.md), and [acceptance plan](docs/ACCEPTANCE_TESTS.md). See [campaign evidence](docs/CAMPAIGN_FEASIBILITY.md), [research registry](docs/RESEARCH_REGISTRY.md), and [operating controls](docs/OPERATIONS_RUNBOOK.md).

The V2.0 attachment was unavailable during drafting. The commissioning message is the provisional requirements baseline. Reconcile the attachment before treating this plan as authoritative. This branch contains design documentation and an offline YouTube Shorts publishing contract. Run its mock tests with `python -B -m unittest discover -s tests -v`.

## Run the local revenue workflow

Requires Python 3.11+ and Linux FFmpeg/FFprobe with libass and libx264. Run the synthetic end-to-end demo and test suite from the repository root.

```sh
python -B -m aame demo /tmp/aame-demo
python -B -m unittest discover -s tests -v
```

Use an unused demo directory. The demo creates a synthetic 12-second source, renders a captioned vertical MP4, verifies the artifact, exercises the YouTube and marketplace handoffs through fixtures, and records a simulated payout in SQLite. The output video is `output/fixture.mp4` under that directory. The report labels all ledger amounts as simulated and leaves verified cash break-even false.

Use `python -B -m aame --help` for individual local stages. The optional Whisper command requires preinstalled dependencies and trusted, checksum-pinned weights. The supplied timestamped transcript path works without Whisper. See the [local runbook](docs/OPERATIONS_RUNBOOK.md) for operating boundaries and remaining launch gates.
