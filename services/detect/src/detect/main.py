import asyncio
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
from confluent_kafka import Consumer, Producer
from fastapi import Depends, FastAPI
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from sqlalchemy import func
from sqlmodel import Session, col, select

from detect.db import init_db, make_engine
from detect.detector import ChargeRecord, DetectedSubscription, detect_subscriptions
from detect.models import MerchantCharge, Subscription, SubscriptionCharge, SubscriptionResponse
from detect.telemetry import configure_telemetry

logger = logging.getLogger(__name__)

IN_TOPIC = "transaction.categorized"
OUT_TOPIC = "subscription.detected"
GROUP_ID = "detect"

# How often to scan for missed subscriptions (default: 6 h).
SCAN_INTERVAL_SECONDS = int(os.environ.get("DETECT_SCAN_INTERVAL_SECONDS", str(6 * 3600)))

_stop = threading.Event()
_engine = None
_producer: Producer | None = None

_rules_url = (
    os.environ.get("services__rules__https__0")
    or os.environ.get("services__rules__http__0")
    or ""
)

_rules_cache_lock = threading.Lock()
_rules_cache: list = []
_rules_cache_expires: float = 0.0
_RULES_CACHE_TTL = 30  # seconds


# ── Rules resolution (canonical merchant name at read time) ───────────────────

def _fetch_aliases() -> list:
    global _rules_cache, _rules_cache_expires
    with _rules_cache_lock:
        if time.monotonic() < _rules_cache_expires:
            return _rules_cache
        if not _rules_url:
            return []
        try:
            ca_bundle = os.environ.get("CURL_CA_BUNDLE", True)
            merchants = httpx.get(f"{_rules_url}/merchants", timeout=3.0, verify=ca_bundle).raise_for_status().json()
            aliases = [
                {**alias, "canonicalName": m["canonicalName"]}
                for m in merchants
                for alias in m["aliases"]
            ]
            _rules_cache = aliases
            _rules_cache_expires = time.monotonic() + _RULES_CACHE_TTL
        except Exception:
            logger.warning("Could not fetch merchant aliases from rules service")
        return _rules_cache


def _matches(text: str, pattern: str, match_type: str) -> bool:
    text_u = text.upper()
    pattern_u = pattern.upper()
    if match_type == "Contains":
        return pattern_u in text_u
    if match_type == "Exact":
        return text_u == pattern_u
    if match_type == "StartsWith":
        return text_u.startswith(pattern_u)
    if match_type == "Regex":
        return bool(re.search(pattern, text, re.IGNORECASE))
    return False


def _resolve_merchant_name(raw_description: str) -> str:
    """Return canonical merchant name, or raw_description if no alias matches."""
    for alias in _fetch_aliases():
        if _matches(raw_description, alias["pattern"], alias["matchType"]):
            return alias["canonicalName"]
    return raw_description


def _to_response(sub: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        raw_description=sub.raw_description,
        merchant_name=_resolve_merchant_name(sub.raw_description),
        currency=sub.currency,
        cadence_days=sub.cadence_days,
        cadence_label=sub.cadence_label,
        current_amount_minor=sub.current_amount_minor,
        previous_amount_minor=sub.previous_amount_minor,
        price_changed=sub.price_changed,
        last_charge_date=sub.last_charge_date,
        next_expected_date=sub.next_expected_date,
        status=sub.status,
        first_seen_date=sub.first_seen_date,
        occurrence_count=sub.occurrence_count,
        annual_estimate_minor=sub.annual_estimate_minor,
        detected_at=sub.detected_at,
        updated_at=sub.updated_at,
    )


# ── Kafka helpers ─────────────────────────────────────────────────────────────

def _headers_to_carrier(headers) -> dict:
    return {
        k: v.decode() if isinstance(v, (bytes, bytearray)) else v
        for k, v in (headers or [])
    }


def _emit(event_type: str, payload: dict, tracer) -> None:
    if _producer is None:
        return
    msg = json.dumps({"event_type": event_type, "schema_version": 1, **payload})
    carrier: dict = {}
    propagate.inject(carrier)
    headers = [(k, v.encode()) for k, v in carrier.items()]
    _producer.produce(OUT_TOPIC, value=msg.encode(), headers=headers)
    _producer.poll(0)
    logger.info("Emitted %s for %s", event_type, payload.get("merchant_name"))


# ── Core detection logic ──────────────────────────────────────────────────────

def _data_frontier(db: Session) -> date | None:
    """Latest charge date we've imported across all merchants.

    This is how far our data actually reaches; subscriptions are only judged
    "missed" relative to this frontier, never relative to wall-clock time, so
    a stale import can't manufacture false missed-charge alarms.
    """
    return db.exec(select(func.max(MerchantCharge.charge_date))).one()


def _charges_for_description(
    db: Session, raw_description: str, currency: str
) -> tuple[list[ChargeRecord], list[str]]:
    rows = db.exec(
        select(MerchantCharge).where(
            MerchantCharge.raw_description == raw_description,
            MerchantCharge.currency == currency,
        )
    ).all()
    records = [
        ChargeRecord(
            raw_description=r.raw_description,
            amount_minor=r.amount_minor,
            currency=r.currency,
            date=r.charge_date,
        )
        for r in rows
    ]
    return records, [r.id for r in rows]


