import logging
import os
import threading
from contextlib import asynccontextmanager

from confluent_kafka import Consumer
from fastapi import FastAPI

logger = logging.getLogger(__name__)

# detect watches the transaction.categorized stream. Anomaly detection is a
# placeholder for now (M3/M4); for now it just consumes the stream.
IN_TOPIC = "transaction.categorized"
GROUP_ID = "detect"

_stop = threading.Event()


def run_consumer():
    bootstrap = os.environ["ConnectionStrings__kafka"]
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([IN_TOPIC])
    logger.info("detect consuming %s", IN_TOPIC)

    try:
        while not _stop.is_set():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka consume error: %s", msg.error())
                continue

            raw = msg.value()
            body = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            logger.info("detect received: %s", body)
    finally:
        consumer.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
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
