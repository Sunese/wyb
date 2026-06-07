using System.Text.Json;

namespace Wyb.Integration.Tests;

/// <summary>
/// Verifies the consuming services actually drain their topics, using only broker
/// state (committed consumer-group offsets) — no test hooks in the service code.
///
/// detect consumes <c>transaction.categorized</c> (group "detect"); ledger consumes
/// <c>transaction.categorized</c> (group "my-group").
/// </summary>
[Collection("Stack")]
public class ConsumerGroupTests(StackFixture fixture)
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(40);

    [Fact]
    public async Task Detect_Consumes_FromCategorized()
    {
        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.categorized",
            JsonSerializer.Serialize(new { marker = Guid.NewGuid().ToString("N") }));

        var caughtUp = await KafkaTestClient.WaitForGroupCaughtUpAsync(
            fixture.Bootstrap, "detect", "transaction.categorized", Timeout);

        Assert.True(caughtUp, "detect consumer group did not catch up to transaction.categorized");
    }

    [Fact]
    public async Task Ledger_Consumes_FromCategorizedTopic()
    {
        // Drive a message through categorize so transaction.categorized has data,
        // then confirm the ledger's consumer group drained it.
        var description = $"INTTEST_LEDGER_{Guid.NewGuid():N}";
        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.categorized", MakeEvent(description));

        var enriched = await KafkaTestClient.ConsumeMatchingAsync(
            fixture.Bootstrap, "transaction.categorized",
            json => json.TryGetProperty("raw_description", out var d) && d.GetString() == description,
            Timeout);
        Assert.NotNull(enriched);

        var caughtUp = await KafkaTestClient.WaitForGroupCaughtUpAsync(
            fixture.Bootstrap, "ledger", "transaction.categorized", Timeout);

        Assert.True(caughtUp, "ledger consumer group did not catch up to transaction.categorized");
    }

    private static string MakeEvent(string description) => JsonSerializer.Serialize(new
    {
        schema_version = 1,
        source_file = "integration-test.csv",
        row_index = 0,
        account_id = "test-account",
        date = "2025-01-01",
        amount_minor = -9900,
        currency = "DKK",
        raw_description = description,
    });
}
