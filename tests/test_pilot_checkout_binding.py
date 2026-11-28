"""Offline checkout binding regressions. No network, real customer or payment."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from aame.pilot_preflight import _open, _canonical, _digest
from aame.pilot_checkout_binding import reserve_binding, bind_session


class PilotCheckoutBindingTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.db = Path(scratch.name) / "private.sqlite"
        for ref in ("order-a", "order-b", "order-c"):
            plan = {"schema": 1, "order_ref": ref, "currency": "usd",
                    "count": 3, "amount_cents": 7500, "windows": [[0,20000],
                    [20000,40000],[40000,60000]]}
            payload = _canonical(plan)
            with closing(_open(self.db)) as con, con:
                con.execute("INSERT INTO pilot_preflight VALUES(?,?,?)",
                            (ref, payload, _digest(payload)))

    def reserve(self, ref="order-a", account="fixture-account", live=False):
        return reserve_binding(self.db, ref, account_ref=account, live=live)

    def session(self, ref="order-a", session_id="cs_fixture", intent="pi_fixture",
                account="fixture-account", live=False):
        reserved = self.reserve(ref, account, live)
        return {"object": "checkout.session", "id": session_id,
                "payment_intent": intent, "client_reference_id": ref,
                "livemode": live, "mode": "payment", "currency": "usd",
                "amount_total": 7500, "metadata": {
                    "aame_plan_sha256": reserved["descriptor"]["plan_sha256"],
                    "aame_attempt_ref": reserved["attempt_ref"]}}

    def bind(self, session, ref="order-a", account="fixture-account", live=False):
        return bind_session(self.db, ref, session,
                            retrieved_account_ref=account, live=live)

    def test_restart_and_concurrent_reservation(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: self.reserve(), range(8)))
        self.assertTrue(all(row == rows[0] for row in rows))
        self.assertEqual(self.reserve(), rows[0])
        for key in ("checkout_authorized", "fulfillment_authorized",
                    "live_enabled", "cash_verified"):
            self.assertFalse(rows[0][key])

    def test_account_environment_cannot_change(self):
        self.reserve()
        with self.assertRaises(ValueError):
            self.reserve(account="another-account")
        with self.assertRaises(ValueError):
            self.reserve(live=True)

    def test_same_amount_wrong_plan_or_attempt(self):
        for key in ("aame_plan_sha256", "aame_attempt_ref"):
            session = self.session()
            session["metadata"][key] = "wrong"
            with self.assertRaises(ValueError):
                self.bind(session)
        self.assertIsNone(self.reserve()["session_id"])

    def test_duplicate_and_out_of_order_observation(self):
        session = self.session(intent=None)
        self.bind(session)
        session["payment_intent"] = "pi_fixture"
        self.assertEqual(self.bind(session), self.bind(session))
        session["payment_intent"] = None
        self.assertEqual(self.bind(session)["intent_id"], "pi_fixture")
        session["payment_intent"] = "pi_other"
        with self.assertRaises(ValueError):
            self.bind(session)
        with self.assertRaises(ValueError):
            self.bind(self.session(session_id="cs_other"))

    def test_cross_order_session_and_intent_reuse(self):
        self.bind(self.session())
        with self.assertRaises(ValueError):
            self.bind(self.session("order-b", intent="pi_other"), "order-b")
        with self.assertRaises(ValueError):
            self.bind(self.session("order-b", session_id="cs_other"), "order-b")
        self.assertIsNone(self.reserve("order-b")["session_id"])
        self.assertIsNone(self.reserve("order-b")["intent_id"])

    def test_authenticated_context_and_amount(self):
        session = self.session()
        with self.assertRaises(ValueError):
            self.bind(session, account="other")
        with self.assertRaises(ValueError):
            self.bind(session, live=True)
        session["amount_total"] = 2500
        with self.assertRaises(ValueError):
            self.bind(session)

    def test_lost_response_reconciliation_never_creates_new_attempt(self):
        first = self.reserve()
        # Simulated process restart before persisting a provider response.
        recovered = self.reserve()
        self.assertEqual(first, recovered)
        session = self.session()
        result = self.bind(session)
        self.assertEqual(result["attempt_ref"], first["attempt_ref"])
        self.assertEqual(result["session_id"], "cs_fixture")
        self.assertFalse(result["fulfillment_authorized"])
        self.assertFalse(result["cash_verified"])

    def test_requires_preflight_and_reservation(self):
        session = self.session()
        with self.assertRaises(ValueError):
            self.reserve("missing")
        with self.assertRaises(ValueError):
            self.bind(session, "order-c")

    def test_provider_identity_scoped_to_account_and_environment(self):
        self.bind(self.session())
        self.bind(self.session("order-b", account="other"), "order-b", account="other")
        self.bind(self.session("order-c", live=True), "order-c", live=True)
