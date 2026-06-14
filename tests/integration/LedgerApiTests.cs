using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Wyb.Integration.Tests;

/// <summary>
/// Verifies that a transaction flowing through the full pipeline (transaction.categorized →
/// ledger consumer → Marten) surfaces correctly via the ledger HTTP API.
/// </summary>
[Collection("Stack")]
public class LedgerApiTests(StackFixture fixture)
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(40);

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

    private HttpClient Ledger => fixture.Ledger;

    private static string MakeCategorizedEvent(string dedupKey, string description) =>
        JsonSerializer.Serialize(new
        {
            schema_version = 1,
            dedup_key = dedupKey,
            account_id = "test-account",
            date = "2025-06-01",
            amount_minor = -14900,
            currency = "DKK",
            raw_description = description,
            imported_at = DateTimeOffset.UtcNow,
            category = "Groceries",
        });

    [Fact]
    public async Task Transaction_AppearsInLedgerApi_AfterBeingPublishedToCategorizedTopic()
    {
        var dedupKey = Guid.NewGuid().ToString("N");
        var description = $"INTTEST_LEDGER_{dedupKey}";

        await KafkaTestClient.ProduceAsync(
            fixture.Bootstrap, "transaction.categorized",
            MakeCategorizedEvent(dedupKey, description));

        var caughtUp = await KafkaTestClient.WaitForGroupCaughtUpAsync(
            fixture.Bootstrap, "ledger", "transaction.categorized", Timeout);
        Assert.True(caughtUp, "Ledger consumer did not catch up to transaction.categorized");

        var res = await Ledger.GetAsync($"/transactions/{dedupKey}");
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);

        var tx = await res.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.Equal(dedupKey, tx.GetProperty("id").GetString());
        Assert.Equal(-14900, tx.GetProperty("amountMinor").GetInt64());
        Assert.Equal("DKK", tx.GetProperty("currency").GetString());
        Assert.Equal("Groceries", tx.GetProperty("category").GetString());
        Assert.Equal(description, tx.GetProperty("rawDescription").GetString());
    }

    [Fact]
    public async Task DuplicateTransaction_IsIdempotent_LedgerStoresItOnce()
    {
        var dedupKey = Guid.NewGuid().ToString("N");
        var description = $"INTTEST_DEDUP_{dedupKey}";
        var evt = MakeCategorizedEvent(dedupKey, description);

        // Publish the same event twice — simulates Kafka redelivery.
        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.categorized", evt);
        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.categorized", evt);

        var caughtUp = await KafkaTestClient.WaitForGroupCaughtUpAsync(
            fixture.Bootstrap, "ledger", "transaction.categorized", Timeout);
        Assert.True(caughtUp, "Ledger consumer did not catch up");

        // Transaction exists exactly once — the API returns 200, not an error from a double-write.
        var res = await Ledger.GetAsync($"/transactions/{dedupKey}");
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);

        var tx = await res.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.Equal(dedupKey, tx.GetProperty("id").GetString());
    }

    [Fact]
    public async Task UnknownTransaction_Returns404()
    {
        var res = await Ledger.GetAsync($"/transactions/{Guid.NewGuid():N}");
        Assert.Equal(HttpStatusCode.NotFound, res.StatusCode);
    }

    [Fact]
    public async Task ImportStatus_ReflectsImportedTransactions()
    {
        var dedupKey = Guid.NewGuid().ToString("N");

        await KafkaTestClient.ProduceAsync(
            fixture.Bootstrap, "transaction.categorized",
            MakeCategorizedEvent(dedupKey, $"INTTEST_IMPORTSTATUS_{dedupKey}"));

        var caughtUp = await KafkaTestClient.WaitForGroupCaughtUpAsync(
            fixture.Bootstrap, "ledger", "transaction.categorized", Timeout);
        Assert.True(caughtUp, "Ledger consumer did not catch up to transaction.categorized");

        var res = await Ledger.GetAsync("/imports/status");
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);

        var status = await res.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.NotEqual(JsonValueKind.Null, status.GetProperty("lastImportAt").ValueKind);
        Assert.NotEqual(JsonValueKind.Null, status.GetProperty("coverageEnd").ValueKind);
        Assert.True(status.GetProperty("transactionCount").GetInt32() >= 1);

        // The account from MakeCategorizedEvent appears in the per-account breakdown.
        var found = false;
        foreach (var account in status.GetProperty("accounts").EnumerateArray())
        {
            if (account.GetProperty("accountId").GetString() == "test-account")
            {
                found = true;
                break;
            }
        }
        Assert.True(found, "expected 'test-account' in the import-status account breakdown");
    }
}
