import asyncio
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from confluent_kafka import Consumer, Producer
from fastapi import FastAPI
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from sqlmodel import Session, select

from detect.db import init_db, make_engine
from detect.detector import ChargeRecord, DetectedSubscription, detect_subscriptions
from detect.models import MerchantCharge, Subscription
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

def _charges_for_merchant(db: Session, merchant: str, currency: str) -> list[ChargeRecord]:
    rows = db.exec(
        select(MerchantCharge).where(
            MerchantCharge.merchant_name == merchant,
            MerchantCharge.currency == currency,
        )
    ).all()
    return [
        ChargeRecord(
            merchant_name=r.merchant_name,
            amount_minor=r.amount_minor,
            currency=r.currency,
            date=r.charge_date,
        )
        for r in rows
    ]


def _upsert_subscription(
    db: Session,
    detected: DetectedSubscription,
    tracer,
) -> None:
    now = datetime.now(timezone.utc)
    existing = db.exec(
        select(Subscription).where(
            Subscription.merchant_name == detected.merchant_name,
            Subscription.currency == detected.currency,
        )
    ).first()

    if existing is None:
        db.add(Subscription(
            merchant_name=detected.merchant_name,
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
        ))
        db.commit()
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

    if price_changed:
        _emit("subscription_price_changed", _sub_payload(detected), tracer)
    elif status_changed and detected.status == "missed":
        _emit("subscription_missed", _sub_payload(detected), tracer)


def _sub_payload(s: DetectedSubscription) -> dict:
    return {
        "merchant_name": s.merchant_name,
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
    """Store a new charge and re-evaluate the subscription for its merchant."""
    merchant = tx.get("merchant_name")
    amount = tx.get("amount_minor", 0)

    if not merchant or amount >= 0:
        return  # credits and unknown merchants are not our concern

    transaction_id = tx.get("dedup_key") or tx.get("id", "")
    currency = tx.get("currency", "")
    charge_date = date.fromisoformat(tx["date"])

    with Session(_engine) as db:
        if db.exec(
            select(MerchantCharge).where(MerchantCharge.transaction_id == transaction_id)
        ).first():
            return  # already seen; idempotent

        db.add(MerchantCharge(
            transaction_id=transaction_id,
            merchant_name=merchant,
            currency=currency,
            amount_minor=amount,
            charge_date=charge_date,
        ))
        db.commit()

        charges = _charges_for_merchant(db, merchant, currency)

    results = detect_subscriptions(charges)
    for detected in results:
        with Session(_engine) as db:
            _upsert_subscription(db, detected, tracer)


# ── Missed-subscription scanner (scheduled) ───────────────────────────────────

def scan_missed(tracer) -> None:
    """Emit subscription_missed events for subscriptions that are overdue."""
    today = date.today()
    with Session(_engine) as db:
        subs = db.exec(select(Subscription).where(Subscription.status == "active")).all()
        for sub in subs:
            tolerance = sub.cadence_days * 0.5
            if (today - sub.next_expected_date).days > tolerance:
                sub.status = "missed"
                sub.updated_at = datetime.now(timezone.utc)
                db.add(sub)
                db.commit()
                _emit(
                    "subscription_missed",
                    {
                        "merchant_name": sub.merchant_name,
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
