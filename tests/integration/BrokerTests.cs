using System.Text.Json;

namespace Wyb.Integration.Tests;

/// <summary>
/// Baseline broker connectivity: the Kafka container accepts a produce and serves
/// it back, and the Go ingest service can publish to Kafka (via its /ping → pong).
/// </summary>
[Collection("Stack")]
public class BrokerTests(StackFixture fixture)
{
    [Fact]
    public async Task Broker_RoundTrips_AProducedMessage()
    {
        var topic = $"itest-roundtrip-{Guid.NewGuid():N}";
        var marker = Guid.NewGuid().ToString("N");

        await KafkaTestClient.ProduceAsync(fixture.Bootstrap, topic,
            JsonSerializer.Serialize(new { marker }));

        var result = await KafkaTestClient.ConsumeMatchingAsync(
            fixture.Bootstrap, topic,
            json => json.TryGetProperty("marker", out var m) && m.GetString() == marker,
            TimeSpan.FromSeconds(15));

        Assert.NotNull(result);
        Assert.Equal(marker, result.Value.GetProperty("marker").GetString());
    }

    [Fact]
    public async Task Ingest_Ping_PublishesPongToKafka()
    {
        // The Go ingest service publishes a pong event to my-topic on /ping.
        var res = await fixture.Ingest.GetAsync("/ping");
        res.EnsureSuccessStatusCode();

        var result = await KafkaTestClient.ConsumeMatchingAsync(
            fixture.Bootstrap, "my-topic",
            json => json.TryGetProperty("message", out var m) && m.GetString() == "pong",
            TimeSpan.FromSeconds(15));

        Assert.NotNull(result);
        Assert.Equal("pong", result.Value.GetProperty("message").GetString());
    }
}
