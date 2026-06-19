# Roadmap

## Foundation phase

- M1: CSV ingest, basic ledger, transactions table
  ✅ Complete.

- (✅ Complete) M2: Categorization (rules + manual) + merchant resolution.
  - Rule engine, manual override, "apply retroactively."
  - Canonicalize merchants (MENY VESTERBRO + MENY ØSTERBRO → MENY).
  - Almost everything downstream depends on clean merchants.

- M3: Subscription management. Detect recurring charges. List with
  current amount, cadence, annual total. Flag price changes and
  missing expected charges. First "killer feature."
  - TODO: Subscription detail view — clicking a subscription reveals the
    full history of charges from that merchant (date + amount per
    occurrence), making price-change timeline and missed charges obvious.

- M4: Anomaly detection + home dashboard. Per-category baselines
  with seasonality. "What changed this month." The "quiet month"
  verdict. End state: the thesis works.

## Shippable phase

- M5: Notifications + export + polish. ntfy + email.
  - Per-event preferences
  - CSV/XLSX/JSON export and backup import.
  - Starter Danish merchant rule pack.
  - End state: someone other than the user could install it.

- M6: Forecasting + cashflow shape.
  - Project balance forward using detected recurring + baseline spend.
  - Low-balance warnings.
  - Behavioral pattern detection (day-of-week, day-of-month, post-salary burst).

- M7: Cross-period diffs + merchant intelligence.
  - Comparison views ("this Q1 vs last Q1").
  - sPer-merchant deep-dive pages.
  - Merchant outlier detection.

- M8: Annual retrospective + counterfactual queries.
  - Auto-generated year/quarter reports.
  - "What if Netflix neverexisted" exploration.

## Self-hostable phase

- M9: Excellent CSV/XLSX ingestion + optional PSD2 sync.
  - The big bet: make manual import feel almost as good as auto-sync, then let auto-sync be an opt-in extra rather than the spine of the product.
  - Core work:
    - Per-bank format autodetection on upload (Danske, Nordea, Jyske, Sydbank, Lunar, Revolut to start). Parsers are
      plugins, versioned, with golden-file tests.
    - First-time-import wizard in the web UI: pick your bank,
      get a screenshotted walkthrough of where to tap in that
      bank's app/web, drag the file in.
    - Deep links into bank apps where the OS supports them (e.g. `danskebank://`).
    - Import-cadence health: "last import was N days ago"
      indicator on the dashboard, optional ntfy/email reminder
      on a user-set cadence (weekly default).
    - Smart dedup against re-imports: if the user exports
      overlapping ranges, the dedup key handles it.
    - Import lag awareness in detectors: M3/M4 features must
      reason about how stale data is before alerting.
    - `wyb-import` CLI for users who want to script imports from
      emailed statements or scheduled downloads.
  - Optional power-user path:
    - `aisp` service (alongside `ingest`) wrapping Enable
      Banking's API and emitting the same Kafka events as
      CSV ingest. Same schema_version discipline. The ledger
      doesn't care which source produced an event.
    - Gated behind explicit per-user config: the user signs up
      at Enable Banking themselves, creates a restricted
      production application, links their own accounts, and
      provides credentials to their WYB instance.
    - Session metadata (session_id, ASPSP, valid_until)
      persisted so the UI can show "Nordea connection expires
      in 12 days - reconnect." strategy=longest on first sync, strategy=default for
      incremental. PSU headers sent when sync is user-triggered. Documented as advanced/optional. The default install does
      not require it.

  - End state: WYB is fully usable indefinitely with zero
    third-party service dependencies, and the people who want
    auto-sync can have it on their own terms.

- M10: Multi-user / households + mobile PWA.
  - Joint vs. personal accounts, permission model.
  - Mobile-first PWA polish.
  - The regulatory framing here is: each household member's accounts
    are imported by them, for them.
  - If using auto-sync, each member brings their own Enable Banking app.

- M11: Investments + pension + net worth view.
  -Manual entries, holistic financial picture.

- M12+: Smarter analytics.
  - ML categorization, embedding-based merchant clustering, better anomaly models, ranked alert prioritization.
