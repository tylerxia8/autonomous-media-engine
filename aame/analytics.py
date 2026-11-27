"""Offline analytics for reviewed, authorized metadata and experiment records."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from hashlib import sha256
import json
from math import log1p
from statistics import median
from typing import Literal


@dataclass(frozen=True)
class PeerObservation:
    post_id: str
    # Platform, language, niche, account scale, and metric definition.
    cohort: tuple[str, str, str, str, str]
    posted_at: datetime
    observed_at: datetime
    views: int | None


@dataclass(frozen=True)
class Outlier:
    peer_count: int
    robust_z: float | None
    flagged: bool | None


def _aware(instant: datetime) -> bool:
    return instant.utcoffset() is not None


def _velocity(observation: PeerObservation) -> tuple[float, float] | None:
    if not (_aware(observation.observed_at) and _aware(observation.posted_at)):
        return None
    hours = (observation.observed_at - observation.posted_at).total_seconds() / 3600
    views = observation.views
    if hours <= 0 or type(views) is not int or not 0 <= views <= 2**63 - 1:
        return None
    return hours, log1p(views / hours)


def detect_outlier(
    target: PeerObservation,
    peers: list[PeerObservation],
    *,
    minimum_peers: int = 20,
    freshness: timedelta = timedelta(hours=48),
) -> Outlier:
    """Use recent same-cohort observations within 20% of the target's age."""
    if minimum_peers < 3 or freshness <= timedelta(0):
        raise ValueError("invalid peer baseline settings")
    target_velocity = _velocity(target)
    if target_velocity is None:
        return Outlier(0, None, None)

    target_age, target_score = target_velocity
    latest: dict[str, PeerObservation] = {}
    conflicting: set[str] = set()
    for peer in peers:
        if not peer.post_id or peer.post_id == target.post_id or peer.cohort != target.cohort:
            continue
        if not _aware(peer.observed_at):
            continue
        delta = target.observed_at - peer.observed_at
        if not timedelta(0) <= delta <= freshness:
            continue
        previous = latest.get(peer.post_id)
        if previous is None or previous.observed_at < peer.observed_at:
            latest[peer.post_id] = peer
            conflicting.discard(peer.post_id)
        elif previous.observed_at == peer.observed_at and previous != peer:
            conflicting.add(peer.post_id)

    scores = []
    for post_id, peer in latest.items():
        if post_id in conflicting:
            continue
        velocity = _velocity(peer)
        if velocity is not None and abs(velocity[0] - target_age) <= target_age * 0.2:
            scores.append(velocity[1])

    if len(scores) < minimum_peers:
        return Outlier(len(scores), None, None)
    center = median(scores)
    deviation = median(abs(score - center) for score in scores)
    if deviation == 0:
        return Outlier(len(scores), None, None)
    z_score = 0.6744897501960817 * (target_score - center) / deviation
    return Outlier(len(scores), z_score, z_score >= 3.5)


Arm = Literal["control", "treatment"]


@dataclass(frozen=True)
class Assignment:
    experiment_id: str
    source_unit_id: str
    block: str
    arm: Arm
    propensity: Fraction


def assign_treatment(experiment_id: str, source_unit_id: str, block: str) -> Assignment:
    """Assign once per fixed source unit and block, with a one-half propensity."""
    if not all(value.strip() for value in (experiment_id, source_unit_id, block)):
        raise ValueError("assignment identifiers must be nonempty")
    payload = json.dumps(["aame-assignment-v1", experiment_id, source_unit_id, block])
    arm = "treatment" if sha256(payload.encode()).digest()[0] < 128 else "control"
    return Assignment(experiment_id, source_unit_id, block, arm, Fraction(1, 2))


@dataclass(frozen=True)
class CashOutcome:
    source_unit_id: str
    received_cash_cents: int
    expense_cents: int
    finalized: bool


@dataclass(frozen=True)
class ArmCash:
    assigned: int
    finalized: int
    received_cash_cents: int
    expense_cents: int
    finalized_net_per_assignment_cents: Fraction | None


@dataclass(frozen=True)
class ExperimentCash:
    control: ArmCash
    treatment: ArmCash
    incremental_net_per_assignment_cents: Fraction | None


