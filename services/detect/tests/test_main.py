from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from detect.main import _sync_subscription_charges, app, process_transaction
from detect.models import MerchantCharge, Subscription, SubscriptionCharge


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_subscriptions_empty(client) -> None:
    c, _ = client
    response = c.get("/subscriptions")
    assert response.status_code == 200
    assert response.json() == []


def test_list_subscriptions_returns_rows_sorted_by_annual_estimate(client) -> None:
    c, engine = client
    now = datetime.now(timezone.utc)
    today = date.today()

    with Session(engine) as db:
        db.add(Subscription(
            raw_description="Netflix",
            currency="DKK",
            cadence_days=30.0,
            cadence_label="monthly",
            current_amount_minor=10900,
            previous_amount_minor=None,
            price_changed=False,
            last_charge_date=today,
            next_expected_date=today,
            status="active",
            first_seen_date=today,
            occurrence_count=3,
            annual_estimate_minor=130800,
            detected_at=now,
            updated_at=now,
        ))
        db.add(Subscription(
            raw_description="Spotify",
            currency="DKK",
            cadence_days=30.0,
            cadence_label="monthly",
            current_amount_minor=6900,
            previous_amount_minor=5900,
            price_changed=True,
            last_charge_date=today,
            next_expected_date=today,
            status="active",
            first_seen_date=today,
            occurrence_count=5,
            annual_estimate_minor=82800,
            detected_at=now,
            updated_at=now,
        ))
        db.commit()

    response = c.get("/subscriptions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    # sorted descending by annual_estimate_minor
    assert body[0]["raw_description"] == "Netflix"
    assert body[1]["raw_description"] == "Spotify"
    assert body[1]["price_changed"] is True
    assert body[0]["annual_estimate_minor"] == 130800


# ── /subscriptions/{id}/charges ───────────────────────────────────────────────

def _make_sub(db: Session) -> Subscription:
    today = date.today()
    now = datetime.now(timezone.utc)
    sub = Subscription(
        raw_description="Netflix",
        currency="DKK",
        cadence_days=30.0,
        cadence_label="monthly",
        current_amount_minor=10900,
        previous_amount_minor=None,
        price_changed=False,
        last_charge_date=today,
        next_expected_date=today + timedelta(days=30),
        status="active",
        first_seen_date=today,
        occurrence_count=2,
        annual_estimate_minor=130800,
        detected_at=now,
        updated_at=now,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def _make_charge(db: Session, tx_id: str, days_ago: int) -> MerchantCharge:
    charge = MerchantCharge(
        transaction_id=tx_id,
        raw_description="Netflix",
        currency="DKK",
        amount_minor=-10900,
        charge_date=date.today() - timedelta(days=days_ago),
    )
    db.add(charge)
    db.commit()
    db.refresh(charge)
    return charge


def test_subscription_charges_empty_for_unknown_id(client) -> None:
    c, _ = client
    response = c.get("/subscriptions/does-not-exist/charges")
    assert response.status_code == 200
    assert response.json() == []


def test_subscription_charges_returns_linked_charges(client) -> None:
    c, engine = client
    with Session(engine) as db:
        sub = _make_sub(db)
        charge1 = _make_charge(db, "tx-1", days_ago=60)
        charge2 = _make_charge(db, "tx-2", days_ago=30)
        db.add(SubscriptionCharge(subscription_id=sub.id, merchant_charge_id=charge1.id))
        db.add(SubscriptionCharge(subscription_id=sub.id, merchant_charge_id=charge2.id))
        db.commit()
        sub_id = sub.id

    response = c.get(f"/subscriptions/{sub_id}/charges")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    # ordered most-recent first
    assert body[0]["charge_date"] > body[1]["charge_date"]


def test_subscription_charges_excludes_other_subscriptions(client) -> None:
    c, engine = client
    with Session(engine) as db:
        sub1 = _make_sub(db)
        charge1 = _make_charge(db, "tx-a", days_ago=30)
        sub2 = Subscription(
            raw_description="Spotify",
            currency="DKK",
            cadence_days=30.0,
            cadence_label="monthly",
            current_amount_minor=6900,
            previous_amount_minor=None,
            price_changed=False,
            last_charge_date=date.today(),
            next_expected_date=date.today() + timedelta(days=30),
            status="active",
            first_seen_date=date.today(),
            occurrence_count=2,
            annual_estimate_minor=82800,
            detected_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(sub2)
        db.commit()
        db.refresh(sub2)
        charge2 = MerchantCharge(
            transaction_id="tx-b",
            raw_description="Spotify",
            currency="DKK",
            amount_minor=-6900,
            charge_date=date.today() - timedelta(days=30),
        )
        db.add(charge2)
        db.commit()
        db.refresh(charge2)
        db.add(SubscriptionCharge(subscription_id=sub1.id, merchant_charge_id=charge1.id))
        db.add(SubscriptionCharge(subscription_id=sub2.id, merchant_charge_id=charge2.id))
        db.commit()
        sub1_id = sub1.id

    response = c.get(f"/subscriptions/{sub1_id}/charges")
    body = response.json()
    assert len(body) == 1
    assert body[0]["transaction_id"] == "tx-a"


# ── _sync_subscription_charges ────────────────────────────────────────────────

def test_sync_subscription_charges_inserts_rows(client) -> None:
    _, engine = client
    with Session(engine) as db:
        sub = _make_sub(db)
        charge1 = _make_charge(db, "tx-s1", days_ago=60)
        charge2 = _make_charge(db, "tx-s2", days_ago=30)
        _sync_subscription_charges(db, sub.id, [charge1.id, charge2.id])
        rows = db.exec(
            select(SubscriptionCharge).where(SubscriptionCharge.subscription_id == sub.id)
        ).all()
        assert {r.merchant_charge_id for r in rows} == {charge1.id, charge2.id}


def test_sync_subscription_charges_is_idempotent(client) -> None:
    _, engine = client
    with Session(engine) as db:
        sub = _make_sub(db)
        charge = _make_charge(db, "tx-idem", days_ago=30)
        _sync_subscription_charges(db, sub.id, [charge.id])
        _sync_subscription_charges(db, sub.id, [charge.id])  # second call must not fail
        rows = db.exec(
            select(SubscriptionCharge).where(SubscriptionCharge.subscription_id == sub.id)
        ).all()
        assert len(rows) == 1


def test_sync_subscription_charges_adds_new_without_removing_old(client) -> None:
    _, engine = client
    with Session(engine) as db:
        sub = _make_sub(db)
        charge1 = _make_charge(db, "tx-g1", days_ago=60)
        charge2 = _make_charge(db, "tx-g2", days_ago=30)
        _sync_subscription_charges(db, sub.id, [charge1.id])
        _sync_subscription_charges(db, sub.id, [charge1.id, charge2.id])
        rows = db.exec(
            select(SubscriptionCharge).where(SubscriptionCharge.subscription_id == sub.id)
        ).all()
        assert len(rows) == 2


# ── process_transaction populates join table ──────────────────────────────────

def test_process_transaction_links_charges_to_subscription(client) -> None:
    _, engine = client
    tracer = MagicMock()

    base = date(2025, 1, 1)
    for i in range(3):
        process_transaction(
            {
                "dedup_key": f"dedup-{i}",
                "raw_description": "NETFLIX.COM",
                "amount_minor": -10900,
                "currency": "DKK",
                "date": (base + timedelta(days=30 * i)).isoformat(),
            },
            tracer,
        )

    with Session(engine) as db:
        sub = db.exec(
            select(Subscription).where(Subscription.raw_description == "NETFLIX.COM")
        ).first()
        assert sub is not None

        links = db.exec(
            select(SubscriptionCharge).where(SubscriptionCharge.subscription_id == sub.id)
        ).all()
        assert len(links) == 3

        charge_ids = {lnk.merchant_charge_id for lnk in links}
        charges = db.exec(
            select(MerchantCharge).where(MerchantCharge.raw_description == "NETFLIX.COM")
        ).all()
        assert {c.id for c in charges} == charge_ids
