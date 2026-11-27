from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import unittest

from aame.analytics import (
    CashOutcome,
    EvaluationRow,
    PeerObservation,
    assign_treatment,
    detect_outlier,
    intent_to_treat,
    partition_evaluation,
)


NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)
COHORT = ("youtube", "en", "games", "small", "engaged_views")


def observation(post_id, views, *, age=24, offset=0):
    observed_at = NOW - timedelta(hours=offset)
    return PeerObservation(post_id, COHORT, observed_at - timedelta(hours=age),
                           observed_at, views)


class OutlierTest(unittest.TestCase):
    def test_detects_seeded_spike_against_matched_distinct_peers(self):
        peers = [observation(f"peer-{index}", 100 + index * 4) for index in range(20)]
        peers.extend([
            peers[0],
            observation("future", 100_000, offset=-1),
            observation("old", 100_000, offset=60),
            observation("wrong-age", 100_000, age=12),
            replace(observation("wrong-metric", 100_000),
                    cohort=(*COHORT[:-1], "public_views")),
            observation("target", 2),
        ])
        detected = detect_outlier(observation("target", 10_000), peers)
        self.assertEqual(detected.peer_count, 20)
        self.assertGreater(detected.robust_z, 3.5)
        self.assertTrue(detected.flagged)
        self.assertFalse(detect_outlier(observation("target", 135), peers).flagged)

    def test_suppresses_missing_small_and_zero_dispersion_cohorts(self):
        target = observation("target", 10_000)
        self.assertIsNone(detect_outlier(replace(target, views=None), []).flagged)
        self.assertIsNone(detect_outlier(target, [observation("peer", 50)] * 30).flagged)
        peers = [observation(f"peer-{index}", 100) for index in range(20)]
        self.assertIsNone(detect_outlier(target, peers).flagged)

    def test_excludes_conflicting_snapshots_and_does_not_use_stale_count(self):
        peers = [observation(f"peer-{index}", 100 + index) for index in range(19)]
        peers.extend([observation("conflict", 100), observation("conflict", 200)])
        peers.extend([observation("missing", 100, offset=1), observation("missing", None)])
        detected = detect_outlier(observation("target", 10_000), peers)
        self.assertEqual(detected.peer_count, 19)
        self.assertIsNone(detected.flagged)


class ExperimentTest(unittest.TestCase):
    def setUp(self):
        assignments = [assign_treatment("fixture", str(index), "creator-day")
                       for index in range(64)]
        self.control = next(row for row in assignments if row.arm == "control")
        treatments = [row for row in assignments if row.arm == "treatment"]
        self.treatment, self.rejected = treatments[:2]
        self.assignments = [self.control, self.treatment, self.rejected]

    def test_reproducible_propensity(self):
        row = self.treatment
        self.assertEqual(row, assign_treatment(row.experiment_id, row.source_unit_id, row.block))
        self.assertEqual(row.propensity, Fraction(1, 2))

    def test_retains_rejected_assignments_and_their_cost(self):
        outcomes = [
            CashOutcome(self.control.source_unit_id, 50, 10, True),
            CashOutcome(self.treatment.source_unit_id, 200, 10, True),
            CashOutcome(self.rejected.source_unit_id, 0, 30, True),
        ]
        report = intent_to_treat(self.assignments, outcomes)
        self.assertEqual(report.treatment.assigned, 2)
        self.assertEqual(report.treatment.expense_cents, 40)
        self.assertEqual(report.incremental_net_per_assignment_cents, 40)

    def test_missing_outcome_keeps_denominator_and_withholds_lift(self):
        outcomes = [
            CashOutcome(self.control.source_unit_id, 50, 10, True),
            CashOutcome(self.treatment.source_unit_id, 200, 10, False),
        ]
        report = intent_to_treat(self.assignments, outcomes)
        self.assertEqual(report.treatment.assigned, 2)
        self.assertEqual(report.treatment.finalized, 0)
        self.assertIsNone(report.incremental_net_per_assignment_cents)

    def test_rejects_duplicate_and_tampered_assignments(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            intent_to_treat([self.treatment, self.treatment], [])
        with self.assertRaisesRegex(ValueError, "allocation"):
            intent_to_treat([replace(self.treatment, propensity=Fraction(1, 3))], [])
        with self.assertRaisesRegex(ValueError, "unassigned"):
            intent_to_treat([self.control], [CashOutcome("unknown", 0, 1, True)])


def evaluation_row(asset, creator, days, *, label_lag=1):
    decision_at = NOW + timedelta(days=days)
    return EvaluationRow(asset, creator, decision_at, decision_at,
                         decision_at + timedelta(days=label_lag))


class EvaluationTest(unittest.TestCase):
    def split(self, rows):
        return partition_evaluation(
            rows,
            calibration_at=NOW + timedelta(days=10),
            test_at=NOW + timedelta(days=20),
            evaluated_at=NOW + timedelta(days=30),
            embargo=timedelta(days=2),
            held_out_creators={"held"},
        )

    def test_enforces_embargo_as_of_and_creator_holdout(self):
        train = evaluation_row("train", "seen", 1)
        calibration = evaluation_row("calibration", "seen", 10)
        test = evaluation_row("test", "seen", 20)
        held = evaluation_row("held-out", "held", 21)
        partitions = self.split([
            held, test, calibration, train,
            evaluation_row("too-recent", "seen", 30),
            evaluation_row("train-label-leakage", "seen", 6, label_lag=4),
            evaluation_row("embargo", "seen", 19),
            evaluation_row("early-held-out", "held", 1),
        ])
        self.assertEqual(partitions.train, (train,))
        self.assertEqual(partitions.calibration, (calibration,))
        self.assertEqual(partitions.test, (test,))
        self.assertEqual(partitions.unseen_creators, (held,))

    def test_rejects_asset_leakage_and_future_features(self):
        with self.assertRaisesRegex(ValueError, "source group crosses"):
            self.split([evaluation_row("same", "seen", 1), evaluation_row("same", "held", 20)])
        row = evaluation_row("future-feature", "seen", 1)
        with self.assertRaisesRegex(ValueError, "out of order"):
            self.split([replace(row, feature_as_of=row.label_observed_at)])


if __name__ == "__main__":
    unittest.main()
