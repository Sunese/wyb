using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using OpenTelemetry.Context.Propagation;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using Wyb.Ledger.Data;

namespace Wyb.Ledger;

public class TransactionConsumer(IConnection rabbit, IServiceScopeFactory scopeFactory, ILogger<TransactionConsumer> logger)
    : BackgroundService
{
    private static readonly ActivitySource ActivitySource = new("Wyb.Ledger");
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var channel = await rabbit.CreateChannelAsync(cancellationToken: stoppingToken);

        await channel.ExchangeDeclareAsync(
            exchange: "transaction.categorized",
            type: ExchangeType.Fanout,
            durable: true,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await channel.ExchangeDeclareAsync(
            exchange: "transaction.categorized.dlx",
            type: ExchangeType.Fanout,
            durable: true,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await channel.QueueDeclareAsync(
            queue: "ledger.transaction.categorized.dlq",
            durable: true,
            exclusive: false,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await channel.QueueBindAsync(
            queue: "ledger.transaction.categorized.dlq",
            exchange: "transaction.categorized.dlx",
            routingKey: "",
            cancellationToken: stoppingToken);

        await channel.QueueDeclareAsync(
            queue: "ledger.transaction.categorized",
            durable: true,
            exclusive: false,
            autoDelete: false,
            arguments: new Dictionary<string, object?> { ["x-dead-letter-exchange"] = "transaction.categorized.dlx" },
            cancellationToken: stoppingToken);

        await channel.QueueBindAsync(
            queue: "ledger.transaction.categorized",
            exchange: "transaction.categorized",
            routingKey: "",
            cancellationToken: stoppingToken);

        var consumer = new AsyncEventingBasicConsumer(channel);
        consumer.ReceivedAsync += async (_, ea) =>
        {
            var linkContext = Propagators.DefaultTextMapPropagator.Extract(
                default,
                ea.BasicProperties.Headers,
                static (headers, key) =>
                {
                    if (key != "traceparent") return [];
                    if (headers is null || !headers.TryGetValue("x-link-traceparent", out var val)) return [];
                    return val is byte[] bytes ? [Encoding.UTF8.GetString(bytes)] : [val?.ToString() ?? string.Empty];
                });

            ActivityLink[] links = linkContext.ActivityContext.TraceId != default
                ? [new ActivityLink(linkContext.ActivityContext)]
                : [];

            using var activity = ActivitySource.StartActivity(
                "ledger.consume_transaction",
                ActivityKind.Consumer,
                parentContext: default,
                links: links);

            try
            {
                var msg = JsonSerializer.Deserialize<ImportTransactionRequest>(
                    ea.Body.Span,
                    new JsonSerializerOptions
                    {
                        PropertyNameCaseInsensitive = true,
                        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
                    });

                if (msg is null)
                {
                    logger.LogWarning("Received null or undeserializable message, discarding");
                    await channel.BasicAckAsync(ea.DeliveryTag, multiple: false);
                    return;
                }

                using var scope = scopeFactory.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<LedgerDbContext>();

                var (dedupKey, hashInput) = DedupKey.Compute(msg.AccountId, msg.Date, msg.AmountMinor, msg.Currency, msg.RawDescription);

                var existing = await db.Transactions.FirstOrDefaultAsync(t => t.DedupKey == dedupKey);
                if (existing is null)
                {
                    logger.LogInformation("Importing transaction. Input: {Input}", hashInput);
                    db.Transactions.Add(new Transaction
                    {
                        DedupKey = dedupKey,
                        Date = msg.Date,
                        AmountMinor = msg.AmountMinor,
                        Currency = msg.Currency,
                        RawDescription = msg.RawDescription,
                        AccountId = msg.AccountId,
                        ImportedAt = DateTimeOffset.UtcNow,
                        SchemaVersion = msg.SchemaVersion,
                        Category = msg.Category,
                        MerchantName = msg.MerchantName,
                    });
                    await db.SaveChangesAsync();
                }
                else if (!existing.CategoryOverridden &&
                         (existing.Category != msg.Category || existing.MerchantName != msg.MerchantName))
                {
                    logger.LogInformation(
                        "Updating transaction category/merchant. Input: {Input}", hashInput);
                    existing.Category = msg.Category;
                    existing.MerchantName = msg.MerchantName;
                    await db.SaveChangesAsync();
                }
                else
                {
                    logger.LogInformation("Transaction already up to date, skipping. Input: {Input}", hashInput);
                }

                await channel.BasicAckAsync(ea.DeliveryTag, multiple: false);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Failed to process transaction message, sending to DLQ");
                await channel.BasicNackAsync(ea.DeliveryTag, multiple: false, requeue: false);
            }
        };

        await channel.BasicConsumeAsync(
            queue: "ledger.transaction.categorized",
            autoAck: false,
            consumer: consumer,
            cancellationToken: stoppingToken);

        await Task.Delay(Timeout.Infinite, stoppingToken);
    }
}