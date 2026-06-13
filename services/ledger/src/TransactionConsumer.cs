using System.Diagnostics;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Confluent.Kafka;
using JasperFx.Events;
using Marten;
using Marten.Exceptions;
using Npgsql;
using OpenTelemetry.Context.Propagation;
using Wyb.Ledger.Data;
using Wyb.Ledger.Events;

namespace Wyb.Ledger;

public class TransactionConsumer(
    IConsumer<string, string> consumer,
    ILogger<TransactionConsumer> logger,
    IDocumentStore documentStore)
    : BackgroundService
{
    private static readonly ActivitySource ActivitySource = new("Wyb.Ledger");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // Deliberate 5-second block — proves .NET 10 wraps ExecuteAsync in Task.Run.
        // Thread.Sleep(5000);

        // categorize enriches imported transactions and republishes them here.
        consumer.Subscribe("transaction.categorized");

        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    logger.LogInformation("Waiting to consume message...");
                    var result = consumer.Consume(stoppingToken); // blocks
                    if (result?.Message is null)
                    {
                        logger.LogWarning("Received null message at {TopicPartitionOffset}", result?.TopicPartitionOffset);
                        continue;
                    }

                    var producerContext = Propagators.DefaultTextMapPropagator.Extract(
                        default,
                        result.Message.Headers,
                        static (headers, key) =>
                        {
                            var val = headers?.FirstOrDefault(x => x.Key == key)?.GetValueBytes();
                            return val is byte[] bytes ? [Encoding.UTF8.GetString(bytes)] : [];
                        });

                    ActivityLink[] links = producerContext.ActivityContext.TraceId != default
                        ? [new ActivityLink(producerContext.ActivityContext)]
                        : [];

                    using var activity = ActivitySource.StartActivity(
                        "ledger.consume_transaction",
                        ActivityKind.Consumer,
                        parentContext: default,   // new root intentionally - async boundary
                        links: links);

                    logger.LogInformation("Received message at {TopicPartitionOffset}: {Key} = {Value}",
                        result.TopicPartitionOffset, result.Message.Key, result.Message.Value);
                    await HandleAsync(result, activity, stoppingToken);
                    logger.LogInformation("Finished processing message at {TopicPartitionOffset}", result.TopicPartitionOffset);

                    // At-least-once: commit only after successful processing.
                    consumer.Commit(result);
                }
                catch (ConsumeException ex)
                {
                    // Deserialization / broker error for one message — log, keep going.
                    logger.LogError(ex, "Kafka consume error: {Reason}", ex.Error.Reason);
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Normal shutdown via stoppingToken.
        }
        finally
        {
            consumer.Close(); // leaves the group cleanly, commits final offsets
        }
    }

    private async Task HandleAsync(ConsumeResult<string, string> result, Activity? activity, CancellationToken ct)
    {
        logger.LogInformation("Handling message at {TopicPartitionOffset}", result.TopicPartitionOffset);
        try
        {
            var receivedEvent = JsonSerializer.Deserialize<TransactionRecorded>(result.Message.Value, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
            })
                ?? throw new JsonException("Deserialized message value is null");

            var recorded = await RecordTransactionAsync(documentStore, receivedEvent, ct);
            if (!recorded)
            {
                activity?.SetTag("transaction.duplicate", true);
                activity?.SetStatus(ActivityStatusCode.Ok);
                logger.LogWarning("Duplicate transaction for DedupKey {DedupKey}. Skipping.", receivedEvent.DedupKey);
            }
        }
        catch (JsonException ex)
        {
            logger.LogError(ex, "Failed to deserialize message value: {Value}", result.Message.Value);
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Unhandled exception processing message at {TopicPartitionOffset}", result.TopicPartitionOffset);
        }
    }

    /// <summary>
    /// Appends a <see cref="TransactionRecorded"/> event to a new Marten stream keyed by
    /// <see cref="TransactionRecorded.DedupKey"/>. Returns false (and does nothing) when the
    /// stream already exists — this is the idempotency guard against Kafka redeliveries.
    /// </summary>
    internal static async Task<bool> RecordTransactionAsync(
        IDocumentStore store, TransactionRecorded recorded, CancellationToken ct = default)
    {
        await using var session = store.LightweightSession();
        try
        {
            var state = await session.Events.FetchStreamStateAsync(recorded.DedupKey, ct);
            if (state is not null) return false;

            session.Events.StartStream<Transaction>(recorded.DedupKey, recorded);
            await session.SaveChangesAsync(ct);
            return true;
        }
        catch (ExistingStreamIdCollisionException)
        {
            // Lost a race between FetchStreamStateAsync and StartStream — still idempotent.
            return false;
        }
    }
}
