using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using Wyb.Ledger.Data;

namespace Wyb.Ledger;

public class TransactionConsumer(IConnection rabbit, IServiceScopeFactory scopeFactory, ILogger<TransactionConsumer> logger)
    : BackgroundService
{
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

                var exists = await db.Transactions.AnyAsync(t => t.DedupKey == dedupKey);
                if (!exists)
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
                    });
                    await db.SaveChangesAsync();
                }
                else
                {
                    // we might have analyzed us to richer details, such as a new category
                    var existing = await db.Transactions.FirstOrDefaultAsync(t => t.DedupKey == dedupKey);
                    if (existing is not null && existing.Category != msg.Category)
                    {
                        logger.LogInformation("Updating transaction category from {OldCategory} to {NewCategory}. Input: {Input}", existing.Category, msg.Category, hashInput);
                        existing.Category = msg.Category;
                        await db.SaveChangesAsync();
                    }
                    else
                    {
                        logger.LogInformation("Transaction already exists with same category, skipping. Input: {Input}", hashInput);
                    }
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