using JasperFx;
using JasperFx.Events;
using Marten;
using Testcontainers.PostgreSql;
using Weasel.Core;
using Wyb.Ledger;
using Wyb.Ledger.Data;
using Wyb.Ledger.Events;

namespace Wyb.Ledger.IntegrationTests;

public class TransactionConsumerTests : IAsyncLifetime
{
    private readonly PostgreSqlContainer _postgres = new PostgreSqlBuilder("postgres:16-alpine").Build();

    private IDocumentStore _store = null!;

    public async Task InitializeAsync()
    {
        await _postgres.StartAsync();

        _store = DocumentStore.For(opts =>
        {
            opts.Connection(_postgres.GetConnectionString());
            opts.DatabaseSchemaName = "events";
            opts.Events.StreamIdentity = StreamIdentity.AsString;
            opts.UseSystemTextJsonForSerialization(enumStorage: EnumStorage.AsString);
            opts.AutoCreateSchemaObjects = AutoCreate.All;
        });
    }

    public async Task DisposeAsync()
    {
        await _store.DisposeAsync();
        await _postgres.DisposeAsync();
    }

    private static TransactionRecorded MakeEvent(string? dedupKey = null) => new(
        DedupKey: dedupKey ?? Guid.NewGuid().ToString("N"),
        Date: new DateOnly(2025, 1, 1),
        AmountMinor: -9900,
        Currency: "DKK",
        RawDescription: "NETTO TESTBUTIK",
        ImportedAt: DateTimeOffset.UtcNow,
        Category: TransactionCategory.Groceries,
        SchemaVersion: 1);

    [Fact]
    public async Task RecordTransaction_HappyPath_CreatesStream()
    {
        var evt = MakeEvent();

        var recorded = await TransactionConsumer.RecordTransactionAsync(_store, evt);

        Assert.True(recorded);
        await using var session = _store.LightweightSession();
        var state = await session.Events.FetchStreamStateAsync(evt.DedupKey);
        Assert.NotNull(state);
        Assert.Equal(1, state.Version);
    }

    [Fact]
    public async Task RecordTransaction_HappyPath_AggregatesCorrectly()
    {
        var evt = MakeEvent();

        await TransactionConsumer.RecordTransactionAsync(_store, evt);

        await using var session = _store.LightweightSession();
        var tx = await session.Events.AggregateStreamAsync<Transaction>(evt.DedupKey);
        Assert.NotNull(tx);
        Assert.Equal(evt.DedupKey, tx.Id);
        Assert.Equal(evt.AmountMinor, tx.AmountMinor);
        Assert.Equal(evt.Currency, tx.Currency);
        Assert.Equal(evt.Category, tx.Category);
        Assert.Equal(evt.RawDescription, tx.RawDescription);
        Assert.False(tx.CategoryOverridden);
    }

    [Fact]
    public async Task RecordTransaction_DuplicateDedupKey_IsSkipped()
    {
        var evt = MakeEvent();

        var first = await TransactionConsumer.RecordTransactionAsync(_store, evt);
        var second = await TransactionConsumer.RecordTransactionAsync(_store, evt);

        Assert.True(first);
        Assert.False(second);

        // Exactly one event in the stream — not two.
        await using var session = _store.LightweightSession();
        var state = await session.Events.FetchStreamStateAsync(evt.DedupKey);
        Assert.Equal(1, state!.Version);
    }

    [Fact]
    public async Task RecordTransaction_DifferentDedupKeys_BothPersist()
    {
        var a = MakeEvent();
        var b = MakeEvent();

        await TransactionConsumer.RecordTransactionAsync(_store, a);
        await TransactionConsumer.RecordTransactionAsync(_store, b);

        await using var session = _store.LightweightSession();
        Assert.NotNull(await session.Events.FetchStreamStateAsync(a.DedupKey));
        Assert.NotNull(await session.Events.FetchStreamStateAsync(b.DedupKey));
    }

    [Fact]
    public async Task CategoryOverridden_UpdatesProjectionAndSetsFlag()
    {
        var evt = MakeEvent();
        await TransactionConsumer.RecordTransactionAsync(_store, evt);

        await using var session = _store.LightweightSession();
        session.Events.Append(evt.DedupKey, new Wyb.Ledger.Events.CategoryOverridden(evt.DedupKey, TransactionCategory.Beer));
        await session.SaveChangesAsync();

        var tx = await session.Events.AggregateStreamAsync<Transaction>(evt.DedupKey);
        Assert.NotNull(tx);
        Assert.Equal(TransactionCategory.Beer, tx.Category);
        Assert.True(tx.CategoryOverridden);
    }

    [Fact]
    public async Task ImportedAt_IsPreservedInProjection()
    {
        var importedAt = new DateTimeOffset(2026, 6, 18, 10, 0, 0, TimeSpan.Zero);
        var evt = MakeEvent() with { ImportedAt = importedAt };

        await TransactionConsumer.RecordTransactionAsync(_store, evt);

        await using var session = _store.LightweightSession();
        var tx = await session.Events.AggregateStreamAsync<Transaction>(evt.DedupKey);
        Assert.NotNull(tx);
        Assert.Equal(importedAt, tx.ImportedAt);
    }
}
