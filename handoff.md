# WYB — Milestone 1 handoff

Polyglot finance app with anomaly-detection thesis. Foundation works (M0 complete: Aspire AppHost, polyglot OTel traces fan across web → ledger → rabbit → categorize). Now: real CSV ingest from one Danish bank, end-to-end.

## Stack

- **AppHost** (Aspire 13.2, .NET 10) — orchestration + dashboard for OTel
- **ledger** — .NET 10 Web API, owns Postgres
- **ingest** — Go, watches a directory for CSVs
- **categorize**, **detect** — Python (FastAPI + uv)
- **web** — SvelteKit + Vite
- **Postgres**, **RabbitMQ** — managed by Aspire
- Service-to-service over HTTP + RabbitMQ events

OTel: Aspire injects `OTEL_*` env vars; each service has its own SDK init. `traceparent` propagates across HTTP and RabbitMQ messages — confirmed working.

## Repo layout
wyb/
apphost/                       # Aspire AppHost
shared/Wyb.ServiceDefaults/    # OTel/health/discovery for .NET services
services/
ledger/                      # .NET — owns Postgres
ingest/                      # Go — CSV intake (Milestone 1)
categorize/                  # Python — consumes events
detect/                      # Python — placeholder, mirror of categorize
web/                         # SvelteKit
tests/integration/             # cross-service tests via Aspire.Hosting.Testing

## Run

```bash
cd apphost
aspire run
```

Dashboard URL is printed. All services should go green; Postgres + RabbitMQ have data volumes and persistent lifetimes.

## Conventions

- **Money**: integer minor units (øre) + currency code. Never floats.
- **Time**: `timestamptz` UTC in DB, `Europe/Copenhagen` in UI.
- **Transaction dedup key**: `hash(account_id, date, amount_minor, currency, normalized_description)`. Stable, derivable, survives reimports.
- **Raw imports are sacred**: every CSV ever ingested is stored verbatim in a Docker volume, never modified. Canonical store is *derived* from raw + code.
- **Schema versioning**: every event payload includes `schema_version`. Add now, costs nothing.
- **One Postgres, owned by ledger.** No "DB per service" yet.
- **Event format**: JSON over RabbitMQ for v1. Protobuf comes later.

## Milestone 1 scope

Goal: drop a CSV from the user's bank into a folder, see normalized transactions in the ledger DB, browsable from `web`. **No categorization, no merchant fuzzy matching, no anomaly detection yet.**

Three sub-steps:

### 1. ledger: Postgres + EF Core

Add EF Core to `services/ledger/src/Wyb.Ledger.csproj`:

```bash
cd services/ledger/src
dotnet add package Microsoft.EntityFrameworkCore.Design
# Aspire.Npgsql.EntityFrameworkCore.PostgreSQL is already there
```

Wire EF Core to the Aspire-injected connection:

```csharp
builder.AddNpgsqlDbContext<LedgerDbContext>("ledger-db");
```

(`ledger-db` matches the AppHost: `postgres.AddDatabase("ledger-db")`.)

Create one entity:

```csharp
public class Transaction
{
    public Guid Id { get; set; }                    // app-generated UUID
    public string DedupKey { get; set; } = "";      // sha256 hex, indexed unique
    public DateOnly Date { get; set; }
    public long AmountMinor { get; set; }           // øre
    public string Currency { get; set; } = "DKK";
    public string RawDescription { get; set; } = "";
    public string AccountId { get; set; } = "";
    public DateTime ImportedAt { get; set; }
    public int SchemaVersion { get; set; } = 1;
}
```

Add a unique index on `DedupKey`. Use `dotnet ef migrations add InitialCreate` to scaffold the migration; apply on startup with `db.Database.MigrateAsync()` inside a hosted service or in `Program.cs` after `app.Build()`.

Add three endpoints:
- `POST /transactions` — internal, called by ingest's RabbitMQ consumer or directly by ingest. Idempotent on `DedupKey`.
- `GET /transactions?from=&to=&limit=&offset=` — for the web table.
- Existing `POST /transactions/seed` — keep as a smoke test.

Subscribe to `transaction.imported` queue. On message: compute dedup key, upsert (skip if exists), ack.

