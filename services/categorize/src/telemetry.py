"""OpenTelemetry SDK setup. Reads OTEL_* env vars injected by Aspire."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator


def configure_tracing() -> None:
    """Configure the global tracer provider and propagators.

    Resource attributes (service.name etc.) are picked up automatically from
    OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES.
    Endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT.
    """
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    set_global_textmap(
        CompositePropagator(
            [TraceContextTextMapPropagator(), W3CBaggagePropagator()]
        )
    )