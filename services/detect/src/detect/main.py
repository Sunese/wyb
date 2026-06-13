import logging
import os
import threading
from contextlib import asynccontextmanager

from confluent_kafka import Consumer, Producer
from fastapi import FastAPI
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace

from detect.telemetry import configure_telemetry

logger = logging.getLogger(__name__)

# detect watches the transaction.categorized stream. Anomaly detection is a
# placeholder for now (M3/M4); for now it just consumes the stream.
IN_TOPIC = "transaction.categorized"
OUT_TOPIC = "detect.detected"
GROUP_ID = "detect"

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
    logger.info("detect consuming %s, producing %s", IN_TOPIC, OUT_TOPIC)

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
        "detect.handle_categorized",
        context=otel_context.Context(),
        kind=trace.SpanKind.CONSUMER,
        links=links,
    ) as span:
        try:
            logger.info("Handling message...")
        except (ValueError, TypeError):
            # Poison message — log and skip so we don't wedge the consumer.
            logger.warning("Skipping undeserializable message: %s", body)
            return

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_telemetry()
    _stop.clear()
    thread = threading.Thread(target=run_consumer, daemon=True)
    thread.start()
    try:
        yield
    finally:
        _stop.set()


app = FastAPI(title="wyb-detect", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    print("Hello from detect!")
