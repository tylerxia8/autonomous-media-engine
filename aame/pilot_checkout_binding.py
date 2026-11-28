"""Offline durable checkout binding; no network, payment or fulfillment authority.

Use only a private durable SQLite database and opaque internal references.
The stored descriptor is NOT a complete Stripe request. A future transport
must reserve costs, persist its exact request and check current rights/STOP
before any external mutation. No retry or replacement-session API is provided.
"""
from collections.abc import Mapping
from contextlib import closing
import json
import sqlite3
import uuid

from aame.pilot_preflight import load_plan, _canonical, _digest, _ref


def _open(database):
    connection = sqlite3.connect(database, timeout=10)
    try:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS pilot_checkout_binding (
                order_ref TEXT PRIMARY KEY,
                descriptor TEXT NOT NULL,
                descriptor_sha256 TEXT NOT NULL,
                attempt_ref TEXT NOT NULL UNIQUE,
                account_ref TEXT NOT NULL,
                live INTEGER NOT NULL CHECK(live IN (0,1)),
                session_id TEXT,
                intent_id TEXT,
                UNIQUE(account_ref,live,session_id),
                UNIQUE(account_ref,live,intent_id)
            )""")
        connection.commit()
    except BaseException:
        connection.close()
        raise
    return connection


def _descriptor(database, order_ref, account_ref, live):
    _ref(account_ref)
    if type(live) is not bool:
        raise ValueError("explicit test/live environment required")
    stored = load_plan(database, order_ref)
    plan = stored["plan"]
    return {"schema": 1, "order_ref": order_ref,
            "account_ref": account_ref, "live": live,
            "plan_sha256": stored["plan_sha256"],
            "amount_cents": plan["amount_cents"], "currency": plan["currency"],
            "mode": "payment"}


def _read(connection, order_ref, descriptor):
    row = connection.execute(
        """SELECT descriptor,descriptor_sha256,attempt_ref,account_ref,live,
                  session_id,intent_id FROM pilot_checkout_binding WHERE order_ref=?""",
        (order_ref,)).fetchone()
    if row is None:
        raise ValueError("no durable checkout attempt")
    payload, digest, attempt, account, live, session, intent = row
    if (payload != _canonical(descriptor) or digest != _digest(payload)
            or account != descriptor["account_ref"] or live != int(descriptor["live"])):
        raise ValueError("checkout descriptor changed or corrupted")
    return {"descriptor": json.loads(payload), "descriptor_sha256": digest,
            "attempt_ref": attempt, "session_id": session, "intent_id": intent,
            "live_enabled": False, "checkout_authorized": False,
            "fulfillment_authorized": False, "cash_verified": False}


def reserve_binding(database, order_ref, *, account_ref, live):
    """Reserve one immutable local descriptor, idempotent across restarts.

    This is not a spend reservation or approval to create a provider session.
    A different account/environment or plan requires a separate order; there
    is deliberately no replacement or automatic retry after an unknown outcome.
    """
    descriptor = _descriptor(database, order_ref, account_ref, live)
    payload = _canonical(descriptor)
    with closing(_open(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO pilot_checkout_binding
               (order_ref,descriptor,descriptor_sha256,attempt_ref,account_ref,live)
               VALUES (?,?,?,?,?,?) ON CONFLICT(order_ref) DO NOTHING""",
            (order_ref, payload, _digest(payload), uuid.uuid4().hex, account_ref, int(live)))
        return _read(connection, order_ref, descriptor)


def bind_session(database, order_ref, session, *, retrieved_account_ref, live):
    """Bind authenticated server-side session retrieval to a reserved descriptor.

    Caller must authenticate the transport and account independently. Metadata
    must have been set by the merchant, not a buyer. This is only identity
    binding, NOT payment classification; fresh payment/refund/dispute evidence
    and a separate fulfillment claim are required. Never use webhook payloads,
    screenshots or redirects directly. No external call occurs here.
    """
    descriptor = _descriptor(database, order_ref, retrieved_account_ref, live)
    if not isinstance(session, Mapping):
        raise ValueError("authenticated session mapping required")
    with closing(_open(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _read(connection, order_ref, descriptor)
        metadata = session.get("metadata")
        session_id = _ref(session.get("id"))
        intent = session.get("payment_intent")
        if intent is not None:
            _ref(intent)
        if (not isinstance(metadata, Mapping)
                or metadata.get("aame_plan_sha256") != descriptor["plan_sha256"]
                or metadata.get("aame_attempt_ref") != current["attempt_ref"]
                or session.get("object") != "checkout.session"
                or session.get("client_reference_id") != order_ref
                or session.get("livemode") is not live
                or session.get("mode") != descriptor["mode"]
                or session.get("currency") != descriptor["currency"]
                or type(session.get("amount_total")) is not int
                or session["amount_total"] != descriptor["amount_cents"]):
            raise ValueError("session does not match reserved checkout descriptor")
        if current["session_id"] not in (None, session_id):
            raise ValueError("order already bound to another session")
        if current["intent_id"] is not None and intent not in (None, current["intent_id"]):
            raise ValueError("order already bound to another payment intent")
        try:
            connection.execute(
                """UPDATE pilot_checkout_binding SET session_id=?,
                   intent_id=COALESCE(intent_id,?) WHERE order_ref=?""",
                (session_id, intent, order_ref))
        except sqlite3.IntegrityError as exc:
            raise ValueError("provider session or intent already bound to another order") from exc
        return _read(connection, order_ref, descriptor)