### 2. ingest: real CSV parsing

Pick **one** bank — the user's actual one. Don't generalize. Hardcode the column layout.

Add `fsnotify`:

```bash
cd services/ingest
go get github.com/fsnotify/fsnotify
```

Mount a host directory into the container via the AppHost:

```csharp
builder.AddGolangApp("ingest", "../services/ingest")
    .WithHttpEndpoint(env: "PORT")
    .WithReference(rabbit)
    .WaitFor(rabbit)
    .WithBindMount("./drop", "/data/drop")           // user drops CSVs here
    .WithBindMount("./raw", "/data/raw");            // append-only archive
```

Create those two directories at the repo root: `mkdir -p drop raw` (gitignored, except for `.gitkeep`).

Flow per CSV:
1. fsnotify event → file appeared in `/data/drop`
2. Read it, parse rows (`encoding/csv` + a struct matching the bank's columns)
3. Move the original to `/data/raw/<original-filename>` with a timestamp prefix; never modify
4. For each row: build a `transaction.imported` JSON payload, publish to RabbitMQ with the existing trace context

Payload shape:
```json
{
  "schema_version": 1,
  "source_file": "danske-2026-05-export.csv",
  "row_index": 47,
  "account_id": "DK-DANSKE-1234",
  "date": "2026-05-08",
  "amount_minor": -4995,
  "currency": "DKK",
  "raw_description": "MENY VESTERBRO"
}
```

Idempotency lives in ledger — ingest can re-publish freely, ledger dedups.

Add the manual command for re-deriving from raw later (M1.5): a CLI flag `--rebuild` that walks `/data/raw/*` and republishes everything. Worth wiring even as a stub — forces the pipeline to stay re-runnable.

### 3. web: transactions table

A single page. Functional, ugly, scrollable.

`src/routes/transactions/+page.server.ts` — server-side `load` that calls `ledger`'s `GET /transactions` via the Aspire-injected URL (`env.services__ledger__http__0`).

`src/routes/transactions/+page.svelte` — table with date, description, amount (formatted from minor units to DKK with proper signs and locale). Sortable by date; date-range filter optional.

This is the inspection UI. Expect to find a dozen normalization bugs just by scrolling through real data. That's the point.

## What is NOT in M1

- Merchant resolution / normalization service (M2)
- Categorization rules (M3)
- Recurring detection / anomaly scoring (M4)
- Multi-bank support (later)
- Auth (single-user, behind WireGuard for now)
- GoCardless / PSD2 (Phase 2)
- Backup export/import (M5 — but `pg_dump` and tarring `/data/raw` is the floor)

## Testing

- **ledger unit tests** (`Wyb.Ledger.Tests`): dedup key derivation, EF Core entity config. These have invariants worth pinning down.
- **ledger integration tests** (`Wyb.Ledger.IntegrationTests`): Testcontainers Postgres, exercise the upsert path.
- **ingest** (`main_test.go`): one fixture CSV per bank, assert the parsed payloads.
- **integration** (`tests/integration`): `Aspire.Hosting.Testing` boots the full AppHost; assert that dropping a CSV in `drop/` results in N rows in ledger.

Don't write tests for the SvelteKit UI yet.

## Pitfalls already discovered

- `WithNpmPackageInstallation()` doesn't exist in Aspire 13.x — `AddViteApp` installs deps automatically.
- Don't call `WithHttpEndpoint()` on Vite resources — duplicate endpoint error.
- FastAPI: use `lifespan` async context manager, not `@app.on_event`.
- Zsh: quote bracket-spec deps like `'uvicorn[standard]'`.
- VS Code Pylance needs to know about per-service venvs; use a `.code-workspace` file with each service as its own folder.
- SvelteKit OTel needs `NODE_OPTIONS=--import ./otel.js` in the AppHost; the SDK must start before SvelteKit's HTTP server does.
- Aspire injects `ConnectionStrings__rabbit` and `services__ledger__http__0` style env vars — read those, don't hardcode URLs.

## Branch hygiene

One feature per branch. `m1/ledger-ef-core`, `m1/ingest-csv`, `m1/web-transactions-table`. Merge in that order so each branch can verify against working upstream services.