using Wyb.Ledger.Data;

namespace Wyb.Ledger.Tests;

public class ImportStatusTests
{
    private static readonly DateTimeOffset Now = new(2026, 6, 14, 12, 0, 0, TimeSpan.Zero);

    private static Transaction Tx(string account, DateOnly date, DateTimeOffset importedAt) =>
        new(
            Id: Guid.NewGuid().ToString("N"),
            Date: date,
            AmountMinor: -1000,
            Currency: "DKK",
            RawDescription: "test",
            ImportedAt: importedAt,
            Category: default,
            SchemaVersion: 1,
            AccountId: account);

    [Fact]
    public void From_empty_reports_no_coverage()
    {
        var status = ImportStatusResponse.From(Array.Empty<Transaction>(), Now);

        Assert.Null(status.LastImportAt);
        Assert.Null(status.CoverageEnd);
        Assert.Null(status.DaysSinceLastImport);
        Assert.Equal(0, status.TransactionCount);
        Assert.Empty(status.Accounts);
    }

    [Fact]
    public void From_reports_latest_coverage_and_import_overall()
    {
        var txs = new[]
        {
            Tx("a", new DateOnly(2026, 5, 1), Now.AddDays(-30)),
            Tx("a", new DateOnly(2026, 5, 20), Now.AddDays(-10)), // latest import and coverage
            Tx("b", new DateOnly(2026, 4, 15), Now.AddDays(-20)),
        };

        var status = ImportStatusResponse.From(txs, Now);

        Assert.Equal(Now.AddDays(-10), status.LastImportAt);
        Assert.Equal(new DateOnly(2026, 5, 20), status.CoverageEnd);
        Assert.Equal(10, status.DaysSinceLastImport);
        Assert.Equal(3, status.TransactionCount);
    }

    [Fact]
    public void From_breaks_down_per_account()
    {
        var txs = new[]
        {
            Tx("a", new DateOnly(2026, 5, 1), Now.AddDays(-30)),
            Tx("a", new DateOnly(2026, 5, 20), Now.AddDays(-10)),
            Tx("b", new DateOnly(2026, 4, 15), Now.AddDays(-20)),
        };

        var status = ImportStatusResponse.From(txs, Now);

        var a = status.Accounts.Single(x => x.AccountId == "a");
        Assert.Equal(new DateOnly(2026, 5, 20), a.CoverageEnd);
        Assert.Equal(10, a.DaysSinceLastImport);
        Assert.Equal(2, a.TransactionCount);

        var b = status.Accounts.Single(x => x.AccountId == "b");
        Assert.Equal(new DateOnly(2026, 4, 15), b.CoverageEnd);
        Assert.Equal(20, b.DaysSinceLastImport);
        Assert.Equal(1, b.TransactionCount);
    }
}
