# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WYB is a self-hosted personal finance monitoring app — "Grafana for your bank account." Polyglot monorepo orchestrated with Aspire. Each service uses the language that fits the job.

## Running

```bash
cd apphost && aspire run
```

Dashboard URL is printed. All services should go green. Postgres and RabbitMQ use persistent volumes.

## Test commands

```bash
# .NET (ledger unit + integration)
dotnet test services/ledger/tests/Wyb.Ledger.Tests
dotnet test services/ledger/tests/Wyb.Ledger.IntegrationTests

# Cross-service integration (boots the full AppHost)
dotnet test tests/integration

# Go (ingest)
go test ./services/ingest/...

# Python
uv run --directory services/categorize pytest
uv run --directory services/detect pytest

# SvelteKit — run in this order for web changes
cd services/web
npm run check          # svelte-check + typescript
npm run test:unit      # vitest
npm run test:e2e       # playwright
npm run lint           # prettier --check && eslint
npm run format         # prettier --write
```

## Architecture

```
apphost/                       Aspire AppHost — wires everything together
shared/Wyb.ServiceDefaults/    OTel / health / discovery shared by .NET services
services/
  ledger/                      .NET 10 Web API — canonical store, owns Postgres
  ingest/                      Go — watches a directory, parses CSVs, publishes events
  categorize/                  Python (FastAPI + uv) — consumes transaction events
  detect/                      Python (FastAPI + uv) — anomaly detection (placeholder)
  web/                         SvelteKit (adapter-node) — UI
tests/integration/             C# xunit — boots full AppHost via Aspire.Hosting.Testing
```

**Data flow:** ingest drops CSVs → publishes `transaction.imported` events to RabbitMQ → ledger consumes, deduplicates, and stores in Postgres → web reads from ledger over HTTP.

**One Postgres, owned by ledger.** No DB-per-service. Service-to-service communication is HTTP + RabbitMQ.

OTel traces propagate across all services via `traceparent` in HTTP headers and RabbitMQ message properties. Aspire injects `OTEL_*` env vars automatically.

## Key conventions

- **Money**: integer minor units (øre) + currency code. Never floats.
- **Time**: `timestamptz` UTC in DB, `Europe/Copenhagen` displayed in the UI.
- **Transaction dedup key**: `hash(account_id, date, amount_minor, currency, normalized_description)`. Stable, derivable, survives reimports. Idempotency lives in ledger — ingest can republish freely.
- **Raw imports are sacred**: every CSV ingested is stored verbatim and never modified. The canonical store is derived from raw data + code.
- **Schema versioning**: every RabbitMQ event payload includes `schema_version`.
- **Event format**: JSON over RabbitMQ for now; Protobuf planned later.
- **No auth yet**: single-user, assumed to be behind WireGuard.

## Aspire gotchas

- `AddViteApp` installs npm deps automatically — do **not** call `WithNpmPackageInstallation()`.
- Do **not** call `WithHttpEndpoint()` on Vite resources — causes a duplicate endpoint error.
- FastAPI services must use `lifespan` async context manager, not `@app.on_event`.
- SvelteKit OTel requires `WithEnvironment("NODE_OPTIONS", "--import ./otel.js")` in the AppHost so the SDK starts before SvelteKit's HTTP server.
- Aspire injects env vars like `ConnectionStrings__rabbit` and `services__ledger__http__0` — read those, never hardcode URLs or connection strings.
- Zsh: quote bracket-spec deps like `'uvicorn[standard]'`.

## MCP servers

- `.mcp.json` — `aspire agent mcp` (Aspire dashboard/resource access)
- `services/web/.mcp.json` — Svelte MCP server (docs + autofixer)

Available skills: `aspire`, `aspireify`, `dotnet-inspect`, `playwright-cli`.

## Branch hygiene

One feature per branch, named `m<milestone>/<short-desc>` (e.g. `m1/ledger-ef-core`). Merge sequentially so each branch can verify against working upstream services.

## Current milestone (M1)

Goal: drop a CSV from a Danish bank into `drop/`, see normalized transactions in ledger, browsable from web.

Three branches in order:
1. `m1/ledger-ef-core` — EF Core + Postgres + transaction endpoints + RabbitMQ consumer
2. `m1/ingest-csv` — fsnotify + real CSV parsing, publishes to RabbitMQ, archives raw to `raw/`
3. `m1/web-transactions-table` — server-side load from ledger, table with date/description/amount

`drop/` and `raw/` directories at repo root are gitignored (bind-mounted into the ingest container).
