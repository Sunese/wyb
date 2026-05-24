using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;

namespace Wyb.Integration.Tests;

/// <summary>
/// End-to-end event flow tests: seed rules/merchants via the categorize HTTP API,
/// publish a transaction.imported event, then consume from transaction.categorized
/// and assert the enriched payload.
///
/// Each test binds its own exclusive temp queue to transaction.categorized so
/// messages from different tests don't cross-contaminate.
/// </summary>
[Collection("Categorize")]
public class CategorizationFlowTests(CategorizeFixture fixture)
{
    private readonly HttpClient _http = fixture.CategorizeHttp;
    private readonly IConnection _rabbit = fixture.Rabbit;

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

    /// <summary>
    /// Publishes one transaction.imported event and waits up to <paramref name="timeoutMs"/>
    /// for a matching message to arrive on <paramref name="queueName"/>.
    /// Returns the parsed JSON payload, or null if nothing arrived in time.
    /// </summary>
    private async Task<JsonElement?> PublishAndConsumeAsync(
        IChannel channel, string queueName, object eventPayload, int timeoutMs = 8_000)
    {
        var tcs = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        var consumer = new AsyncEventingBasicConsumer(channel);
        consumer.ReceivedAsync += (_, ea) =>
        {
            var json = JsonSerializer.Deserialize<JsonElement>(ea.Body.Span);
            tcs.TrySetResult(json);
            return Task.CompletedTask;
        };
        await channel.BasicConsumeAsync(queueName, autoAck: true, consumer: consumer);

        var body = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(eventPayload));
        await channel.BasicPublishAsync("transaction.imported", routingKey: "", body: body);

        using var cts = new CancellationTokenSource(timeoutMs);
        cts.Token.Register(() => tcs.TrySetCanceled());
        try { return await tcs.Task; }
        catch (OperationCanceledException) { return null; }
    }

    private static object MakeEvent(string description) => new
    {
        schema_version = 1,
        source_file = "integration-test.csv",
        row_index = 0,
        account_id = "test-account",
        date = "2025-01-01",
        amount_minor = -9900,
        currency = "DKK",
        raw_description = description,
    };

    [Fact]
    public async Task ImportedTransaction_WithMatchingRule_IsAssignedCorrectCategory()
    {
        // Use a unique pattern to avoid collisions with other tests' rules.
        var marker = $"INTTEST_RULE_{Guid.NewGuid():N}";

        var rulePost = await _http.PostAsJsonAsync("/rules", new
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
            using var channel = await _rabbit.CreateChannelAsync();
            await channel.ExchangeDeclareAsync("transaction.categorized", "fanout", durable: true, autoDelete: false);
            await channel.ExchangeDeclareAsync("transaction.imported", "fanout", durable: true, autoDelete: false);
            var q = await channel.QueueDeclareAsync(queue: "", durable: false, exclusive: true, autoDelete: true);
            await channel.QueueBindAsync(q.QueueName, "transaction.categorized", "");

            var result = await PublishAndConsumeAsync(channel, q.QueueName, MakeEvent($"Buy {marker} premium"));

            Assert.NotNull(result);
            Assert.Equal("Subscriptions", result.Value.GetProperty("category").GetString());
        }
        finally
        {
            await _http.DeleteAsync($"/rules/{ruleId}");
        }
    }

    [Fact]
    public async Task ImportedTransaction_WithMerchantAlias_HasMerchantNameEnriched()
    {
        var marker = $"INTTEST_MERCHANT_{Guid.NewGuid():N}";
        var canonicalName = $"Merchant_{marker}";

        var merchantPost = await _http.PostAsJsonAsync("/merchants",
            new { canonicalName, defaultCategory = "Shopping" }, Json);
        merchantPost.EnsureSuccessStatusCode();
        var merchantId = (await merchantPost.Content.ReadFromJsonAsync<JsonElement>(Json)).GetProperty("id").GetString();
        await _http.PostAsJsonAsync($"/merchants/{merchantId}/aliases",
            new { pattern = marker, matchType = "Contains" }, Json);

        try
        {
            using var channel = await _rabbit.CreateChannelAsync();
            await channel.ExchangeDeclareAsync("transaction.categorized", "fanout", durable: true, autoDelete: false);
            await channel.ExchangeDeclareAsync("transaction.imported", "fanout", durable: true, autoDelete: false);
            var q = await channel.QueueDeclareAsync(queue: "", durable: false, exclusive: true, autoDelete: true);
            await channel.QueueBindAsync(q.QueueName, "transaction.categorized", "");

            var result = await PublishAndConsumeAsync(channel, q.QueueName, MakeEvent($"Purchase at {marker} store"));

            Assert.NotNull(result);
            Assert.Equal(canonicalName, result.Value.GetProperty("merchant_name").GetString());
            // No explicit rule — merchant default category applies
            Assert.Equal("Shopping", result.Value.GetProperty("category").GetString());
        }
        finally
        {
            await _http.DeleteAsync($"/merchants/{merchantId}");
        }
    }

    [Fact]
    public async Task ImportedTransaction_WithNoMatchingRules_IsUncategorized()
    {
        var description = $"COMPLETELY_UNKNOWN_{Guid.NewGuid():N}";

        using var channel = await _rabbit.CreateChannelAsync();
        await channel.ExchangeDeclareAsync("transaction.categorized", "fanout", durable: true, autoDelete: false);
        await channel.ExchangeDeclareAsync("transaction.imported", "fanout", durable: true, autoDelete: false);
        var q = await channel.QueueDeclareAsync(queue: "", durable: false, exclusive: true, autoDelete: true);
        await channel.QueueBindAsync(q.QueueName, "transaction.categorized", "");

        var result = await PublishAndConsumeAsync(channel, q.QueueName, MakeEvent(description));

        Assert.NotNull(result);
        Assert.Equal("Uncategorized", result.Value.GetProperty("category").GetString());
    }
}
