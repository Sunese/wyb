from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class MerchantCharge(SQLModel, table=True):
    """One debit charge stored for pattern analysis, keyed by raw bank description."""
    __tablename__ = "merchant_charges"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    transaction_id: str = Field(index=True, unique=True)
    raw_description: str = Field(index=True)
    currency: str
    amount_minor: int   # negative (debit)
    charge_date: date
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Subscription(SQLModel, table=True):
    """Detected recurring charge for a (raw_description, currency) pair."""
    __tablename__ = "subscriptions"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    raw_description: str = Field(index=True)
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


class SubscriptionResponse(BaseModel):
    """API response shape — includes merchant_name resolved from the rules service."""
    id: str
    raw_description: str
    merchant_name: str          # canonical name from rules, or raw_description if no alias
    currency: str
    cadence_days: float
    cadence_label: str
    current_amount_minor: int
    previous_amount_minor: Optional[int]
    price_changed: bool
    last_charge_date: date
    next_expected_date: date
    status: str
    first_seen_date: date
    occurrence_count: int
    annual_estimate_minor: int
    detected_at: datetime
    updated_at: datetime


class SubscriptionCharge(SQLModel, table=True):
    """Links a detected subscription to the MerchantCharge rows that back it."""
    __tablename__ = "subscription_charges"

    subscription_id: str = Field(foreign_key="subscriptions.id", primary_key=True)
    merchant_charge_id: str = Field(foreign_key="merchant_charges.id", primary_key=True)
