# TODO — Documentation debt

## OTel tracing strategy

The distributed tracing setup across ingest → categorize → ledger uses a deliberate
span-link pattern (not parent-child) to keep per-row traces small and independent.
This is non-obvious and needs to be documented.

### What to document

Update **README.md** and **docs/architecture.md** (and any relevant diagram in
`docs/diagrams/`) to cover:

1. **Why span links instead of parent-child**
   - A file drop can produce thousands of rows; parent-child at that scale makes
     traces unusable in any UI.
   - Parent spans are expected to outlive their children; here the ingest span
     closes before ledger has processed a single message.

2. **The three-trace-per-row pattern**
   - *Ingest trace* (1 per file): `ingest.processFile` → N `ingest.publish`
     Producer children, tagged with `row.index` and `source.file`.
   - *Categorize trace* (1 per row): `categorize.handle_imported` root span
     with a `SpanLink` → the specific `ingest.publish` span.
   - *Ledger trace* (1 per row): `ledger.consume_transaction` root span with
     a `SpanLink` → `categorize.handle_imported`.

3. **The `x-link-traceparent` custom header**
   - Categorize writes its span context into `x-link-traceparent` (W3C
     traceparent format) rather than the standard `traceparent` header.
   - Reason: the standard `traceparent` header is read automatically by .NET's
     RabbitMQ auto-instrumentation, which would make ledger a *child* of
     categorize rather than a separate root trace with a link.
   - Ledger reads `x-link-traceparent` exclusively for the `ActivityLink`; it
     never propagates it further.
   - Ingest → categorize uses the standard `traceparent` header because Python's
     pika instrumentation is not active (removed) and categorize manually
     controls how it interprets the header.

4. **Where each service's OTel setup lives**
   - Go (ingest): `services/ingest/telemetry.go` — gRPC OTLP exporter, reads
     `OTEL_*` env vars injected by Aspire.
   - Python (categorize): `services/categorize/src/categorize/telemetry.py` —
     gRPC OTLP exporter; `PikaInstrumentor` intentionally NOT used.
   - C# (ledger): `shared/Wyb.ServiceDefaults/Extensions.cs` — standard Aspire
     service defaults; custom `ActivitySource("Wyb.Ledger")` in
     `TransactionConsumer.cs`.

### Files to update

- `README.md` — add an Observability section or expand the architecture summary
- `docs/architecture.md` — add a Distributed tracing section
- `docs/diagrams/transaction-import-sequence.drawio` — update the sequence
  diagram to show span links between services
