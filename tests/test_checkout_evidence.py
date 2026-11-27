import unittest
from aame.checkout_evidence import ExpectedCheckout, inspect_checkout


class CheckoutEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.expected = ExpectedCheckout("fixture_order", "fixture_session",
                                         "fixture_merchant", 7500, True)
        self.session = dict(object="checkout.session", id="fixture_session",
                            client_reference_id="fixture_order", livemode=True,
                            mode="payment", currency="usd", amount_total=7500,
                            status="complete", payment_status="paid",
                            payment_intent="fixture_intent")

    def inspect(self, **changes):
        return inspect_checkout(self.expected, dict(self.session, **changes),
                                retrieved_account_ref="fixture_merchant")

    def test_paid_is_not_cash_or_permission(self):
        result = self.inspect()
        self.assertEqual(result["state"], "provider_payment_reported")
        for flag in ("cash_verified", "earned_revenue", "fulfillment_authorized", "live_enabled"):
            self.assertIs(result[flag], False)

    def test_delayed_payment(self):
        self.assertEqual(self.inspect(payment_status="unpaid")["state"], "awaiting_payment")

    def test_expired(self):
        self.assertEqual(self.inspect(status="expired", payment_status="unpaid")["state"],
                         "expired_unpaid")

    def test_wrong_binding(self):
        for changes in (dict(id="other"), dict(client_reference_id="other"),
                        dict(amount_total=7499), dict(amount_total=7500.0),
                        dict(currency="eur"), dict(mode="subscription"),
                        dict(livemode=False), dict(object="payment_intent")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.inspect(**changes)

    def test_wrong_account(self):
        with self.assertRaises(ValueError):
            inspect_checkout(self.expected, self.session, retrieved_account_ref="other")

    def test_inconsistent_state(self):
        for changes in (dict(status="open"), dict(payment_intent=None),
                        dict(payment_status="no_payment_required"),
                        dict(status="unknown")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.inspect(**changes)

    def test_test_mode_never_live(self):
        expected = ExpectedCheckout("fixture_order", "fixture_session",
                                    "fixture_merchant", 7500, False)
        result = inspect_checkout(expected, dict(self.session, livemode=False),
                                  retrieved_account_ref="fixture_merchant")
        self.assertEqual(result["state"], "test_payment_reported")
        self.assertFalse(result["cash_verified"])

    def test_invalid_quote(self):
        for amount in (0, -1, True, 7500.0):
            with self.assertRaises(ValueError):
                ExpectedCheckout("order", "session", "merchant", amount, True)
