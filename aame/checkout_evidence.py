"""Offline first-order payment evidence binding.

Inputs must come from a trusted order store and authenticated provider retrieval,
not a buyer's screenshot, redirect query string, or arbitrary webhook payload.
This module neither authenticates the transport nor posts ledger events.
"""
from dataclasses import dataclass
from collections.abc import Mapping


def _ref(value):
    return isinstance(value, str) and bool(value.strip())


def _cents(value):
    return type(value) is int and 0 < value <= 100000000


@dataclass(frozen=True)
class ExpectedCheckout:
    order_ref: str
    session_id: str
    account_ref: str
    amount_cents: int
    live: bool

    def __post_init__(self):
        if not all(_ref(v) for v in (self.order_ref, self.session_id, self.account_ref)):
            raise ValueError("order, session and account bindings required")
        if not _cents(self.amount_cents) or type(self.live) is not bool:
            raise ValueError("invalid expected amount or environment")


def inspect_checkout(expected, session, *, retrieved_account_ref):
    """Classify a fresh authenticated Stripe Checkout Session.

    retrieved_account_ref comes from the trusted transport's authenticated
    account context, never from the Session's customer-controlled metadata.
    Payment confirmation is not delivery acceptance or bank-cleared cash.
    Refund/dispute state must be independently reconciled before fulfillment.
    """
    if not isinstance(expected, ExpectedCheckout) or not isinstance(session, Mapping):
        raise ValueError("expected order and session required")
    if retrieved_account_ref != expected.account_ref:
        raise ValueError("merchant account mismatch")
    if (session.get("object") != "checkout.session"
            or session.get("id") != expected.session_id
            or session.get("client_reference_id") != expected.order_ref
            or session.get("livemode") is not expected.live
            or session.get("mode") != "payment"
            or session.get("currency") != "usd"
            or not _cents(session.get("amount_total"))
            or session["amount_total"] != expected.amount_cents):
        raise ValueError("checkout binding mismatch")
    status = session.get("status")
    paid = session.get("payment_status")
    if status not in ("open", "complete", "expired") or paid not in (
            "paid", "unpaid", "no_payment_required"):
        raise ValueError("unknown checkout state")
    intent = session.get("payment_intent")
    if paid == "paid":
        if status != "complete" or not _ref(intent):
            raise ValueError("inconsistent payment evidence")
        state = "provider_payment_reported" if expected.live else "test_payment_reported"
    elif paid == "no_payment_required":
        raise ValueError("nonzero paid pilot cannot be free")
    else:
        state = "expired_unpaid" if status == "expired" else "awaiting_payment"
    return {"order_ref": expected.order_ref, "session_id": expected.session_id,
            "payment_intent": intent if paid == "paid" else None,
            "state": state, "cash_verified": False, "earned_revenue": False,
            "fulfillment_authorized": False, "live_enabled": False}