def _sync_subscription_charges(
    db: Session, subscription_id: str, charge_ids: list[str]
) -> None:
    existing = {
        row.merchant_charge_id
        for row in db.exec(
            select(SubscriptionCharge).where(
                SubscriptionCharge.subscription_id == subscription_id
            )
        ).all()
    }
    for cid in charge_ids:
        if cid not in existing:
            db.add(SubscriptionCharge(subscription_id=subscription_id, merchant_charge_id=cid))
    db.commit()


def _upsert_subscription(
    db: Session,
    detected: DetectedSubscription,
    charge_ids: list[str],
    tracer,
) -> None:
    now = datetime.now(timezone.utc)
    existing = db.exec(
        select(Subscription).where(
            Subscription.raw_description == detected.raw_description,
            Subscription.currency == detected.currency,
        )
    ).first()

    if existing is None:
        new_sub = Subscription(
            raw_description=detected.raw_description,
            currency=detected.currency,
            cadence_days=detected.cadence_days,
            cadence_label=detected.cadence_label,
            current_amount_minor=detected.current_amount_minor,
            previous_amount_minor=detected.previous_amount_minor,
            price_changed=detected.price_changed,
            last_charge_date=detected.last_charge_date,
            next_expected_date=detected.next_expected_date,
            status=detected.status,
            first_seen_date=detected.first_seen_date,
            occurrence_count=detected.occurrence_count,
            annual_estimate_minor=detected.annual_estimate_minor,
            detected_at=now,
            updated_at=now,
        )
        db.add(new_sub)
        db.commit()
        db.refresh(new_sub)
        _sync_subscription_charges(db, new_sub.id, charge_ids)
        _emit("subscription_detected", _sub_payload(detected), tracer)
        return

    price_changed = (
        detected.current_amount_minor != existing.current_amount_minor
        and existing.current_amount_minor != 0
    )
    status_changed = detected.status != existing.status

    existing.cadence_days = detected.cadence_days
    existing.cadence_label = detected.cadence_label
    existing.current_amount_minor = detected.current_amount_minor
    existing.previous_amount_minor = detected.previous_amount_minor
    existing.price_changed = detected.price_changed
    existing.last_charge_date = detected.last_charge_date
    existing.next_expected_date = detected.next_expected_date
    existing.status = detected.status
    existing.occurrence_count = detected.occurrence_count
    existing.annual_estimate_minor = detected.annual_estimate_minor
    existing.updated_at = now
    db.add(existing)
    db.commit()
    _sync_subscription_charges(db, existing.id, charge_ids)

    if price_changed:
        _emit("subscription_price_changed", _sub_payload(detected), tracer)
    elif status_changed and detected.status == "missed":
        _emit("subscription_missed", _sub_payload(detected), tracer)


def _sub_payload(s: DetectedSubscription) -> dict:
    return {
        "raw_description": s.raw_description,
        "currency": s.currency,
        "cadence_days": s.cadence_days,
        "cadence_label": s.cadence_label,
        "current_amount_minor": s.current_amount_minor,
        "previous_amount_minor": s.previous_amount_minor,
        "price_changed": s.price_changed,
        "last_charge_date": s.last_charge_date.isoformat(),
        "next_expected_date": s.next_expected_date.isoformat(),
        "status": s.status,
        "annual_estimate_minor": s.annual_estimate_minor,
    }


def process_transaction(tx: dict, tracer) -> None:
    """Store a new debit charge and re-evaluate subscriptions for its description."""
    amount = tx.get("amount_minor", 0)
    if amount >= 0:
        return  # credits are not our concern

    raw_description = tx.get("raw_description", "").strip()
    if not raw_description:
        logger.debug("skipping transaction with empty raw_description")
        return

    transaction_id = tx.get("dedup_key") or tx.get("id", "")
    currency = tx.get("currency", "")
    charge_date = date.fromisoformat(tx["date"])

    with Session(_engine) as db:
        if db.exec(
            select(MerchantCharge).where(MerchantCharge.transaction_id == transaction_id)
        ).first():
            logger.debug("skipping transaction - already stored")
            return  # already seen; idempotent

        db.add(MerchantCharge(
            transaction_id=transaction_id,
            raw_description=raw_description,
            currency=currency,
            amount_minor=amount,
            charge_date=charge_date,
        ))
        db.commit()
        logger.info("added transaction: %s", raw_description)

        charges, charge_ids = _charges_for_description(db, raw_description, currency)
        frontier = _data_frontier(db)

    results = detect_subscriptions(charges, data_frontier=frontier)
    for detected in results:
        with Session(_engine) as db:
            _upsert_subscription(db, detected, charge_ids, tracer)


# ── Missed-subscription scanner (scheduled) ───────────────────────────────────

