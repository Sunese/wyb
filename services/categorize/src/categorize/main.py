import json
import logging
import os
import re
import threading
from contextlib import asynccontextmanager

import httpx
from confluent_kafka import Consumer, Producer
from fastapi import FastAPI
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace

from categorize.telemetry import configure_tracing

logger = logging.getLogger(__name__)

# Topics: ingest publishes imported transactions to IN_TOPIC; we publish the
# enriched result to OUT_TOPIC, which the ledger consumes.
IN_TOPIC = "transaction.imported"
OUT_TOPIC = "transaction.categorized"
GROUP_ID = "categorize"


_rules_url = (
    os.environ.get("services__rules__https__0")
    or os.environ.get("services__rules__http__0")
    or "http://localhost:8000"
)


def _fetch_rules_and_aliases() -> tuple[list, list]:
    with httpx.Client(base_url=_rules_url, timeout=5.0) as client:
        rules = client.get("/rules").raise_for_status().json()
        merchants = client.get("/merchants").raise_for_status().json()
    aliases = [
        {**alias, "merchantName": m["canonicalName"], "defaultCategory": m["defaultCategory"]}
        for m in merchants
        for alias in m["aliases"]
    ]
    return rules, aliases


# ── Pure categorization logic (unit-testable) ─────────────────────────────────

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


def _apply_rules(raw_description: str, rules: list) -> dict | None:
    for rule in sorted(rules, key=lambda r: r["priority"]):
        if _matches(raw_description, rule["pattern"], rule["matchType"]):
            return rule
    return None


def _resolve_merchant(raw_description: str, aliases: list) -> dict | None:
    for alias in aliases:
        if _matches(raw_description, alias["pattern"], alias["matchType"]):
            return alias
    return None


def _enrich(payload: dict) -> tuple[dict, dict]:
    """Apply rules + merchant aliases to a transaction payload.

    Returns (enriched_payload, span_attributes) so the caller can record
    the decision on its span.
    """
    raw_description = payload.get("raw_description", "")

    rules, aliases = _fetch_rules_and_aliases()

    rule_match = _apply_rules(raw_description, rules)
    merchant_match = _resolve_merchant(raw_description, aliases)
    merchant_name = merchant_match["merchantName"] if merchant_match else None
    merchant_default_category = merchant_match.get("defaultCategory") if merchant_match else None

    if rule_match:
        category = rule_match["category"]
        matched_by = "rule"
    elif merchant_default_category:
        category = merchant_default_category
        matched_by = "merchant_default"
    else:
        category = "Uncategorized"
        matched_by = "none"

    enriched = {**payload, "category": category}
    if merchant_name:
        enriched["merchant_name"] = merchant_name

    attributes = {
        "categorize.raw_description": raw_description,
        "categorize.category": category,
        "categorize.matched_by": matched_by,
    }
    if rule_match:
        attributes["categorize.rule.name"] = rule_match["name"]
        attributes["categorize.rule.priority"] = rule_match["priority"]
    if merchant_name:
        attributes["categorize.merchant.name"] = merchant_name

    return enriched, attributes


# ── Kafka helpers ─────────────────────────────────────────────────────────────

def _headers_to_carrier(headers) -> dict:
    """Confluent message headers are a list of (key, bytes) tuples (or None)."""
    carrier: dict = {}
    for key, value in headers or []:
        carrier[key] = value.decode() if isinstance(value, (bytes, bytearray)) else value
    return carrier


def _context_to_headers() -> list[tuple[str, bytes]]:
    """Inject the current trace context into W3C headers for the outgoing message."""
    carrier: dict = {}
    propagate.inject(carrier)
    return [(k, v.encode()) for k, v in carrier.items()]


# ── Kafka consumer (runs in a background thread) ──────────────────────────────

_stop = threading.Event()


def run_consumer():
    tracer = trace.get_tracer("categorize")
    bootstrap = os.environ["ConnectionStrings__kafka"]

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    producer = Producer({"bootstrap.servers": bootstrap})
    consumer.subscribe([IN_TOPIC])
    logger.info("categorize consuming %s, producing %s", IN_TOPIC, OUT_TOPIC)

    try:
        while not _stop.is_set():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka consume error: %s", msg.error())
                continue

            try:
                _handle_message(msg, tracer, producer)
            except Exception:
                # One bad message must not wedge the consumer.
                logger.exception("Failed to handle message, skipping")
    finally:
        producer.flush(5)
        consumer.close()


def _handle_message(msg, tracer, producer):
    raw = msg.value()
    body = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
    logger.info("Received message: %s", body)

    carrier = _headers_to_carrier(msg.headers())
    upstream_ctx = propagate.extract(carrier)
    upstream_span_ctx = trace.get_current_span(upstream_ctx).get_span_context()
    links = [trace.Link(upstream_span_ctx)] if upstream_span_ctx.is_valid else []

    with tracer.start_as_current_span(
        "categorize.handle_imported",
        context=otel_context.Context(),
        kind=trace.SpanKind.CONSUMER,
        links=links,
    ) as span:
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            # Poison message — log and skip so we don't wedge the consumer.
            logger.warning("Skipping undeserializable message: %s", body)
            return

        enriched, attributes = _enrich(payload)
        for key, value in attributes.items():
            span.set_attribute(key, value)

        logger.info("Publishing message: %s", json.dumps(enriched))
        producer.produce(
            OUT_TOPIC,
            value=json.dumps(enriched).encode(),
            headers=_context_to_headers(),
        )
        producer.poll(0)


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_tracing()
    _stop.clear()
    thread = threading.Thread(target=run_consumer, daemon=True)
    thread.start()
    try:
        yield
    finally:
        _stop.set()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
