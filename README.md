# WYB

Self-hosted personal finance app.

## Status

Early.

## Stack

Polyglot

- .NET for the canonical store
- Go for ingest and I/O-heavy services
- Python for anything statistical or AI-adjacent
- SvelteKit for the web UI

Orchestrated with Aspire in dev, Postgres + Kafka for state and events, OpenTelemetry traces across every service.

## Running

```bash
aspire run
```
