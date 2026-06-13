import statistics
from dataclasses import dataclass
from datetime import date, timedelta

MIN_OCCURRENCES = 2
REGULARITY_CV_THRESHOLD = 0.30  # coefficient of variation; below this = regular

# (min_days, max_days, label) — ordered narrow-to-wide so first match wins
CADENCE_BUCKETS: list[tuple[int, int, str]] = [
    (3, 9, "weekly"),
    (10, 17, "bi-weekly"),
    (18, 45, "monthly"),
    (46, 75, "bi-monthly"),
    (76, 135, "quarterly"),
    (136, 270, "semi-annual"),
    (271, 400, "annual"),
]

MISSED_TOLERANCE_FACTOR = 0.5  # flag missed if overdue by > 50% of cadence


@dataclass(frozen=True)
class ChargeRecord:
    """A single debit from a known merchant, used as detector input."""
    merchant_name: str
    amount_minor: int   # negative (debit)
    currency: str
    date: date


@dataclass(frozen=True)
class DetectedSubscription:
    merchant_name: str
    currency: str
    cadence_days: float
    cadence_label: str
    current_amount_minor: int   # positive (absolute value)
    previous_amount_minor: int | None
    price_changed: bool
    last_charge_date: date
    next_expected_date: date
    status: str                 # "active" | "missed"
    first_seen_date: date
    occurrence_count: int
    annual_estimate_minor: int


def _classify_cadence(median_days: float) -> str | None:
    for lo, hi, label in CADENCE_BUCKETS:
        if lo <= median_days <= hi:
            return label
    return None


def detect_subscriptions(
    charges: list[ChargeRecord],
    today: date | None = None,
) -> list[DetectedSubscription]:
    """
    Analyse a list of charges and return those that look like
    recurring subscriptions.

    ``today`` is injectable so unit tests can pin the reference date.
    """
    if today is None:
        today = date.today()

    # Only debits from a known merchant.
    debits = [c for c in charges if c.amount_minor < 0 and c.merchant_name]

    # Group by (merchant_name, currency).
    groups: dict[tuple[str, str], list[ChargeRecord]] = {}
    for c in debits:
        key = (c.merchant_name, c.currency)
        groups.setdefault(key, []).append(c)

    subscriptions: list[DetectedSubscription] = []

    for (merchant, currency), group in groups.items():
        group = sorted(group, key=lambda c: c.date)

        if len(group) < MIN_OCCURRENCES:
            continue

        intervals = [
            (group[i + 1].date - group[i].date).days
            for i in range(len(group) - 1)
        ]

        median_interval = statistics.median(intervals)
        if median_interval <= 0:
            continue

        cv = (
            statistics.stdev(intervals) / median_interval
            if len(intervals) >= 2
            else 0.0
        )
        if cv >= REGULARITY_CV_THRESHOLD:
            continue

        cadence_label = _classify_cadence(median_interval)
        if cadence_label is None:
            continue

        last = group[-1]
        prev = group[-2] if len(group) >= 2 else None

        current_amount = abs(last.amount_minor)
        previous_amount = abs(prev.amount_minor) if prev else None
        price_changed = previous_amount is not None and current_amount != previous_amount

        next_expected = last.date + timedelta(days=median_interval)
        tolerance = timedelta(days=median_interval * MISSED_TOLERANCE_FACTOR)
        status = "missed" if today > next_expected + tolerance else "active"

        annual_estimate = round(current_amount * (365.0 / median_interval))

        subscriptions.append(DetectedSubscription(
            merchant_name=merchant,
            currency=currency,
            cadence_days=round(median_interval, 1),
            cadence_label=cadence_label,
            current_amount_minor=current_amount,
            previous_amount_minor=previous_amount,
            price_changed=price_changed,
            last_charge_date=last.date,
            next_expected_date=next_expected,
            status=status,
            first_seen_date=group[0].date,
            occurrence_count=len(group),
            annual_estimate_minor=annual_estimate,
        ))

    return subscriptions
