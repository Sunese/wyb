# WYB — Technical Architecture

## System overview

## Transaction import sequence

## Categorisation matching logic

### Match types

| Type         | Behaviour                                         |
| ------------ | ------------------------------------------------- |
| `Contains`   | `pattern.upper() in description.upper()`          |
| `Exact`      | `description.upper() == pattern.upper()`          |
| `StartsWith` | `description.upper().startswith(pattern.upper())` |
| `Regex`      | `re.search(pattern, description, IGNORECASE)`     |

## Distributed tracing

Every transaction produces three independent root traces — one per service boundary. They are connected by **span links** (not parent-child relationships).

### Why span links instead of parent-child

A file drop can produce thousands of rows. Parent-child at that scale makes every trace unusable in any UI — a single `ingest.processFile` span would have thousands of children from two different services. Span links give the same navigability without forcing a single root to outlive all its descendants.

There is also a lifecycle mismatch: the ingest span closes before ledger has processed a single message. A parent is semantically expected to outlive its children; a link carries no such obligation.

### The three-trace-per-row pattern

```
Ingest trace (1 per file)
  └─ ingest.processFile
       └─ ingest.publish  [row_index=N, source_file=…]  ──link──┐
                                                                  │
Categorize trace (1 per row)                                      │
  └─ categorize.handle_imported  ◄── SpanLink ──────────────────┘
       └─ …                                             ──link──┐
                                                                  │
Ledger trace (1 per row)                                          │
  └─ ledger.consume_transaction  ◄── SpanLink ──────────────────┘
```

- **Ingest**: one trace per file (`ingest.processFile`), with one `ingest.publish` child span per row. Each child is tagged `row.index` and `source.file`.
- **Categorize**: one root span per row (`categorize.handle_imported`) with a `SpanLink` pointing to the corresponding `ingest.publish` span.
- **Ledger**: one root span per row (`ledger.consume_transaction`) with a `SpanLink` pointing to `categorize.handle_imported`.

### The `x-link-traceparent` custom header

Categorize writes its span context into the RabbitMQ message property `x-link-traceparent` (W3C traceparent format) instead of the standard `traceparent` header.

**Why:** .NET's RabbitMQ auto-instrumentation reads `traceparent` automatically and would silently make ledger a *child* of categorize rather than an independent root with a link. Using a custom header lets ledger opt in explicitly via `ActivityLink` without triggering the auto-instrumentation path.

Ledger reads `x-link-traceparent` exclusively for `ActivityLink` construction and never propagates it further.

Ingest → categorize uses the standard `traceparent` header because Python's pika instrumentation is intentionally not active and categorize manually controls how it parses the header.

### OTel setup per service

| Service | Location | Notes |
| --- | --- | --- |
| Go (ingest) | `services/ingest/telemetry.go` | gRPC OTLP exporter; reads `OTEL_*` vars injected by Aspire |
| Python (categorize) | `services/categorize/src/categorize/telemetry.py` | gRPC OTLP exporter; `PikaInstrumentor` intentionally NOT used |
| C# (ledger) | `shared/Wyb.ServiceDefaults/Extensions.cs` | Standard Aspire service defaults; custom `ActivitySource("Wyb.Ledger")` in `TransactionConsumer.cs` |

## Deduplication key

The same CSV can be imported any number of times safely. The dedup key is a SHA-256 hash of five fields:

```
sha256( account_id | date | amount_minor | currency | normalised_description )
```

`normalised_description` is upper-cased and whitespace-collapsed before hashing, so minor formatting differences in bank exports do not create duplicate transactions.

This makes replay safe: dropping a CSV again re-runs categorisation with the current rules, and the upsert updates any transaction whose category has changed — unless the user manually overrode it.
