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

## Running

```bash
aspire run
```

Open the dashboard URL it prints.