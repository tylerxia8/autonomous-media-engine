"""Command-line entry point for the local AAME simulation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from subprocess import SubprocessError

from aame.demo import run_demo
from aame.qualification import content_rewards_template, direct_pilot_template, qualify, utc_time
from aame.selection import rank_campaigns
from aame.transcription import transcribe
from aame.workflow import Workflow


def timestamp(value):
    result = utc_time(value)
    if result is None:
        raise argparse.ArgumentTypeError("expected a UTC ISO 8601 timestamp")
    return result


def command_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the complete synthetic media and payout fixture")
    demo.add_argument("directory", type=Path)
    template = commands.add_parser("content-rewards-template", help="print a blocked evidence packet")
    template.add_argument("campaign_id")
    direct = commands.add_parser("direct-pilot-template", help="print a blocked direct deal packet")
    direct.add_argument("campaign_id")
    rank = commands.add_parser("rank-campaigns", help="rank reviewed campaign evidence offline")
    rank.add_argument("candidates", type=Path)
    rank.add_argument("--route", choices=("direct", "content_rewards"), default="direct")
    rank.add_argument("--budget-cents", type=int, default=0)
    speech = commands.add_parser("transcribe", help="transcribe one authorized file locally")
    speech.add_argument("directory", type=Path)
    speech.add_argument("--launch-at", type=timestamp, required=True)
    speech.add_argument("--packet", required=True, type=Path)
    speech.add_argument("--source-root", required=True, type=Path)
    speech.add_argument("--source", required=True)
    speech.add_argument("--model-root", required=True, type=Path)
    speech.add_argument("--model", required=True)
    speech.add_argument("--model-sha256", required=True)
    speech.add_argument("--output", required=True, type=Path)
    owner = commands.add_parser("owner-time", help="record owner operator time")
    owner.add_argument("directory", type=Path)
    owner.add_argument("--launch-at", type=timestamp, required=True)
    owner.add_argument("--key", required=True)
    owner.add_argument("--seconds", type=int, required=True)
    for command in ("prepare", "review", "publish", "submit", "approve", "reject", "reconcile", "revoke", "stop", "report"):
        subcommand = commands.add_parser(command)
        subcommand.add_argument("directory", type=Path)
        subcommand.add_argument("--launch-at", type=timestamp, required=True)
        if command not in ("stop", "report"):
            subcommand.add_argument("job")
        if command == "prepare":
            subcommand.add_argument("--packet", required=True, type=Path)
            subcommand.add_argument("--source-root", required=True, type=Path)
            subcommand.add_argument("--source", required=True)
            subcommand.add_argument("--transcript", required=True)
            subcommand.add_argument("--transcript-sha256", required=True)
        if command == "review":
            subcommand.add_argument("--artifact-sha256", required=True)
            subcommand.add_argument("--pre-reviewed", action="store_true")
        if command == "submit":
            subcommand.add_argument("--deadline", type=timestamp, required=True)
    return parser


def run(args, now):
    if args.command == "demo":
        return run_demo(args.directory)
    if args.command == "content-rewards-template":
        return content_rewards_template(args.campaign_id)
    if args.command == "direct-pilot-template":
        return direct_pilot_template(args.campaign_id)
    if args.command == "rank-campaigns":
        candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
        return rank_campaigns(candidates, now=now, budget_cents=args.budget_cents, route=args.route)
    if args.command == "transcribe":
        workflow = Workflow(args.directory, launch_at=args.launch_at)
        workflow.check_running()
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        decision = qualify(packet, now)
        if decision["status"] != "evidence_complete":
            raise ValueError("qualification blocked: " + ", ".join(decision["blockers"]))
        digest = transcribe(
            args.source_root, args.source, args.output, expected_source_sha256=packet["asset_id"],
            model_root=args.model_root, model_relative_path=args.model,
            expected_model_sha256=args.model_sha256,
        )
        return {"transcript": str(args.output), "sha256": digest}
    if args.command != "prepare" and not (args.directory / "workflow.sqlite").is_file():
        raise ValueError("workflow directory does not exist")
    workflow = Workflow(args.directory, launch_at=args.launch_at)
    match args.command:
        case "prepare":
            packet = json.loads(args.packet.read_text(encoding="utf-8"))
            return workflow.prepare(
                args.job, packet=packet, source_root=args.source_root, source=args.source,
                transcript=args.transcript, transcript_hash=args.transcript_sha256, now=now,
            )
        case "review":
            workflow.review(
                args.job, artifact_hash=args.artifact_sha256, now=now, pre_review=args.pre_reviewed,
            )
        case "publish":
            workflow.publish_fixture(args.job, now=now)
        case "submit":
            workflow.submit_fixture(args.job, deadline=args.deadline, now=now)
        case "approve" | "reject":
            workflow.record_review_fixture(args.job, approved=args.command == "approve", now=now)
        case "reconcile":
            workflow.reconcile_fixture(args.job, now=now)
        case "revoke":
            workflow.revoke(args.job, now=now)
        case "owner-time":
            workflow.record_owner_time(args.key, seconds=args.seconds, now=now)
        case "stop":
            workflow.stop(now=now)
    return workflow.report(now=now)


def main():
    parser = command_parser()
    args = parser.parse_args()
    try:
        result = run(args, datetime.now(timezone.utc))
    except (ValueError, OSError, SubprocessError) as error:
        parser.exit(1, f"AAME: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
