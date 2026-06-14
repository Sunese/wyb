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

## License

WYB is licensed under the [GNU Affero General Public License v3.0](LICENSE)
(`AGPL-3.0-only`).

In short: you're free to run, study, modify, and share it — but if you run a
modified version as a network service, you must offer your users the
corresponding source. Copyright © 2026 Sune Engtorp.

