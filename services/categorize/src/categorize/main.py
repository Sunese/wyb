import asyncio
import json
import os
import time

from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.pika import PikaInstrumentor
import pika

from categorize.telemetry import configure_tracing

configure_tracing()
PikaInstrumentor().instrument()

tracer = trace.get_tracer("categorize")


def _start_consumer() -> None:
    """Blocking consumer loop. Runs in a background thread."""
    url = os.environ["ConnectionStrings__rabbit"]
    params = pika.URLParameters(url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue="transaction.imported", durable=True)

    def on_message(ch, method, properties, body):
        # PikaInstrumentor extracted the trace context from message headers,
        # so this span is a child of the ledger's publish span.
        with tracer.start_as_current_span("categorize.handle_imported"):
            payload = json.loads(body)
            print(f"[categorize] received transaction: {payload['description']}")
            # simulate some work
            time.sleep(1)
            ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue="transaction.imported", on_message_callback=on_message)
    channel.start_consuming()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: kick off the blocking pika consumer in a background thread.
    loop = asyncio.get_event_loop()
    consumer_task = loop.run_in_executor(None, _start_consumer)
    yield
    # Shutdown: pika's BlockingConnection doesn't have a clean async cancel
    # path. For now we just let the process exit; we can wire a graceful
    # shutdown later when we move to aio-pika.
    _ = consumer_task


app = FastAPI(title="wyb-categorize", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}