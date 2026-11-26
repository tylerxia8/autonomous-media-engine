"""Offline qualification of operator-reviewed campaign evidence."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


IDENTITY_FIELDS = ("campaign_id", "version", "platform", "account_id", "asset_id")
ACTIONS = ("discover", "acquire", "edit", "publish", "submit", "read_metrics", "reconcile")
FACTS = ("eligibility", "active_funding", "commercial_rights", "payment")
MODES = ("manual", "automated")


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def utc_time(value):
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant if instant.utcoffset() == timedelta(0) else None


def current_evidence(record, now):
    if not isinstance(record, dict) or record.get("verified") is not True:
        return False
    observed = utc_time(record.get("observed_at"))
    expires = utc_time(record.get("expires_at"))
    return (
        nonblank(record.get("reference"))
        and nonblank(record.get("reviewer"))
        and observed is not None
        and expires is not None
        and observed <= now < expires
    )


def valid_payment(payment):
    if not isinstance(payment, dict):
        return False
    amount = payment.get("fee_usd_cents")
    fees = payment.get("max_deductions_usd_cents")
    minimum = payment.get("minimum_views")
    clearing_days = payment.get("max_clearing_days")
    return (
        type(amount) is int
        and type(fees) is int
        and 0 <= fees < amount
        and type(minimum) is int
        and minimum >= 0
        and (minimum == 0 or nonblank(payment.get("view_metric_and_window")))
        and type(clearing_days) is int
        and clearing_days >= 0
        and payment.get("review_order") in ("pre_then_post", "post_only")
        and nonblank(payment.get("submission_deadline_rule"))
        and nonblank(payment.get("withdrawal_terms"))
    )


def identity_scope(packet):
    scope = {field: packet.get(field) for field in IDENTITY_FIELDS}
    if "marketplace" in packet:
        scope["marketplace"] = packet["marketplace"]
    return scope


def content_rewards_template(campaign_id):
    if not nonblank(campaign_id):
        raise ValueError("campaign ID is required")
    identity = {
        "campaign_id": campaign_id, "version": None, "platform": "youtube",
        "account_id": None, "asset_id": None, "marketplace": "content_rewards",
    }
    payment = {
        "fee_usd_cents": None, "max_deductions_usd_cents": None,
        "minimum_views": None, "view_metric_and_window": None,
        "max_clearing_days": None, "review_order": None,
        "submission_deadline_rule": None, "withdrawal_terms": None,
    }

    def missing_evidence():
        return {
            "reference": None, "reviewer": None, "verified": False,
            "observed_at": None, "expires_at": None, "scope": dict(identity),
        }

    facts = {name: missing_evidence() for name in FACTS}
    facts["eligibility"]["clip_duration_ms"] = None
    facts["payment"]["terms"] = dict(payment)
    return {
        **identity,
        "fixed_payment": payment,
        "facts": facts,
        "permissions": {
            action: {
                **missing_evidence(), "action": action,
                "mode": "manual" if action == "submit" else None,
            }
            for action in ACTIONS
        },
    }


def qualify(packet, now):
    """Evaluate exact-snapshot attestations. Results never enable live actions."""
    if not isinstance(packet, dict):
        raise ValueError("evidence packet must be a JSON object")
    if now.utcoffset() != timedelta(0):
        raise ValueError("qualification time must be UTC")

    identity = identity_scope(packet)
    complete_identity = all(nonblank(value) for value in identity.values())
    facts = packet.get("facts")
    permissions = packet.get("permissions")
    facts = facts if isinstance(facts, dict) else {}
    permissions = permissions if isinstance(permissions, dict) else {}

    blockers = []
    if not complete_identity:
        blockers.append("incomplete_identity")
    if "marketplace" in packet and packet["marketplace"] not in ("content_rewards", "direct"):
        blockers.append("unsupported_marketplace")
    for name in FACTS:
        record = facts.get(name)
        if not current_evidence(record, now) or record.get("scope") != identity:
            blockers.append(name)
    if not valid_payment(packet.get("fixed_payment")):
        blockers.append("incomplete_fixed_payment")
    elif isinstance(facts.get("payment"), dict):
        if facts["payment"].get("terms") != packet["fixed_payment"]:
            blockers.append("payment_terms_mismatch")

    evidence_complete = not blockers
    capabilities = {}
    for action in ACTIONS:
        record = permissions.get(action)
        capabilities[action] = "disabled"
        if (
            evidence_complete
            and current_evidence(record, now)
            and record.get("scope") == identity
            and record.get("action") == action
            and record.get("mode") in MODES
            and (
                packet.get("marketplace") != "content_rewards"
                or action != "submit" or record["mode"] == "manual"
            )
        ):
            capabilities[action] = record["mode"]

    for action in ("discover", "acquire", "edit", "publish", "submit", "reconcile"):
        if capabilities[action] == "disabled":
            blockers.append(f"permission:{action}")

    return {
        "status": "blocked" if blockers else "evidence_complete",
        "checked_at": now.isoformat(),
        "capabilities": capabilities,
        "blockers": blockers,
        "live_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, help="local JSON evidence packet")
    args = parser.parse_args()
    try:
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        decision = qualify(packet, datetime.now(timezone.utc))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Invalid evidence packet: {error}\n")
    print(json.dumps(decision, indent=2))
    return 0 if decision["status"] == "evidence_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
