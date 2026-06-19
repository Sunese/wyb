from datetime import date, timedelta

import pytest

from detect.detector import (
    MISSED_TOLERANCE_FACTOR,
    MIN_OCCURRENCES,
    ChargeRecord,
    DetectedSubscription,
    _classify_cadence,
    detect_subscriptions,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_charges(
    merchant: str,
    currency: str,
    amount_minor: int,
    start: date,
    interval_days: int,
    count: int,
    *,
    jitter_days: int = 0,
) -> list[ChargeRecord]:
    """Evenly-spaced (or slightly jittered) debit charges."""
    return [
        ChargeRecord(
            raw_description=merchant,
            amount_minor=-abs(amount_minor),
            currency=currency,
            date=start + timedelta(days=interval_days * i + (i % 2) * jitter_days),
        )
        for i in range(count)
    ]


TODAY = date(2025, 6, 1)
START = date(2024, 1, 1)


# ── _classify_cadence ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("days,expected", [
    (7, "weekly"),
    (3, "weekly"),
    (9, "weekly"),
    (14, "bi-weekly"),
    (30, "monthly"),
    (90, "quarterly"),
    (180, "semi-annual"),
    (365, "annual"),
    (2, None),
    (500, None),
])
def test_classify_cadence(days, expected):
    assert _classify_cadence(days) == expected


# ── Basic detection ───────────────────────────────────────────────────────────

def test_monthly_subscription_detected():
    txs = make_charges("Netflix", "DKK", 10900, START, 30, 6)
    result = detect_subscriptions(txs, today=TODAY)
    assert len(result) == 1
    sub = result[0]
    assert sub.raw_description == "Netflix"
    assert sub.cadence_label == "monthly"
    assert sub.current_amount_minor == 10900
    assert sub.occurrence_count == 6


def test_weekly_subscription_detected():
    txs = make_charges("Gym", "DKK", 5000, START, 7, 8)
    result = detect_subscriptions(txs, today=TODAY)
    assert len(result) == 1
    assert result[0].cadence_label == "weekly"


def test_annual_subscription_detected():
    txs = make_charges("Adobe", "DKK", 150000, START, 365, 3)
    result = detect_subscriptions(txs, today=TODAY)
    assert len(result) == 1
    assert result[0].cadence_label == "annual"


def test_below_min_occurrences_not_detected():
    txs = make_charges("Netflix", "DKK", 10900, START, 30, MIN_OCCURRENCES - 1)
    assert detect_subscriptions(txs, today=TODAY) == []


def test_exactly_min_occurrences_detected():
    txs = make_charges("Netflix", "DKK", 10900, START, 30, MIN_OCCURRENCES)
    assert len(detect_subscriptions(txs, today=TODAY)) == 1


# ── Credits ignored ───────────────────────────────────────────────────────────

def test_credits_are_ignored():
    credits = [
        ChargeRecord("Netflix", 10900, "DKK", START + timedelta(days=30 * i))
        for i in range(6)
    ]
    assert detect_subscriptions(credits, today=TODAY) == []


# ── Transactions without merchant ignored ─────────────────────────────────────

def test_no_merchant_ignored():
    txs = [
        ChargeRecord("", -10900, "DKK", START + timedelta(days=30 * i))
        for i in range(6)
    ]
    assert detect_subscriptions(txs, today=TODAY) == []


# ── Irregular charges not classified ─────────────────────────────────────────

def test_irregular_charges_not_detected():
    dates = [START, START + timedelta(30), START + timedelta(35),
             START + timedelta(95), START + timedelta(105)]
    txs = [ChargeRecord("Random", -5000, "DKK", d) for d in dates]
    assert detect_subscriptions(txs, today=TODAY) == []


# ── Small jitter still detected ───────────────────────────────────────────────

def test_small_jitter_still_regular():
    txs = make_charges("Spotify", "DKK", 9900, START, 30, 6, jitter_days=2)
    result = detect_subscriptions(txs, today=TODAY)
    assert len(result) == 1
    assert result[0].cadence_label == "monthly"


# ── Price change detection ────────────────────────────────────────────────────

def test_price_change_flagged():
    charges = make_charges("Netflix", "DKK", 10900, START, 30, 5)
    charges.append(ChargeRecord("Netflix", -12900, "DKK", charges[-1].date + timedelta(days=30)))
    result = detect_subscriptions(charges, today=TODAY)
    assert len(result) == 1
    sub = result[0]
    assert sub.price_changed is True
    assert sub.current_amount_minor == 12900
    assert sub.previous_amount_minor == 10900


def test_no_price_change_when_stable():
    txs = make_charges("Netflix", "DKK", 10900, START, 30, 6)
    assert detect_subscriptions(txs, today=TODAY)[0].price_changed is False


# ── Status: active vs missed ──────────────────────────────────────────────────

def test_status_active_when_within_tolerance():
    last = TODAY - timedelta(days=25)
    charges = make_charges("Netflix", "DKK", 10900, last - timedelta(days=150), 30, 5)
    charges.append(ChargeRecord("Netflix", -10900, "DKK", last))
    result = detect_subscriptions(charges, today=TODAY)
    assert result[0].status == "active"


def test_status_missed_when_overdue():
    last = TODAY - timedelta(days=60)
    charges = make_charges("Netflix", "DKK", 10900, last - timedelta(days=150), 30, 5)
    charges.append(ChargeRecord("Netflix", -10900, "DKK", last))
    result = detect_subscriptions(charges, today=TODAY)
    assert result[0].status == "missed"


