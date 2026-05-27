import json
import os
import re
import threading
from contextlib import asynccontextmanager

import httpx
import pika
from fastapi import FastAPI
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace

from categorize.telemetry import configure_tracing


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


def _apply_rules(raw_description: str, rules: list) -> str:
    for rule in sorted(rules, key=lambda r: r["priority"]):
        if _matches(raw_description, rule["pattern"], rule["matchType"]):
            return rule["category"]
    return "Uncategorized"


def _resolve_merchant(raw_description: str, aliases: list) -> dict | None:
    for alias in aliases:
        if _matches(raw_description, alias["pattern"], alias["matchType"]):
            return alias
    return None


# ── RabbitMQ consumer (runs in a background thread) ───────────────────────────

def run_consumer():
    tracer = trace.get_tracer("categorize")
    url = os.environ["ConnectionStrings__rabbit"]
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()

    channel.exchange_declare(exchange="transaction.imported", exchange_type="fanout", durable=True)
    channel.exchange_declare(exchange="transaction.categorized", exchange_type="fanout", durable=True)
    channel.queue_declare(queue="categorize.transaction.imported", durable=True)
    channel.queue_bind(exchange="transaction.imported", queue="categorize.transaction.imported")

    def on_message(ch, method, properties, body):
        carrier = {
            k: v.decode() if isinstance(v, bytes) else v
            for k, v in (properties.headers or {}).items()
        }
        upstream_ctx = propagate.extract(carrier)
        upstream_span_ctx = trace.get_current_span(upstream_ctx).get_span_context()
        links = [trace.Link(upstream_span_ctx)] if upstream_span_ctx.is_valid else []

        with tracer.start_as_current_span(
            "categorize.handle_imported",
            context=otel_context.Context(),
            kind=trace.SpanKind.CONSUMER,
            links=links,
        ):
            payload = json.loads(body)
            raw_description = payload.get("raw_description", "")

            rules, aliases = _fetch_rules_and_aliases()

            rule_category = _apply_rules(raw_description, rules)
            merchant_match = _resolve_merchant(raw_description, aliases)
            merchant_name = merchant_match["merchantName"] if merchant_match else None
            merchant_default_category = merchant_match.get("defaultCategory") if merchant_match else None
            category = (rule_category if rule_category != "Uncategorized"
                        else merchant_default_category or "Uncategorized")

            print(f"[categorize] '{raw_description}' → {category}"
                  + (f" ({merchant_name})" if merchant_name else ""))

            enriched = {**payload, "category": category}
            if merchant_name is not None:
                enriched["merchant_name"] = merchant_name

            ch.basic_ack(delivery_tag=method.delivery_tag)

            span_ctx = trace.get_current_span().get_span_context()
            outgoing_headers: dict = {}
            if span_ctx.is_valid:
                trace_id = format(span_ctx.trace_id, "032x")
                span_id = format(span_ctx.span_id, "016x")
                flags = "01" if span_ctx.trace_flags & trace.TraceFlags.SAMPLED else "00"
                outgoing_headers["x-link-traceparent"] = f"00-{trace_id}-{span_id}-{flags}"
            channel.basic_publish(
                exchange="transaction.categorized",
                routing_key="",
                body=json.dumps(enriched),
                properties=pika.BasicProperties(headers=outgoing_headers),
            )

    channel.basic_consume(queue="categorize.transaction.imported", on_message_callback=on_message)
    channel.start_consuming()


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_tracing()
    thread = threading.Thread(target=run_consumer, daemon=True)
    thread.start()
    yield


app = FastAPI(lifespan=lifespan)
