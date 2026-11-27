"""Pure offline direct-pilot delivery contract; no network or payment authority.

The caller must independently resolve current rights, QA and authenticated
provider receipts. These checks only bind the agreed deliverables to evidence.
"""

from datetime import timedelta
from hashlib import sha256
import json
import re


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _utc(value):
    return value.utcoffset() == timedelta(0)


def bundle_manifest(*, agreement_id, version, destination_ref, expected_count, clips):
    """Build a canonical manifest, one agreement-level delivery, not a fee per clip.

    Each clip is a (job_id, QA-approved artifact SHA-256) tuple. The caller
    resolves these against immutable, independently reviewed artifacts.
    """
    if not all(_text(v) for v in (agreement_id, version, destination_ref)):
        raise ValueError("agreement identity and destination required")
    if type(expected_count) is not int or not 1 <= expected_count <= 100:
        raise ValueError("invalid contracted clip count")
    if not isinstance(clips, (list, tuple)) or len(clips) != expected_count:
        raise ValueError("incomplete contracted bundle")
    jobs, hashes = set(), set()
    entries = []
    for entry in clips:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError("invalid clip entry")
        job_id, artifact = entry
        if not _text(job_id) or not _hash(artifact):
            raise ValueError("invalid clip identity")
        if job_id in jobs or artifact in hashes:
            raise ValueError("duplicate clip")
        jobs.add(job_id)
        hashes.add(artifact)
        entries.append({"job_id": job_id, "artifact_sha256": artifact})
    manifest = {
        "agreement_id": agreement_id,
        "version": version,
        "destination_ref": destination_ref,
        "expected_count": expected_count,
        "clips": sorted(entries, key=lambda item: item["job_id"]),
    }
    return manifest


def manifest_digest(manifest):
    """Stable manifest binding. No live idempotency guarantee is implied."""
    normalized = bundle_manifest(
        agreement_id=manifest["agreement_id"],
        version=manifest["version"],
        destination_ref=manifest["destination_ref"],
        expected_count=manifest["expected_count"],
        clips=[(item["job_id"], item["artifact_sha256"]) for item in manifest["clips"]],
    )
    return sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode("ascii")).hexdigest()


def validate_receipt(manifest, receipt, *, dispatched_at, deadline, now):
    """Validate a previously authenticated receipt's shape and binding.

    A complete, timely receipt is evidence of delivery only, never proof of
    earned revenue or cleared funds. Unknown/partial outcomes cannot complete.
    """
    if not all(_utc(t) for t in (dispatched_at, deadline, now)):
        raise ValueError("UTC times required")
    if dispatched_at > deadline or dispatched_at > now:
        raise ValueError("invalid dispatch chronology")
    if not isinstance(receipt, dict):
        raise ValueError("receipt required")
    if (receipt.get("manifest_sha256") != manifest_digest(manifest)
            or receipt.get("destination_ref") != manifest["destination_ref"]
            or not _text(receipt.get("provider_receipt_id"))):
        raise ValueError("receipt binding mismatch")
    accepted_at = receipt.get("accepted_at")
    if (not hasattr(accepted_at, "utcoffset") or not _utc(accepted_at)
            or not dispatched_at <= accepted_at <= min(deadline, now)):
        raise ValueError("invalid acceptance chronology")
    artifacts = receipt.get("accepted_artifact_sha256s")
    if (not isinstance(artifacts, list) or not all(_hash(h) for h in artifacts)
            or len(artifacts) != len(set(artifacts))
            or set(artifacts) != {c["artifact_sha256"] for c in manifest["clips"]}):
        raise ValueError("partial, duplicate or mismatched delivery")
    if receipt.get("status") != "accepted":
        raise ValueError("delivery not accepted")
    return {"status": "delivery_evidence_complete",
            "provider_receipt_id": receipt["provider_receipt_id"],
            "manifest_sha256": receipt["manifest_sha256"],
            "live_enabled": False, "cash_verified": False}
