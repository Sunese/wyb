# WYB

Self-hosted personal finance app (monitoring, not budgeting). Polyglot monorepo orchestrated with Aspire.

## Repo layout

| Path | Language | Role |
|------|----------|------|
| `apphost/` | C# (.NET 10) | Aspire AppHost — orchestration + dashboard |
| `shared/Wyb.ServiceDefaults/` | C# | OTel / health / discovery for .NET services |
| `services/ledger/` | C# (.NET 10) | Canonical store, owns `ledger-db` |
| `services/ingest/` | Go | Watches a directory for CSVs, publishes to Kafka |
| `services/rules/` | Python (FastAPI + uv) | Category rules + merchant aliases store, owns `rules-db` |
| `services/categorize/` | Python (FastAPI + uv) | Consumes `transaction.imported`, applies rules/merchants, publishes `transaction.categorized` |
| `services/detect/` | Python (FastAPI + uv) | Subscription detection (M3); owns `detect-db`. Anomaly detection planned (M4) |
| `services/web/` | SvelteKit (adapter-node) | UI |
| `tests/integration/` | C# (xunit) | Full AppHost boot via `Aspire.Hosting.Testing` |

Infra: Postgres + Kafka — managed by Aspire, persistent volumes.

## Run

```bash
cd apphost && aspire run
```

Dashboard URL is printed. All services should go green. OTel traces across every service.

## Test commands

```bash
# .NET (ledger)
dotnet test services/ledger/tests/Wyb.Ledger.Tests
dotnet test services/ledger/tests/Wyb.Ledger.IntegrationTests

# cross-service integration (boots full AppHost)
dotnet test tests/integration

# Go (ingest)
go test ./services/ingest/...

# Python (rules, categorize, detect)
uv run --directory services/rules pytest
uv run --directory services/categorize pytest
uv run --directory services/detect pytest

# SvelteKit
cd services/web
npm run check          # svelte-check + typescript
npm run test:unit      # vitest (server + browser/component)
npm run test:e2e       # playwright
npm run lint           # prettier --check && eslint
npm run format         # prettier --write
```

## Conventional ordering

`npm run check` then `npm run test:unit` for web changes.
`dotnet test` for any .NET change.

## Key conventions

- **Money**: integer minor units (øre) + currency code. Never floats.
- **Time**: `timestamptz` UTC in DB, `Europe/Copenhagen` in UI.
- **Transaction dedup**: `hash(account_id, date, amount_minor, currency, normalized_description)`. Stable, derivable, survives reimports.
- **Raw imports are sacred**: every CSV stored verbatim, never modified. Canonical store is *derived* from raw + code.
- **Schema versioning**: every event payload includes `schema_version`.
- **One Postgres instance**, database-per-service (`ledger-db`, `rules-db`, `detect-db`). Services never read another service's tables — cross-service data goes over HTTP + Kafka.
- **Event format**: JSON over Kafka. Protobuf later.
- **No auth yet**: single-user behind WireGuard.

## Aspire gotchas

- `AddViteApp` installs npm deps automatically — do NOT call `WithNpmPackageInstallation()`.
- Do NOT call `WithHttpEndpoint()` on Vite resources — duplicate endpoint error.
- FastAPI: use `lifespan` async context manager, not `@app.on_event`.
- SvelteKit OTel: `WithEnvironment("NODE_OPTIONS", "--import ./otel.js")` — SDK must start before HTTP server.
- Aspire injects env vars like `ConnectionStrings__kafka` and `services__ledger__http__0` — read those, don't hardcode.
- Zsh: quote bracket deps like `'uvicorn[standard]'`.

## MCP servers configured

- `.mcp.json` — `aspire agent mcp`
- `services/web/.mcp.json` — Svelte MCP server (docs + autofixer)
- `.claude/skills/` — `aspire`, `aspireify`, `dotnet-inspect`, `playwright-cli`

## Reference

Detailed implementation notes in `handoff.md` (Milestone 1 plan with pitfalls).

## Branch hygiene

One feature per branch, named `m<milestone>/<short-desc>`. Merge sequentially so each branch can verify against working upstream services.
