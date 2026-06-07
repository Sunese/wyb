using System.Text.Json;
using Confluent.Kafka;
using Confluent.Kafka.Admin;

namespace Wyb.Integration.Tests;

/// <summary>
/// Thin Kafka helpers for the integration tests — a producer, a "consume until a
/// matching message appears" reader, and consumer-group offset inspection so we
/// can prove a service consumed without instrumenting its production code.
/// </summary>
public static class KafkaTestClient
{
    public static async Task ProduceAsync(string bootstrap, string topic, string value)
    {
        var config = new ProducerConfig { BootstrapServers = bootstrap, AllowAutoCreateTopics = true };
        using var producer = new ProducerBuilder<Null, string>(config).Build();
        await producer.ProduceAsync(topic, new Message<Null, string> { Value = value });
        producer.Flush(TimeSpan.FromSeconds(10));
    }

    /// <summary>
    /// Reads <paramref name="topic"/> from the beginning (with a throwaway consumer
    /// group) and returns the first message whose deserialized JSON satisfies
    /// <paramref name="match"/>, or null if none arrives within <paramref name="timeout"/>.
    /// </summary>
    public static Task<JsonElement?> ConsumeMatchingAsync(
        string bootstrap, string topic, Func<JsonElement, bool> match, TimeSpan timeout)
    {
        return Task.Run(() =>
        {
            var config = new ConsumerConfig
            {
                BootstrapServers = bootstrap,
                GroupId = $"itest-{Guid.NewGuid():N}",
                AutoOffsetReset = AutoOffsetReset.Earliest,
                EnableAutoCommit = false,
            };

            using var consumer = new ConsumerBuilder<Ignore, string>(config).Build();
            consumer.Subscribe(topic);
            using var cts = new CancellationTokenSource(timeout);
            try
            {
                while (!cts.IsCancellationRequested)
                {
                    var cr = consumer.Consume(TimeSpan.FromMilliseconds(500));
                    if (cr?.Message?.Value is null) continue;

                    JsonElement json;
                    try { json = JsonSerializer.Deserialize<JsonElement>(cr.Message.Value); }
                    catch (JsonException) { continue; }

                    if (match(json)) return (JsonElement?)json;
                }
            }
            catch (OperationCanceledException) { }
            finally { consumer.Close(); }

            return (JsonElement?)null;
        });
    }

    /// <summary>
    /// Waits until the consumer group <paramref name="group"/> has committed offsets
    /// that cover every message currently in <paramref name="topic"/> — i.e. the group
    /// has caught up. Proves the owning service consumed, via broker state only.
    /// </summary>
    public static async Task<bool> WaitForGroupCaughtUpAsync(
        string bootstrap, string group, string topic, TimeSpan timeout)
    {
        using var admin = new AdminClientBuilder(new AdminClientConfig { BootstrapServers = bootstrap }).Build();
        using var consumer = new ConsumerBuilder<Ignore, Ignore>(
            new ConsumerConfig { BootstrapServers = bootstrap, GroupId = $"itest-wm-{Guid.NewGuid():N}" }).Build();

        var partitions = admin.GetMetadata(topic, TimeSpan.FromSeconds(10))
            .Topics[0].Partitions
            .Select(p => new TopicPartition(topic, new Partition(p.PartitionId)))
            .ToList();

        long end = partitions.Sum(tp =>
            consumer.QueryWatermarkOffsets(tp, TimeSpan.FromSeconds(10)).High.Value);

        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            long committed = await CommittedTotalAsync(admin, group, partitions);
            if (end > 0 && committed >= end) return true;
            await Task.Delay(1000);
        }
        return false;
    }

    private static async Task<long> CommittedTotalAsync(
        IAdminClient admin, string group, List<TopicPartition> partitions)
    {
        try
        {
            var results = await admin.ListConsumerGroupOffsetsAsync(
                [new ConsumerGroupTopicPartitions(group, partitions)]);

            return results
                .SelectMany(r => r.Partitions)
                .Where(p => p.Offset != Offset.Unset)
                .Sum(p => p.Offset.Value);
        }
        catch (KafkaException)
        {
            // Group not yet known to the coordinator — treat as "nothing committed".
            return 0;
        }
    }
}
