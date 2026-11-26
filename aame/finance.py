"""Transactional USD budget reservations and cash reconciliation."""

from contextlib import closing, contextmanager
from datetime import datetime, timedelta
import sqlite3


INITIAL_CEILING = 5_000
FIRST_WEEK_CEILING = 3_000
MONTHLY_CEILING = 30_000
ZERO = timedelta(0)


class FinanceError(ValueError):
    """A budget rule or immutable ledger identity rejected the operation."""


def _utc(value: datetime) -> str:
    if value.utcoffset() != ZERO:
        raise FinanceError("ledger timestamps must be UTC")
    return value.isoformat(timespec="microseconds")


def _cents(value: int, *, minimum: int = 0, maximum: int = 10**12) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise FinanceError("invalid USD cent amount")


def _reference(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise FinanceError("nonempty event key and evidence reference required")


class FinanceLedger:
    """File-backed ledger. Callers verify owner and settlement evidence first."""

    def __init__(self, path, *, launch_at: datetime):
        self.path = path
        self.launch = _utc(launch_at)
        self.week_end = _utc(launch_at + timedelta(days=7))
        if str(path) in ("", ":memory:"):
            raise FinanceError("a persistent SQLite path is required")
        with closing(self._connect()) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS budget (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    launch TEXT NOT NULL,
                    initial_cents INTEGER NOT NULL DEFAULT 0,
                    first_week_cents INTEGER NOT NULL DEFAULT 0,
                    monthly_cents INTEGER NOT NULL DEFAULT 0,
                    peak_risk_cents INTEGER NOT NULL DEFAULT 0,
                    frozen INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS budget_approvals (
                    reference TEXT PRIMARY KEY NOT NULL,
                    recorded_at TEXT NOT NULL,
                    initial_cents INTEGER NOT NULL,
                    first_week_cents INTEGER NOT NULL,
                    monthly_cents INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    key TEXT PRIMARY KEY NOT NULL,
                    reserved_at TEXT NOT NULL,
                    reserved_cents INTEGER NOT NULL,
                    expense_cents INTEGER,
                    resolved_at TEXT,
                    resolution_evidence TEXT,
                    resolved_as_paid INTEGER,
                    paid_at TEXT,
                    payment_evidence TEXT
                );
                CREATE TABLE IF NOT EXISTS financial_events (
                    key TEXT PRIMARY KEY NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('estimate', 'approval', 'cash', 'reversal')),
                    cents INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    reverses TEXT REFERENCES financial_events(key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS unique_settlement_evidence
                ON financial_events(kind, evidence) WHERE kind IN ('cash', 'reversal');
            """)
        with self._write() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO budget (singleton, launch) VALUES (1, ?)",
                (self.launch,),
            )
            if self._policy(connection)["launch"] != self.launch:
                raise FinanceError("launch date conflicts with the existing ledger")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _write(self):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def _time(self, now):
        timestamp = _utc(now)
        if timestamp < self.launch:
            raise FinanceError("ledger activity predates launch")
        return timestamp

    @staticmethod
    def _policy(connection):
        return connection.execute("SELECT * FROM budget WHERE singleton = 1").fetchone()

    @staticmethod
    def _totals(connection):
        events = {
            row["kind"]: row["amount"]
            for row in connection.execute("""
                SELECT kind, SUM(cents) AS amount FROM financial_events GROUP BY kind
            """)
        }
        costs = connection.execute("""
            SELECT
                COALESCE(SUM(expense_cents), 0) AS incurred,
                COALESCE(SUM(CASE WHEN paid_at IS NOT NULL THEN expense_cents END), 0) AS paid,
                COALESCE(SUM(CASE WHEN expense_cents IS NULL THEN reserved_cents END), 0) AS reserved
            FROM reservations
        """).fetchone()
        cash = events.get("cash", 0) - events.get("reversal", 0)
        paid = costs["paid"]
        unpaid = costs["incurred"] - paid
        outstanding = costs["reserved"] + unpaid
        return {
            "estimated_cents": events.get("estimate", 0),
            "approved_cents": events.get("approval", 0),
            "received_cash_cents": cash,
            "gross_received_cash_cents": events.get("cash", 0),
            "reversed_cash_cents": events.get("reversal", 0),
            "expenses_cents": costs["incurred"],
            "cash_paid_cents": paid,
            "reserved_cents": costs["reserved"],
            "unpaid_expense_cents": unpaid,
            "outstanding_cents": outstanding,
            "net_cash_cents": cash - paid,
            "capital_at_risk_cents": max(0, paid + outstanding - cash),
            "verified_cash_break_even": cash > 0 and cash >= paid,
        }

    @staticmethod
    def _week_exposure(connection, week_end):
        return connection.execute("""
            SELECT COALESCE(SUM(COALESCE(expense_cents, reserved_cents)), 0)
            FROM reservations WHERE reserved_at < ?
        """, (week_end,)).fetchone()[0]

    @staticmethod
    def _month_exposure(connection, month):
        # Charge open or unpaid exposure and allocations made, incurred, or
        # paid this month. A row contributes at most once in any given month.
        return connection.execute("""
            SELECT COALESCE(SUM(COALESCE(expense_cents, reserved_cents)), 0)
            FROM reservations WHERE substr(reserved_at, 1, 7) = ?
                OR substr(resolved_at, 1, 7) = ? OR substr(paid_at, 1, 7) = ?
                OR paid_at IS NULL
        """, (month, month, month)).fetchone()[0]

    def _update_risk(self, connection):
        totals = self._totals(connection)
        connection.execute("""
            UPDATE budget SET peak_risk_cents = MAX(peak_risk_cents, ?)
            WHERE singleton = 1
        """, (totals["capital_at_risk_cents"],))
        return totals

    def authorize_limits(
        self, *, initial_cents, first_week_cents, monthly_cents, approval_ref, now
    ):
        """Record a verified owner's limit decision. An approval reference is unique."""
        timestamp = self._time(now)
        _reference(approval_ref)
        _cents(initial_cents, maximum=INITIAL_CEILING)
        _cents(first_week_cents, maximum=FIRST_WEEK_CEILING)
        _cents(monthly_cents, maximum=MONTHLY_CEILING)
        amounts = (initial_cents, first_week_cents, monthly_cents)
        with self._write() as connection:
            previous = connection.execute("""
                SELECT initial_cents, first_week_cents, monthly_cents
                FROM budget_approvals WHERE reference = ?
            """, (approval_ref,)).fetchone()
            if previous is not None:
                if tuple(previous) != amounts:
                    raise FinanceError("owner approval reference already used")
                return
            totals = self._totals(connection)
            if monthly_cents == MONTHLY_CEILING and (
                not totals["verified_cash_break_even"]
                or totals["capital_at_risk_cents"] != 0
            ):
                raise FinanceError("full monthly ceiling requires cleared cash break-even and coverage")
            connection.execute("""
                INSERT INTO budget_approvals VALUES (?, ?, ?, ?, ?)
            """, (approval_ref, timestamp, *amounts))
            connection.execute("""
                UPDATE budget SET initial_cents = ?, first_week_cents = ?,
                    monthly_cents = ?, frozen = 0 WHERE singleton = 1
            """, amounts)

    def reserve(self, key, cents, *, now):
        """Commit the bounded worst-case cost atomically. Holds do not expire."""
        timestamp = self._time(now)
        _reference(key)
        _cents(cents)
        with self._write() as connection:
            previous = connection.execute(
                "SELECT reserved_cents FROM reservations WHERE key = ?", (key,),
            ).fetchone()
            if previous is not None:
                if previous["reserved_cents"] != cents:
                    raise FinanceError("reservation key already used for a different amount")
                return

            policy = self._policy(connection)
            totals = self._totals(connection)
            if cents:
                if policy["frozen"]:
                    raise FinanceError("paid work frozen pending owner approval")
                if not totals["verified_cash_break_even"]:
                    risk = totals["capital_at_risk_cents"]
                    if risk + cents > policy["initial_cents"]:
                        raise FinanceError("initial risk limit exceeded")
                if timestamp < self.week_end:
                    week = self._week_exposure(connection, self.week_end)
                    if week + cents > policy["first_week_cents"]:
                        raise FinanceError("first-week limit exceeded")
                month = self._month_exposure(connection, timestamp[:7])
                if month + cents > policy["monthly_cents"]:
                    raise FinanceError("monthly limit exceeded")

            connection.execute("""
                INSERT INTO reservations (key, reserved_at, reserved_cents) VALUES (?, ?, ?)
            """, (key, timestamp, cents))
            self._update_risk(connection)

    def resolve(self, key, *, expense_cents, now, evidence, paid=True):
        """Replace a hold with confirmed expense and release only the unused portion."""
        timestamp = self._time(now)
        _cents(expense_cents)
        _reference(evidence)
        if type(paid) is not bool:
            raise FinanceError("paid must be a boolean")
        with self._write() as connection:
            previous = self._reservation(connection, key, timestamp)
            if previous["expense_cents"] is not None:
                if (
                    previous["expense_cents"] != expense_cents
                    or previous["resolution_evidence"] != evidence
                    or previous["resolved_as_paid"] != paid
                ):
                    raise FinanceError("reservation already resolved with different evidence")
                return
            if expense_cents > previous["reserved_cents"]:
                raise FinanceError("confirmed expense exceeds the reservation")
            before = self._totals(connection)
            connection.execute("""
                UPDATE reservations SET expense_cents = ?, resolved_at = ?,
                    resolution_evidence = ?, resolved_as_paid = ?, paid_at = ?,
                    payment_evidence = ? WHERE key = ?
            """, (
                expense_cents, timestamp, evidence, paid, timestamp if paid else None,
                evidence if paid else None, key,
            ))
            self._handle_break_even_loss(connection, before)

    def pay_expense(self, key, *, now, evidence):
        """Match previously accrued expense against cleared cash payment evidence."""
        timestamp = self._time(now)
        _reference(evidence)
        with self._write() as connection:
            previous = self._reservation(connection, key, timestamp)
            if previous["resolved_at"] is None or timestamp < previous["resolved_at"]:
                raise FinanceError("payment requires a previously confirmed expense")
            if previous["paid_at"] is not None:
                if previous["payment_evidence"] != evidence:
                    raise FinanceError("expense is already paid with different evidence")
                return
            before = self._totals(connection)
            connection.execute("""
                UPDATE reservations SET paid_at = ?, payment_evidence = ? WHERE key = ?
            """, (timestamp, evidence, key))
            self._handle_break_even_loss(connection, before)

    @staticmethod
    def _reservation(connection, key, timestamp):
        previous = connection.execute(
            "SELECT * FROM reservations WHERE key = ?", (key,),
        ).fetchone()
        if previous is None or timestamp < previous["reserved_at"]:
            raise FinanceError("resolution requires an existing reservation")
        return previous

    def record_event(self, key, kind, cents, *, now, evidence, reverses=None):
        """Record one immutable external estimate, approval, receipt or linked reversal."""
        timestamp = self._time(now)
        _reference(key)
        _reference(evidence)
        _cents(cents, minimum=1 if kind in ("cash", "reversal") else 0)
        if kind not in ("estimate", "approval", "cash", "reversal"):
            raise FinanceError("unknown ledger event kind")
        if kind == "reversal":
            _reference(reverses)
        elif reverses is not None:
            raise FinanceError("only reversals can link to a receipt")

        with self._write() as connection:
            previous = connection.execute("""
                SELECT kind, cents, evidence, reverses FROM financial_events WHERE key = ?
            """, (key,)).fetchone()
            if previous is not None:
                if tuple(previous) != (kind, cents, evidence, reverses):
                    raise FinanceError("event key already used with a different payload")
                return
            if kind in ("cash", "reversal") and connection.execute(
                "SELECT 1 FROM financial_events WHERE kind = ? AND evidence = ?",
                (kind, evidence),
            ).fetchone():
                raise FinanceError("settlement evidence already recorded under a different key")
            before = self._totals(connection)
            if kind == "reversal":
                self._check_reversal(connection, reverses, cents, timestamp)
            connection.execute("""
                INSERT INTO financial_events VALUES (?, ?, ?, ?, ?, ?)
            """, (key, kind, cents, timestamp, evidence, reverses))
            self._handle_break_even_loss(connection, before)

    @staticmethod
    def _check_reversal(connection, key, cents, timestamp):
        receipt = connection.execute("""
            SELECT cents, recorded_at FROM financial_events WHERE key = ? AND kind = 'cash'
        """, (key,)).fetchone()
        if receipt is None or timestamp < receipt["recorded_at"]:
            raise FinanceError("reversal requires an earlier cleared receipt")
        reversed_cents = connection.execute("""
            SELECT COALESCE(SUM(cents), 0) FROM financial_events WHERE reverses = ?
        """, (key,)).fetchone()[0]
        if reversed_cents + cents > receipt["cents"]:
            raise FinanceError("reversal exceeds remaining cleared receipt")

    def _handle_break_even_loss(self, connection, before):
        after = self._update_risk(connection)
        if before["verified_cash_break_even"] and not after["verified_cash_break_even"]:
            if self._policy(connection)["monthly_cents"] == MONTHLY_CEILING:
                connection.execute("UPDATE budget SET frozen = 1 WHERE singleton = 1")

    def trailing_week(self, *, now):
        """Return the seven-day window of incurred and cleared activity."""
        end = self._time(now)
        start = _utc(now - timedelta(days=7))
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            events = {
                row["kind"]: row["cents"]
                for row in connection.execute("""
                    SELECT kind, SUM(cents) AS cents FROM financial_events
                    WHERE ? < recorded_at AND recorded_at <= ? GROUP BY kind
                """, (start, end))
            }
            expense, paid = connection.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN ? < resolved_at AND resolved_at <= ?
                        THEN expense_cents END), 0),
                    COALESCE(SUM(CASE WHEN ? < paid_at AND paid_at <= ?
                        THEN expense_cents END), 0)
                FROM reservations
            """, (start, end, start, end)).fetchone()
        cash = events.get("cash", 0) - events.get("reversal", 0)
        net = cash - paid
        return {
            "start_exclusive": start,
            "end_inclusive": end,
            "estimated_cents": events.get("estimate", 0),
            "approved_cents": events.get("approval", 0),
            "received_cash_cents": cash,
            "expenses_cents": expense,
            "net_cash_cents": net,
            "net_cash_per_day_cents_floor": net // 7,
            "daily_target_cents": 1_000,
            "meets_daily_cash_target": net >= 7_000,
        }

    def report(self, *, now):
        """Return a consistent snapshot and current period exposures."""
        timestamp = self._time(now)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            policy = self._policy(connection)
            return {
                **self._totals(connection),
                "checked_at": timestamp,
                "peak_risk_cents": policy["peak_risk_cents"],
                "paid_work_frozen": bool(policy["frozen"]),
                "first_week_exposure_cents": self._week_exposure(connection, self.week_end),
                "monthly_exposure_cents": self._month_exposure(connection, timestamp[:7]),
                "limits": {
                    "initial_cents": policy["initial_cents"],
                    "first_week_cents": policy["first_week_cents"],
                    "monthly_cents": policy["monthly_cents"],
                },
            }
