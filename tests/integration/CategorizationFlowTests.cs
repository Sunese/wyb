using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Wyb.Integration.Tests;

/// <summary>
/// End-to-end event flow over Kafka: seed rules/merchants via the rules HTTP API,
/// publish a transaction.imported event to <c>transaction.imported</c>, then read the enriched
/// result categorize republishes to <c>transaction.categorized</c>.
///
/// Each test uses a unique marker in the description so concurrent tests don't
/// cross-contaminate (the reader filters the topic by that marker).
/// </summary>
[Collection("Stack")]
public class CategorizationFlowTests(StackFixture fixture)
{
    private const string OutTopic = "transaction.categorized";
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(30);

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

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

    private Task<JsonElement?> ConsumeEnrichedFor(string description) =>
        KafkaTestClient.ConsumeMatchingAsync(
            fixture.Bootstrap, OutTopic,
            json => json.TryGetProperty("raw_description", out var d) && d.GetString() == description,
            Timeout);

    [Fact]
    public async Task ImportedTransaction_WithMatchingRule_IsAssignedCorrectCategory()
    {
        var marker = $"INTTEST_RULE_{Guid.NewGuid():N}";
        var description = $"Buy {marker} premium";

        var rulePost = await fixture.Rules.PostAsJsonAsync("/rules", new
        {
            name = "Integration test rule",
            pattern = marker,
            matchType = "Contains",
            category = "Subscriptions",
            priority = 1,
        }, Json);
        rulePost.EnsureSuccessStatusCode();
        var ruleId = (await rulePost.Content.ReadFromJsonAsync<JsonElement>(Json)).GetProperty("id").GetString();

        try
        {
            await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.imported", MakeEvent(description));

            var result = await ConsumeEnrichedFor(description);

            Assert.NotNull(result);
            Assert.Equal("Subscriptions", result.Value.GetProperty("category").GetString());
        }
        finally
        {
            await fixture.Rules.DeleteAsync($"/rules/{ruleId}");
        }
    }

    [Fact]
    public async Task ImportedTransaction_WithMerchantAlias_HasMerchantNameEnriched()
    {
        var marker = $"INTTEST_MERCHANT_{Guid.NewGuid():N}";
        var canonicalName = $"Merchant_{marker}";
        var description = $"Purchase at {marker} store";

        var merchantPost = await fixture.Rules.PostAsJsonAsync("/merchants",
            new { canonicalName, defaultCategory = "Shopping" }, Json);
        merchantPost.EnsureSuccessStatusCode();
        var merchantId = (await merchantPost.Content.ReadFromJsonAsync<JsonElement>(Json)).GetProperty("id").GetString();
        await fixture.Rules.PostAsJsonAsync($"/merchants/{merchantId}/aliases",
            new { pattern = marker, matchType = "Contains" }, Json);

        try
        {
            await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.imported", MakeEvent(description));

            var result = await ConsumeEnrichedFor(description);

            Assert.NotNull(result);
            Assert.Equal(canonicalName, result.Value.GetProperty("merchant_name").GetString());
            // No explicit rule — merchant default category applies.
            Assert.Equal("Shopping", result.Value.GetProperty("category").GetString());
        }
        finally
        {
            await fixture.Rules.DeleteAsync($"/merchants/{merchantId}");
        }
    }

    [Fact]
    public async Task ImportedTransaction_WithNoMatchingRules_IsUncategorized()
    {
        var description = $"COMPLETELY_UNKNOWN_{Guid.NewGuid():N}";

        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, "transaction.imported", MakeEvent(description));

        var result = await ConsumeEnrichedFor(description);

        Assert.NotNull(result);
        Assert.Equal("Uncategorized", result.Value.GetProperty("category").GetString());
    }
}