def scan_missed(tracer) -> None:
    """Re-evaluate overdue subscriptions against the data frontier.

    A subscription is only marked ``missed`` (and alarmed on) when our
    imported data extends past its expected charge date. If it's overdue
    only on the calendar — because the user hasn't imported recently — it's
    marked ``unconfirmed`` and stays silent; the UI nudges a re-import.
    """
    today = date.today()
    with Session(_engine) as db:
        frontier = _data_frontier(db) or today
        subs = db.exec(
            select(Subscription).where(col(Subscription.status).in_(["active", "unconfirmed"]))
        ).all()
        for sub in subs:
            tolerance = sub.cadence_days * 0.5
            overdue_days = lambda ref: (ref - sub.next_expected_date).days  # noqa: E731
            if overdue_days(frontier) > tolerance:
                new_status = "missed"
            elif overdue_days(today) > tolerance:
                new_status = "unconfirmed"
            else:
                new_status = "active"

            if new_status == sub.status:
                continue

            sub.status = new_status
            sub.updated_at = datetime.now(timezone.utc)
            db.add(sub)
            db.commit()

            if new_status == "missed":
                _emit(
                    "subscription_missed",
                    {
                        "raw_description": sub.raw_description,
                        "currency": sub.currency,
                        "cadence_days": sub.cadence_days,
                        "cadence_label": sub.cadence_label,
                        "current_amount_minor": sub.current_amount_minor,
                        "previous_amount_minor": sub.previous_amount_minor,
                        "price_changed": sub.price_changed,
                        "last_charge_date": sub.last_charge_date.isoformat(),
                        "next_expected_date": sub.next_expected_date.isoformat(),
                        "status": "missed",
                        "annual_estimate_minor": sub.annual_estimate_minor,
                    },
                    tracer,
                )


async def missed_scan_loop(tracer):
    await asyncio.sleep(60)  # allow startup to settle
    while True:
        try:
            await asyncio.get_event_loop().run_in_executor(None, scan_missed, tracer)
        except Exception:
            logger.exception("Missed-subscription scan failed")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


# ── Kafka consumer ─────────────────────────────────────────────────────────────

def run_consumer():
    tracer = trace.get_tracer("detect")
    bootstrap = os.environ["ConnectionStrings__kafka"]
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([IN_TOPIC])
    logger.info("detect consuming %s → producing %s", IN_TOPIC, OUT_TOPIC)

    try:
        while not _stop.is_set():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka error: %s", msg.error())
                continue

            carrier = _headers_to_carrier(msg.headers())
            upstream_ctx = propagate.extract(carrier)
            upstream_span_ctx = trace.get_current_span(upstream_ctx).get_span_context()
            links = [trace.Link(upstream_span_ctx)] if upstream_span_ctx.is_valid else []

            with tracer.start_as_current_span(
                "detect.handle_categorized",
                context=otel_context.Context(),
                kind=trace.SpanKind.CONSUMER,
                links=links,
            ):
                try:
                    raw = msg.value()
                    if raw is None:
                        consumer.commit(message=msg)
                        continue
                    body = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    tx = json.loads(body)
                    process_transaction(tx, tracer)
                    consumer.commit(message=msg)
                except (ValueError, KeyError, json.JSONDecodeError):
                    logger.warning("Skipping malformed message")
                    consumer.commit(message=msg)
                except Exception:
                    logger.exception("Failed to handle message — skipping")
                    consumer.commit(message=msg)
    finally:
        consumer.close()


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _producer
    configure_telemetry()

    bootstrap = os.environ["ConnectionStrings__kafka"]
    _producer = Producer({"bootstrap.servers": bootstrap})

    _engine = make_engine()
    init_db(_engine)

    tracer = trace.get_tracer("detect")

    _stop.clear()
    consumer_thread = threading.Thread(target=run_consumer, daemon=True)
    consumer_thread.start()

    scan_task = asyncio.create_task(missed_scan_loop(tracer))

    try:
        yield
    finally:
        _stop.set()
        scan_task.cancel()
        if _producer:
            _producer.flush()


app = FastAPI(title="wyb-detect", lifespan=lifespan)


def get_db():
    with Session(_engine) as session:
        yield session


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/subscriptions")
def list_subscriptions(db: Session = Depends(get_db)) -> list[SubscriptionResponse]:
    from sqlalchemy import desc as sa_desc
    rows = db.exec(
        select(Subscription).order_by(sa_desc(Subscription.annual_estimate_minor))
    ).all()
    return [_to_response(s) for s in rows]


@app.get("/subscriptions/{subscription_id}/charges")
def get_subscription_charges(
    subscription_id: str, db: Session = Depends(get_db)
) -> list[MerchantCharge]:
    from sqlalchemy import desc as sa_desc
    links = db.exec(
        select(SubscriptionCharge).where(
            SubscriptionCharge.subscription_id == subscription_id
        )
    ).all()
    if not links:
        return []
    charge_ids = [lnk.merchant_charge_id for lnk in links]
    return db.exec(
        select(MerchantCharge)
        .where(col(MerchantCharge.id).in_(charge_ids))
        .order_by(sa_desc(MerchantCharge.charge_date))
    ).all()


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
