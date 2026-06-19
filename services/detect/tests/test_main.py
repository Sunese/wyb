from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from detect.main import app
from detect.models import Subscription


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
