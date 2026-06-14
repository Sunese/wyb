using Wyb.Ledger.Data;

namespace Wyb.Ledger;

/// <summary>
/// Import freshness derived from the canonical transaction set, surfaced so the UI can
/// nudge the user to re-import before stale data starts looking like missing charges.
/// <c>CoverageEnd</c> is the latest transaction date we hold (how far our data reaches);
/// <c>LastImportAt</c> is the wall-clock time of the most recent import.
/// </summary>
public sealed record ImportStatusResponse(
    DateTimeOffset? LastImportAt,
    DateOnly? CoverageEnd,
    int? DaysSinceLastImport,
    int TransactionCount,
    IReadOnlyList<AccountImportStatus> Accounts)
{
    /// <summary>
    /// Builds the import-status summary from all stored transactions.
    /// <paramref name="now"/> is injectable so the staleness window is deterministic in tests.
    /// </summary>
    public static ImportStatusResponse From(IReadOnlyCollection<Transaction> transactions, DateTimeOffset now)
    {
        var accounts = transactions
            .GroupBy(t => t.AccountId)
            .Select(g => AccountImportStatus.From(g.Key, g.ToList(), now))
            .OrderBy(a => a.AccountId ?? string.Empty, StringComparer.Ordinal)
            .ToList();

        var overall = AccountImportStatus.From(null, transactions, now);
        return new ImportStatusResponse(
            overall.LastImportAt,
            overall.CoverageEnd,
            overall.DaysSinceLastImport,
            transactions.Count,
            accounts);
    }
}

/// <summary>Import freshness for a single account (or the whole ledger when AccountId is null).</summary>
public sealed record AccountImportStatus(
    string? AccountId,
    DateTimeOffset? LastImportAt,
    DateOnly? CoverageEnd,
    int? DaysSinceLastImport,
    int TransactionCount)
{
    public static AccountImportStatus From(
        string? accountId, IReadOnlyCollection<Transaction> rows, DateTimeOffset now)
    {
        if (rows.Count == 0)
            return new AccountImportStatus(accountId, null, null, null, 0);

        var lastImportAt = rows.Max(t => t.ImportedAt);
        var coverageEnd = rows.Max(t => t.Date);
        var daysSince = (int)Math.Floor((now - lastImportAt).TotalDays);
        return new AccountImportStatus(accountId, lastImportAt, coverageEnd, daysSince, rows.Count);
    }
}
