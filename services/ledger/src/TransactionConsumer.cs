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
            await using var session = documentStore.LightweightSession();

            var streamState = await session.Events.FetchStreamStateAsync(receivedEvent.DedupKey, ct);
            if (streamState != null)
            {
                activity?.SetTag("transaction.duplicate", true);
                activity?.SetStatus(ActivityStatusCode.Ok);
                logger.LogWarning("Duplicate transaction detected for DedupKey {DedupKey}. Skipping...", receivedEvent.DedupKey);
                return; // Idempotent handling: skip duplicates
            }

            session.Events.StartStream<Transaction>(receivedEvent.DedupKey, receivedEvent);
            await session.SaveChangesAsync(ct);
        }
        catch (JsonException ex)
        {
            logger.LogError(ex, "Failed to deserialize message value: {Value}", result.Message.Value);
            return; // Skip processing this message
        }
        catch (ExistingStreamIdCollisionException ex)
        {
            activity?.SetTag("transaction.duplicate", true);
            activity?.SetStatus(ActivityStatusCode.Ok);
            logger.LogWarning(ex, "Duplicate transaction detected. Skipping...");
            return; // Idempotent handling: skip duplicates
        }



        // session.Events.Append(result.Message.Key, );
        // result.Message.Key, result.Message.Value (JSON), result.Message.Headers (traceparent)

    }
}
