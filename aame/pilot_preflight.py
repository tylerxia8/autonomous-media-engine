"""Offline immutable pilot plan. Never authorizes checkout, rendering or delivery.

Database path must be in a private, access-controlled durable directory outside
the repository. Order identifiers are opaque internal references, not PII.
The caller must establish current rights and cost/STOP gates independently.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from aame.video import (
    MAX_SOURCE_BYTES, MAX_TRANSCRIPT_BYTES, RECIPE_VERSION, SCORING_VERSION,
    VideoError, _snapshot, _source_duration, _load_cues, plan_bundle,
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(payload):
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _ref(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("bounded internal reference required")
    return value


def _open(database):
    connection = sqlite3.connect(database, timeout=10)
    try:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pilot_preflight (
                order_ref TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL
            )"""
        )
        connection.commit()
    except BaseException:
        connection.close()
        raise
    return connection


def preflight(database, source_root, asset_relative_path, transcript_relative_path,
              *, order_ref, agreement_version, destination_ref,
              expected_source_sha256, expected_transcript_sha256,
              count=3, amount_cents=7500, excluded_windows=()):
    """Validate actual source and transcript before storing a fixed pilot plan.

    No checkout or paid work is performed. Same order + same canonical plan is
    an idempotent replay; any change requires a new order ID. The local record
    is not proof of rights, editorial quality, payment, or delivery authority.
    """
    for ref in (order_ref, agreement_version, destination_ref):
        _ref(ref)
    if type(count) is not int or count not in (1, 3):
        raise ValueError("only the one- and three-clip pilot are supported")
    if type(amount_cents) is not int or amount_cents != count * 2500:
        raise ValueError("pilot price must match contracted clip count")
    if not isinstance(excluded_windows, (tuple, list)):
        raise VideoError("invalid excluded windows")
    with tempfile.TemporaryDirectory(prefix="aame-preflight-") as scratch:
        root = Path(scratch)
        source, transcript = root / "source.mp4", root / "transcript.json"
        _snapshot(source_root, asset_relative_path, source,
                  expected_source_sha256, MAX_SOURCE_BYTES)
        _snapshot(source_root, transcript_relative_path, transcript,
                  expected_transcript_sha256, MAX_TRANSCRIPT_BYTES)
        duration = _source_duration(source)
        if duration > 30 * 60 * 1000:
            raise VideoError("pilot source exceeds 30 minutes")
        cues = _load_cues(transcript, duration)
        candidates = plan_bundle(cues, count=count, minimum_ms=20000,
                                 maximum_ms=35000, excluded_windows=excluded_windows)
        exclusions = sorted([list(w) for w in excluded_windows])
        plan = {
            "schema": 1, "order_ref": order_ref,
            "agreement_version": agreement_version,
            "destination_ref": destination_ref, "currency": "usd",
            "amount_cents": amount_cents, "count": count,
            "source_sha256": expected_source_sha256,
            "transcript_sha256": expected_transcript_sha256,
            "source_duration_ms": duration, "recipe": RECIPE_VERSION,
            "scoring": SCORING_VERSION, "minimum_ms": 20000, "maximum_ms": 35000,
            "excluded_windows": exclusions,
            "windows": [[c.start_ms, c.end_ms] for c in candidates],
        }
    payload = _canonical(plan)
    digest = _digest(payload)
    with closing(_open(database)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload, digest FROM pilot_preflight WHERE order_ref=?",
                (order_ref,)).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO pilot_preflight(order_ref,payload,digest) VALUES(?,?,?)",
                    (order_ref, payload, digest))
            elif existing != (payload, digest):
                raise ValueError("order already bound to a different or corrupt plan")
    return load_plan(database, order_ref)


def load_plan(database, order_ref):
    """Recover the stored plan after restart; reject inconsistent stored bytes."""
    _ref(order_ref)
    with closing(_open(database)) as connection:
        row = connection.execute(
            "SELECT payload,digest FROM pilot_preflight WHERE order_ref=?",
            (order_ref,)).fetchone()
    if row is None:
        raise ValueError("no preflight plan for order")
    payload, digest = row
    if _digest(payload) != digest:
        raise ValueError("stored plan digest mismatch")
    plan = json.loads(payload)
    if plan.get("order_ref") != order_ref or _canonical(plan) != payload:
        raise ValueError("stored plan identity or canonical form mismatch")
    return {"plan": plan, "plan_sha256": digest, "live_enabled": False,
            "checkout_authorized": False, "cash_verified": False}
