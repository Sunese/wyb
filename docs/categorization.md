# Categorization

WYB categorizes transactions automatically when they are imported. The `categorize` service listens for `transaction.imported` events on Kafka, applies rules and merchant aliases, then publishes `transaction.categorized` with an added `category` (and optionally `merchant_name`).

Rules and merchants are stored in the `rules` service (Postgres, `rules-db`) and exposed over HTTP. `categorize` fetches them fresh on every message.

## Two-layer system

### Layer 1 — Category rules

A rule matches a raw transaction description and maps it to a category.

| Field | Description |
|---|---|
| `name` | Human-readable label |
| `pattern` | The string (or regex) to match against |
| `matchType` | `Contains`, `Exact`, `StartsWith`, or `Regex` |
| `category` | The category to assign |
| `priority` | Lower number = evaluated first. First match wins. |

Rules are the **broad-stroke catch-alls**: "anything with MobilePay in the description is a Transfer."

### Layer 2 — Merchants and aliases

A merchant has a canonical name, an optional default category, and one or more aliases. Each alias is a `pattern + matchType` that matches raw descriptions to that merchant.

| Field | Description |
|---|---|
| `canonicalName` | Normalized merchant name shown in the UI |
| `defaultCategory` | Category to use if no rule matched |
| aliases | One or more `{ pattern, matchType }` entries |

Merchants solve the **name normalization problem**: Danske Bank shows "Rema 1000 Nørre", "Rema 1000 Valby", etc. A single merchant with a `StartsWith` alias on `"Rema 1000"` maps all variants to the canonical name and a single default category.

### Precedence

1. Evaluate all rules sorted by priority (ascending). First match wins — its `category` is used.
2. If no rule matched, check merchant aliases. If one matches and has a `defaultCategory`, use it.
3. Otherwise → `"Uncategorized"`.

Rules override merchant defaults. This is intentional: you can write a high-priority rule for a specific description that overrides the merchant's default.

### Match types

| Type | Behaviour |
|---|---|
| `Contains` | Case-insensitive substring match |
| `Exact` | Case-insensitive full string equality |
| `StartsWith` | Case-insensitive prefix match |
| `Regex` | `re.search(pattern, text, IGNORECASE)` |

All matching is case-insensitive for `Contains`, `Exact`, and `StartsWith`. For `Regex`, the pattern is passed to Python's `re.search` with `IGNORECASE`.

## API

The `rules` service exposes a REST API (OpenAPI docs at `/docs` when running):

```
GET    /rules                          List all rules (ordered by priority)
POST   /rules                          Create a rule
DELETE /rules/{id}                     Delete a rule

GET    /merchants                      List all merchants with their aliases
POST   /merchants                      Create a merchant
DELETE /merchants/{id}                 Delete a merchant (cascades aliases)
POST   /merchants/{id}/aliases         Add an alias to a merchant
DELETE /aliases/{id}                   Delete a single alias
```

## Seed data

`services/rules/seed.json` contains a starter set of rules and merchants for Danske Bank. The `rules` service loads it automatically on first boot if the database is empty — no manual steps needed.

To add more seeds, edit `seed.json` and reset `rules-db` so the service re-seeds on next startup (or add the entries via the API directly — the seed only runs once on an empty DB).

## Design notes

- Rules win over merchant defaults. Use rules for patterns you want to force into a specific category regardless of merchant.
- Merchant `defaultCategory` is the fallback when no rule fires. Useful for stores where the category is always the same but the description varies.
- There is no update endpoint — delete and recreate to change a rule. This keeps the audit trail simple.
- Categories are free-form strings. Pick a small set and be consistent (e.g. `Groceries`, `Dining`, `Transport`, `Transfer`, `Subscriptions`, `Health`, `Home`, `Travel`, `Auto`).
- When a transaction description is ambiguous (e.g. "MobilePay Rejsekort"), a higher-priority exact or StartsWith rule for that specific string can override the generic MobilePay→Transfer rule.
