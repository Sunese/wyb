import json
import os
import time
from opentelemetry import trace
from opentelemetry.instrumentation.pika import PikaInstrumentor
import pika
from telemetry import configure_tracing
import pika, sys, os

def main():
    print("[categorize] starting up...")
    configure_tracing()
    PikaInstrumentor().instrument()
    tracer = trace.get_tracer("categorize")

    url = os.environ["ConnectionStrings__rabbit"]
    params = pika.URLParameters(url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue="transaction.imported", durable=True)
    channel.queue_bind(exchange="transaction.imported", queue="transaction.imported")

    def on_message(ch, method, properties, body):
            # PikaInstrumentor extracted the trace context from message headers,
            # so this span is a child of the ledger's publish span.
            with tracer.start_as_current_span("categorize.handle_imported"):
                payload = json.loads(body)
                print(f"[categorize] received transaction: {payload}")
                # simulate some work
                time.sleep(1)

                # perform actual categorization logic here
                category = "Uncategorized"  # Replace with actual categorization logic
                print(f"[categorize] categorized transaction as: {category}")

                ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_publish(
                    exchange="transaction.categorized",
                    routing_key="",
                    body=json.dumps({**payload, "category": category}),
                    properties=pika.BasicProperties(headers=properties.headers),  # propagate trace context
                )

    channel.basic_consume(queue="transaction.imported", on_message_callback=on_message)
    channel.start_consuming()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)