# ── Status: import-lag awareness ──────────────────────────────────────────────

def test_status_unconfirmed_when_overdue_but_import_is_stale():
    # The charge is overdue on the calendar, but our data only reaches a few
    # days past the last charge — we simply haven't imported the window where
    # the next charge would appear. Must NOT be reported as missed.
    last = TODAY - timedelta(days=60)
    charges = make_charges("Netflix", "DKK", 10900, last - timedelta(days=150), 30, 5)
    charges.append(ChargeRecord("Netflix", -10900, "DKK", last))
    result = detect_subscriptions(
        charges, today=TODAY, data_frontier=last + timedelta(days=5)
    )
    assert result[0].status == "unconfirmed"


def test_status_missed_when_data_covers_the_gap():
    # Same overdue charge, but the data frontier extends past the expected
    # date, so the absence is real.
    last = TODAY - timedelta(days=60)
    charges = make_charges("Netflix", "DKK", 10900, last - timedelta(days=150), 30, 5)
    charges.append(ChargeRecord("Netflix", -10900, "DKK", last))
    result = detect_subscriptions(charges, today=TODAY, data_frontier=TODAY)
    assert result[0].status == "missed"


def test_stale_import_never_reports_missed():
    # Regression for the false positive: a subscription overdue only because
    # the user hasn't imported in months must never be flagged missed.
    last = TODAY - timedelta(days=120)
    charges = make_charges("Netflix", "DKK", 10900, last - timedelta(days=150), 30, 5)
    charges.append(ChargeRecord("Netflix", -10900, "DKK", last))
    result = detect_subscriptions(
        charges, today=TODAY, data_frontier=last + timedelta(days=2)
    )
    assert result[0].status != "missed"


def test_frontier_defaults_to_today():
    # Without an explicit frontier, behaviour collapses to a wall-clock verdict.
    last = TODAY - timedelta(days=60)
    charges = make_charges("Netflix", "DKK", 10900, last - timedelta(days=150), 30, 5)
    charges.append(ChargeRecord("Netflix", -10900, "DKK", last))
    assert detect_subscriptions(charges, today=TODAY)[0].status == "missed"


# ── Annual estimate ───────────────────────────────────────────────────────────

def test_annual_estimate_monthly():
    txs = make_charges("Netflix", "DKK", 10900, START, 30, 6)
    sub = detect_subscriptions(txs, today=TODAY)[0]
    assert sub.annual_estimate_minor == round(10900 * (365.0 / 30))


# ── Multiple subscriptions ────────────────────────────────────────────────────

def test_multiple_merchants_detected_independently():
    netflix = make_charges("Netflix", "DKK", 10900, START, 30, 6)
    spotify = make_charges("Spotify", "DKK", 9900, START, 30, 6)
    result = detect_subscriptions(netflix + spotify, today=TODAY)
    assert {s.raw_description for s in result} == {"Netflix", "Spotify"}


def test_same_merchant_different_currencies_separate():
    dkk = make_charges("Spotify", "DKK", 9900, START, 30, 6)
    eur = make_charges("Spotify", "EUR", 999, START, 30, 6)
    result = detect_subscriptions(dkk + eur, today=TODAY)
    assert len(result) == 2
    assert {s.currency for s in result} == {"DKK", "EUR"}


# ── Edge inputs ───────────────────────────────────────────────────────────────

def test_empty_transactions():
    assert detect_subscriptions([], today=TODAY) == []


def test_single_transaction_per_merchant():
    txs = [ChargeRecord("Netflix", -10900, "DKK", START)]
    assert detect_subscriptions(txs, today=TODAY) == []


# ── Amount stability ──────────────────────────────────────────────────────────

def test_variable_amount_not_detected():
    # A grocery store visited monthly with different amounts each time is NOT a subscription.
    charges = [
        ChargeRecord("Meny", -34218, "DKK", START),
        ChargeRecord("Meny", -41090, "DKK", START + timedelta(days=30)),
    ]
    assert detect_subscriptions(charges, today=TODAY) == []


def test_stable_amount_detected():
    charges = [
        ChargeRecord("Netflix", -11900, "DKK", START),
        ChargeRecord("Netflix", -11900, "DKK", START + timedelta(days=30)),
    ]
    assert len(detect_subscriptions(charges, today=TODAY)) == 1


def test_single_price_change_still_detected():
    # 5 months stable + one price increase: the dominant amount is 10900 (5/6),
    # so it's still a subscription, just one that raised its price.
    charges = make_charges("Netflix", "DKK", 10900, START, 30, 5)
    charges.append(ChargeRecord("Netflix", -12900, "DKK", charges[-1].date + timedelta(days=30)))
    result = detect_subscriptions(charges, today=TODAY)
    assert len(result) == 1
    assert result[0].price_changed is True


def test_two_equal_amount_groups_not_detected():
    # Two charges at price A and two at price B (no single dominant price): not a subscription.
    charges = [
        ChargeRecord("Netto", -18845, "DKK", START),
        ChargeRecord("Netto", -21125, "DKK", START + timedelta(days=30)),
        ChargeRecord("Netto", -18845, "DKK", START + timedelta(days=60)),
        ChargeRecord("Netto", -21125, "DKK", START + timedelta(days=90)),
    ]
    assert detect_subscriptions(charges, today=TODAY) == []