def intent_to_treat(assignments: list[Assignment], outcomes: list[CashOutcome]) -> ExperimentCash:
    """Include every assignment and withhold lift until each outcome is final."""
    if len({assignment.experiment_id for assignment in assignments}) > 1:
        raise ValueError("report one experiment at a time")
    assigned = {assignment.source_unit_id: assignment for assignment in assignments}
    if len(assigned) != len(assignments):
        raise ValueError("duplicate source unit assignment")
    for assignment in assignments:
        if assignment != assign_treatment(
            assignment.experiment_id, assignment.source_unit_id, assignment.block
        ):
            raise ValueError("assignment does not match the experiment allocation")
    observed = {}
    for outcome in outcomes:
        unit = outcome.source_unit_id
        if unit not in assigned or unit in observed:
            raise ValueError("unassigned or duplicate cash outcome")
        if (
            type(outcome.received_cash_cents) is not int
            or type(outcome.expense_cents) is not int
            or outcome.expense_cents < 0
            or type(outcome.finalized) is not bool
        ):
            raise ValueError("cash outcome requires integer cents and a finalized flag")
        observed[unit] = outcome

    def summarize(arm: Arm) -> ArmCash:
        units = [unit for unit, assignment in assigned.items() if assignment.arm == arm]
        records = [observed[unit] for unit in units if unit in observed]
        finalized = sum(record.finalized for record in records)
        cash = sum(record.received_cash_cents for record in records)
        expense = sum(record.expense_cents for record in records)
        mean = Fraction(cash - expense, len(units)) if units and finalized == len(units) else None
        return ArmCash(len(units), finalized, cash, expense, mean)

    control = summarize("control")
    treatment = summarize("treatment")
    control_mean = control.finalized_net_per_assignment_cents
    treatment_mean = treatment.finalized_net_per_assignment_cents
    lift = treatment_mean - control_mean if control_mean is not None and treatment_mean is not None else None
    return ExperimentCash(control, treatment, lift)


@dataclass(frozen=True)
class EvaluationRow:
    source_group_id: str
    creator_id: str
    decision_at: datetime
    feature_as_of: datetime
    label_observed_at: datetime


@dataclass(frozen=True)
class EvaluationPartitions:
    train: tuple[EvaluationRow, ...]
    calibration: tuple[EvaluationRow, ...]
    test: tuple[EvaluationRow, ...]
    unseen_creators: tuple[EvaluationRow, ...]


def partition_evaluation(
    rows: list[EvaluationRow],
    *,
    calibration_at: datetime,
    test_at: datetime,
    evaluated_at: datetime,
    embargo: timedelta,
    held_out_creators: set[str],
) -> EvaluationPartitions:
    """Split decisions chronologically and enforce source and creator isolation."""
    cutoffs = (calibration_at, test_at, evaluated_at)
    if not all(map(_aware, cutoffs)) or not calibration_at < test_at <= evaluated_at:
        raise ValueError("invalid evaluation cutoffs")
    if not timedelta(0) < embargo < test_at - calibration_at:
        raise ValueError("embargo must be positive and shorter than the calibration window")
    partitions: dict[str, list[EvaluationRow]] = {
        "train": [], "calibration": [], "test": [], "unseen_creators": [],
    }
    source_groups: dict[str, str] = {}
    for row in rows:
        if not row.source_group_id or not row.creator_id:
            raise ValueError("source group and creator are required")
        timestamps = (row.feature_as_of, row.decision_at, row.label_observed_at)
        if not all(map(_aware, timestamps)) or not row.feature_as_of <= row.decision_at < row.label_observed_at:
            raise ValueError("features or labels are out of order")
        if row.label_observed_at > evaluated_at:
            continue
        if row.decision_at >= test_at:
            name = "unseen_creators" if row.creator_id in held_out_creators else "test"
        elif row.creator_id in held_out_creators:
            continue
        elif row.decision_at < calibration_at - embargo and row.label_observed_at < calibration_at:
            name = "train"
        elif calibration_at <= row.decision_at < test_at - embargo and row.label_observed_at < test_at:
            name = "calibration"
        else:
            continue
        if source_groups.setdefault(row.source_group_id, name) != name:
            raise ValueError(f"source group crosses evaluation partitions: {row.source_group_id}")
        partitions[name].append(row)
    return EvaluationPartitions(
        **{name: tuple(sorted(items, key=lambda row: row.decision_at)) for name, items in partitions.items()}
    )
