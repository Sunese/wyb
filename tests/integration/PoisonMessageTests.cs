using System.Text.Json;

namespace Wyb.Integration.Tests;

/// <summary>
/// Kafka has no dead-letter queue; resilience instead means a malformed message
/// must not wedge a consumer. We publish garbage to transaction.imported, then a valid event,
/// and assert categorize still enriches the valid one — i.e. it skipped the poison
/// and kept processing.
/// </summary>
[Collection("Stack")]
public class PoisonMessageTests(StackFixture fixture)
{
    [Fact]
    public async Task PoisonMessage_DoesNotWedge_Categorize()
    {
        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.imported", "not valid json {{{{");

        var description = $"INTTEST_POISON_{Guid.NewGuid():N}";
        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.imported", JsonSerializer.Serialize(new
        {
            schema_version = 1,
            source_file = "integration-test.csv",
            row_index = 0,
            account_id = "test-account",
            date = "2025-01-01",
            amount_minor = -9900,
            currency = "DKK",
            raw_description = description,
        }));

        var result = await KafkaTestClient.ConsumeMatchingAsync(
            fixture.Bootstrap, "transaction.categorized",
            json => json.TryGetProperty("raw_description", out var d) && d.GetString() == description,
            TimeSpan.FromSeconds(30));

        Assert.NotNull(result);
        Assert.Equal("Uncategorized", result.Value.GetProperty("category").GetString());
    }
}
