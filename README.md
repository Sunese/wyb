# WYB

Self-hosted personal finance app. Watches your money so you don't have to.

## What it is

Most months, you glance at your finances and nothing has changed. Some months, something has — a subscription crept up, a new recurring charge appeared, a category drifted. WYB tells you which kind of month it is.

It's framed as monitoring, not budgeting. Think Grafana for your bank account, not YNAB.

## Why self-host

Mint died. YNAB is a subscription. Lunchmoney costs $100/year. WYB runs on your homelab, owns your data, and you can leave any time — every CSV ever ingested is stored verbatim, and full backups round-trip cleanly.

## Status

Early. Foundation works; first real feature (CSV ingest from a Danish bank) in progress.

## Stack

Polyglot by design — each service uses the language that fits the job:

- .NET for the canonical store
- Go for ingest and I/O-heavy services
- Python for anything statistical or AI-adjacent
- SvelteKit for the web UI

Orchestrated with Aspire in dev, Postgres + RabbitMQ for state and events, OpenTelemetry traces across every service.

## Observability

Every service emits OpenTelemetry traces to the Aspire dashboard (OTLP gRPC). A file drop produces three independent root traces per row — one from ingest, one from categorize, one from ledger — connected by **span links** rather than parent-child relationships. This keeps individual row traces small and navigable even when a file contains thousands of rows.

The link chain looks like:

```
ingest.publish ──link──► categorize.handle_imported ──link──► ledger.consume_transaction
```

See [docs/architecture.md](docs/architecture.md#distributed-tracing) for the full tracing design, including why a custom `x-link-traceparent` header is used between categorize and ledger.

## Running

```bash
aspire run
```

Open the dashboard URL it prints.