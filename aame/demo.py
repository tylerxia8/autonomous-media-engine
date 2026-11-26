"""Generate synthetic media and exercise the local AAME workflow."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from aame.qualification import ACTIONS, FACTS
from aame.workflow import Workflow


DEMO_LAUNCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture_inputs(root):
    root.mkdir(mode=0o700, parents=True)
    source = root / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "12", "-c:v", "mpeg4", "-c:a", "aac", str(source),
        ],
        check=True,
        timeout=30,
    )
    transcript = root / "transcript.json"
    transcript.write_text(
        json.dumps([
            {"start_ms": 250, "end_ms": 3800, "text": "Look at this surprising result."},
            {"start_ms": 4000, "end_ms": 7800, "text": "Here is what made the difference."},
            {"start_ms": 8000, "end_ms": 11200, "text": "That is the end of this test."},
        ]),
        encoding="utf-8",
    )
    scope = {
        "campaign_id": "fixture-offer",
        "version": "1",
        "platform": "youtube",
        "account_id": "fixture-channel",
        "asset_id": sha256(source.read_bytes()).hexdigest(),
    }
    payment = {
        "fee_usd_cents": 1500,
        "max_deductions_usd_cents": 100,
        "minimum_views": 0,
        "max_clearing_days": 5,
        "review_order": "post_only",
        "submission_deadline_rule": "30 minutes after posting",
        "withdrawal_terms": "fixture settlement",
    }
    evidence = {
        "reference": "fixture:evidence",
        "reviewer": "fixture:reviewer",
        "verified": True,
        "observed_at": DEMO_LAUNCH.isoformat(),
        "expires_at": (DEMO_LAUNCH + timedelta(days=7)).isoformat(),
        "scope": scope,
    }
    facts = {name: dict(evidence) for name in FACTS}
    facts["payment"]["terms"] = payment
    packet = {
        **scope,
        "fixed_payment": payment,
        "facts": facts,
        "permissions": {
            action: {
                **evidence, "action": action,
                "mode": "automated" if action == "publish" else "manual",
            }
            for action in ACTIONS
        },
    }
    return packet, source.name, transcript.name, sha256(transcript.read_bytes()).hexdigest()


def run_demo(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True)
    source_root = directory / "inputs"
    packet, source, transcript, transcript_hash = fixture_inputs(source_root)
    workflow = Workflow(directory / "output", launch_at=DEMO_LAUNCH)
    now = DEMO_LAUNCH + timedelta(hours=1)
    receipt = workflow.prepare(
        "fixture", packet=packet, source_root=source_root, source=source, transcript=transcript,
        transcript_hash=transcript_hash, now=now,
    )
    workflow.review("fixture", artifact_hash=receipt["output_sha256"], now=now)
    workflow.publish_fixture("fixture", now=now)
    workflow.submit_fixture("fixture", deadline=now + timedelta(minutes=30), now=now)
    workflow.record_review_fixture("fixture", approved=True, now=now)
    workflow.reconcile_fixture("fixture", now=now + timedelta(days=1))
    return workflow.report(now=now + timedelta(days=1))
