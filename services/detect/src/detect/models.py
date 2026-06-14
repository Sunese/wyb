from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class MerchantCharge(SQLModel, table=True):
    """One debit charge from a known merchant, stored for pattern analysis."""
    __tablename__ = "merchant_charges"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    transaction_id: str = Field(index=True, unique=True)
    merchant_name: str = Field(index=True)
    currency: str
    amount_minor: int   # negative (debit)
    charge_date: date
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Subscription(SQLModel, table=True):
    """Detected recurring subscription for a (merchant, currency) pair."""
    __tablename__ = "subscriptions"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    merchant_name: str = Field(index=True)
    currency: str
    cadence_days: float
    cadence_label: str
    current_amount_minor: int
    previous_amount_minor: Optional[int] = None
    price_changed: bool = False
    last_charge_date: date
    next_expected_date: date
    status: str   # "active" | "missed" | "unconfirmed"
    first_seen_date: date
    occurrence_count: int
    annual_estimate_minor: int
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
