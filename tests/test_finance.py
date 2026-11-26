from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aame.finance import FinanceError, FinanceLedger


LAUNCH = datetime(2026, 11, 26, tzinfo=timezone.utc)


class FinanceLedgerTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.sqlite"
        self.ledger = FinanceLedger(self.path, launch_at=LAUNCH)

    def authorize(self, *, monthly=5_000, reference="owner-1", now=LAUNCH):
        self.ledger.authorize_limits(
            initial_cents=5_000, first_week_cents=3_000, monthly_cents=monthly,
            approval_ref=reference, now=now,
        )

    def test_default_denies_paid_work_and_mock_reservations_replay(self):
        with self.assertRaisesRegex(FinanceError, "initial risk"):
            self.ledger.reserve("paid", 1, now=LAUNCH)
        self.ledger.reserve("free", 0, now=LAUNCH)
        self.ledger.reserve("free", 0, now=LAUNCH)
        self.ledger.resolve("free", expense_cents=0, now=LAUNCH, evidence="complete")
        self.ledger.resolve("free", expense_cents=0, now=LAUNCH, evidence="complete")
        with self.assertRaisesRegex(FinanceError, "different amount"):
            self.ledger.reserve("free", 1, now=LAUNCH)

    def test_concurrent_reservations_cannot_breach_week_one_limit(self):
        self.authorize()

        def attempt(index):
            try:
                self.ledger.reserve(f"job-{index}", 500, now=LAUNCH)
            except FinanceError as error:
                return str(error)
            return "accepted"

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(results.count("accepted"), 6)
        self.assertEqual(results.count("first-week limit exceeded"), 6)
        self.assertEqual(self.ledger.report(now=LAUNCH)["reserved_cents"], 3_000)

    def test_unresolved_reservation_carries_into_new_month_and_reopen(self):
        self.authorize(monthly=2_000)
        self.ledger.reserve("november", 1_500, now=LAUNCH)
        now = LAUNCH + timedelta(days=35)
        reopened = FinanceLedger(self.path, launch_at=LAUNCH)
        with self.assertRaisesRegex(FinanceError, "monthly limit"):
            reopened.reserve("later", 501, now=now)
        reopened.reserve("later", 500, now=now)
        self.assertEqual(reopened.report(now=now)["monthly_exposure_cents"], 2_000)
        with self.assertRaisesRegex(FinanceError, "launch date conflicts"):
            FinanceLedger(self.path, launch_at=now)

    def test_clearing_old_reservation_does_not_release_current_month_expense(self):
        self.authorize(monthly=2_000)
        self.ledger.reserve("old", 1_500, now=LAUNCH)
        now = LAUNCH + timedelta(days=35)
        self.ledger.resolve("old", expense_cents=1_500, now=now, evidence="invoice")
        with self.assertRaisesRegex(FinanceError, "monthly limit"):
            self.ledger.reserve("new", 501, now=now)

    def test_same_bank_evidence_cannot_increment_cash_under_new_key(self):
        self.ledger.record_event("first", "cash", 1_000, now=LAUNCH, evidence="bank-1")
        with self.assertRaisesRegex(FinanceError, "already recorded"):
            self.ledger.record_event("second", "cash", 1_000, now=LAUNCH, evidence="bank-1")
        self.assertEqual(self.ledger.report(now=LAUNCH)["received_cash_cents"], 1_000)

    def test_first_week_and_initial_risk_use_confirmed_expense_and_open_holds(self):
        self.authorize(monthly=6_000)
        self.ledger.reserve("a", 3_000, now=LAUNCH)
        with self.assertRaisesRegex(FinanceError, "exceeds the reservation"):
            self.ledger.resolve("a", expense_cents=3_001, now=LAUNCH, evidence="invoice")
        self.ledger.resolve("a", expense_cents=2_400, now=LAUNCH, evidence="invoice")
        self.ledger.reserve("b", 600, now=LAUNCH)
        next_week = LAUNCH + timedelta(days=7)
        self.ledger.reserve("next-week", 2_000, now=next_week)
        with self.assertRaisesRegex(FinanceError, "initial risk"):
            self.ledger.reserve("extra", 1, now=next_week)
        report = self.ledger.report(now=next_week)
        self.assertEqual(report["first_week_exposure_cents"], 3_000)
        self.assertEqual(report["peak_risk_cents"], 5_000)

    def test_accounting_distinguishes_accrual_approval_and_cash_and_replays(self):
        self.authorize()
        self.ledger.reserve("work", 400, now=LAUNCH)
        self.ledger.resolve("work", expense_cents=300, now=LAUNCH,
                            evidence="invoice", paid=False)
        for event in (("estimate", 2_000), ("approval", 1_800), ("cash", 1_500)):
            kind, cents = event
            for _ in range(2):
                self.ledger.record_event(kind, kind, cents, now=LAUNCH, evidence="statement")
        report = self.ledger.report(now=LAUNCH)
        self.assertEqual(report["estimated_cents"], 2_000)
        self.assertEqual(report["approved_cents"], 1_800)
        self.assertEqual(report["received_cash_cents"], 1_500)
        self.assertEqual(report["expenses_cents"], 300)
        self.assertEqual(report["cash_paid_cents"], 0)
        self.assertEqual(report["outstanding_cents"], 300)
        self.ledger.pay_expense("work", now=LAUNCH, evidence="bank")
        self.ledger.pay_expense("work", now=LAUNCH, evidence="bank")
        report = self.ledger.report(now=LAUNCH)
        self.assertEqual(report["net_cash_cents"], 1_200)
        self.assertEqual(report["outstanding_cents"], 0)
        with self.assertRaisesRegex(FinanceError, "different payload"):
            self.ledger.record_event("cash", "cash", 1_501, now=LAUNCH, evidence="bank")

    def test_full_monthly_unlock_needs_cash_coverage_and_new_approval_after_reversal(self):
        self.authorize()
        self.ledger.reserve("work", 200, now=LAUNCH)
        with self.assertRaisesRegex(FinanceError, "cash break-even"):
            self.authorize(monthly=30_000, reference="unlock")
        self.ledger.record_event("cash", "cash", 100, now=LAUNCH, evidence="bank")
        with self.assertRaisesRegex(FinanceError, "coverage"):
            self.authorize(monthly=30_000, reference="unlock")
        self.ledger.resolve("work", expense_cents=100, now=LAUNCH, evidence="invoice")
        self.authorize(monthly=30_000, reference="unlock")
        self.ledger.record_event("refund", "reversal", 100, now=LAUNCH,
                                 evidence="bank-reversal", reverses="cash")
        self.assertTrue(self.ledger.report(now=LAUNCH)["paid_work_frozen"])
        with self.assertRaisesRegex(FinanceError, "exceeds remaining"):
            self.ledger.record_event("extra", "reversal", 1, now=LAUNCH,
                                     evidence="another-reversal", reverses="cash")
        self.ledger.record_event("recovery", "cash", 100, now=LAUNCH, evidence="new-bank")
        self.authorize(monthly=30_000, reference="unlock")
        with self.assertRaisesRegex(FinanceError, "frozen"):
            self.ledger.reserve("new", 1, now=LAUNCH)
        self.authorize(monthly=30_000, reference="new-unlock")
        self.ledger.reserve("new", 1, now=LAUNCH)

    def test_rejects_limit_increases_above_hard_ceilings(self):
        for fields in (
            {"initial_cents": 5_001},
            {"first_week_cents": 3_001},
            {"monthly_cents": 30_001},
            {"monthly_cents": True},
        ):
            with self.subTest(fields=fields):
                limits = dict(initial_cents=5_000, first_week_cents=3_000, monthly_cents=5_000)
                limits.update(fields)
                with self.assertRaises(FinanceError):
                    self.ledger.authorize_limits(**limits, approval_ref="owner", now=LAUNCH)


if __name__ == "__main__":
    unittest.main()
