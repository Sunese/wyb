# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WYB is a self-hosted personal finance monitoring app — "Grafana for your bank account." Polyglot monorepo orchestrated with Aspire. Each service uses the language that fits the job.

## Running

Always consult relevant Aspire skills and MCP servers on how to start the Aspire host etc.

To trigger a series of transaction-imported events, copy the "testdata/danskebank_salary_20250101_20251231.csv" file to the "drop" folder.

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
# TODO

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

## Current milestone (M2)

Goal: Categorization (rules + manual) + merchant resolution

For more details on the roadmap, read the [roadmap](./roadmap.md)

## Sync philosophy

CSV/XLSX import from the user's bank is the primary, blessed sync path
and stays that way forever. Reasons, in order of importance:

	1.	No regulatory exposure ever. CSV imports are not PSD2-regulated,
	    so WYB never has to become an AISP, never has to deal with
	    Finanstilsynet, and never has to operate as an agent of a licensed
	    AISP. This is true regardless of how many users WYB has or
	    whether they self-host or use a hosted instance.
	2.	No third-party dependency for the core experience. WYB does not
	    depend on Enable Banking, GoCardless/Nordigen, Tink, or any
	    similar provider for the default sync path. GoCardless killed
	    their free hobbyist tier for new users in 2025; relying on
	    Enable Banking's restricted-mode terms continuing as-is would
	    leave WYB one ToS change away from being broken.
	3.	The thesis is periodic, not real-time. Anomaly detection on
	    personal spending is a weekly-to-monthly question. The data does
	    not need to be live; it needs to be reasonably current.
	4.	Danish banks have decent CSV/XLSX exports. Danske Bank, Nordea,
	    Jyske, Sydbank, Lunar, and Revolut all expose usable exports
	    with meaningful merchant text. The friction tax is real but
	    bounded.

Optional power-user path: Enable Banking restricted-mode auto-sync, for
users who want auto-sync and are willing to register their own Enable
Banking application and link their own accounts to it. Documented as
advanced and opt-in. Because each user uses their own Enable Banking app
under their own consent, this stays inside Enable Banking's
"individual non-commercial use" allowance even when other people use
instances of WYB the original author packaged.

Conventions for sync UX
	- Import lag is the enemy. The UI must aggressively surface "you
	    haven't imported in N days" nudges so the periodic ingest
	    cadence stays healthy.
	- Missing-expected-charge detection (M3/M4) must reason about import
	    lag. Don't flag Netflix as missing just because the user hasn't
	    imported in two weeks.
	- Per-bank parser quirks are inevitable. Treat parsers as plugins,
	    not core code, and version them.


## Notes for the next agent
- Resist scope creep into budgeting features. The thesis is anomaly
    detection; staying weird where weird is the whole point.
- Resist scope creep into "real-time everything." Periodic is fine.
    The product's job is to tell the user when something matters,
    not to be a dashboard they stare at.
- Don't normalize merchant strings in M2 by hand-coding rules
    forever — design the rule engine and alias table now so it
    grows.
- Treat bank CSV parsers as a plugin surface from day one. New
    banks will show up; existing banks will change their formats.
- The user is the only user for the foreseeable future; design for
    that, but keep multi-user in mind for the schema.
- Do not pursue an AISP license, do not become an agent of a
    licensed AISP, do not register WYB as a service operator with
    Finanstilsynet. If WYB ever grows into something that would
    require any of those, that's a strategic decision for a future
    version of the project, not a technical task to add to the
    roadmap.
- For decisions on libraries/services, prefer boring infrastructure
    (Postgres, RabbitMQ, Docker volumes) and save novelty budget for
    application logic.
