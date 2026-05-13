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
            exchange: "transaction.imported",
            type: ExchangeType.Fanout,
            durable: true,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await channel.ExchangeDeclareAsync(
            exchange: "transaction.imported.dlx",
            type: ExchangeType.Fanout,
            durable: true,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await channel.QueueDeclareAsync(
            queue: "ledger.transaction.imported.dlq",
            durable: true,
            exclusive: false,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await channel.QueueBindAsync(
            queue: "ledger.transaction.imported.dlq",
            exchange: "transaction.imported.dlx",
            routingKey: "",
            cancellationToken: stoppingToken);

        await channel.QueueDeclareAsync(
            queue: "ledger.transaction.imported",
            durable: true,
            exclusive: false,
            autoDelete: false,
            arguments: new Dictionary<string, object?> { ["x-dead-letter-exchange"] = "transaction.imported.dlx" },
            cancellationToken: stoppingToken);

        await channel.QueueBindAsync(
            queue: "ledger.transaction.imported",
            exchange: "transaction.imported",
            routingKey: "",
            cancellationToken: stoppingToken);

        var consumer = new AsyncEventingBasicConsumer(channel);
        consumer.ReceivedAsync += async (_, ea) =>
        {
            try
            {
                var req = JsonSerializer.Deserialize<ImportTransactionRequest>(
                    ea.Body.Span,
                    new JsonSerializerOptions
                    {
                        PropertyNameCaseInsensitive = true,
                        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
                    });

                if (req is null)
                {
                    logger.LogWarning("Received null or undeserializable message, discarding");
                    await channel.BasicAckAsync(ea.DeliveryTag, multiple: false);
                    return;
                }

                using var scope = scopeFactory.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<LedgerDbContext>();

                var dedupKey = DedupKey.Compute(req.AccountId, req.Date, req.AmountMinor, req.Currency, req.RawDescription);

                var exists = await db.Transactions.AnyAsync(t => t.DedupKey == dedupKey);
                if (!exists)
                {
                    db.Transactions.Add(new Transaction
                    {
                        Id = Guid.NewGuid(),
                        DedupKey = dedupKey,
                        Date = req.Date,
                        AmountMinor = req.AmountMinor,
                        Currency = req.Currency,
                        RawDescription = req.RawDescription,
                        AccountId = req.AccountId,
                        ImportedAt = DateTimeOffset.UtcNow,
                        SchemaVersion = req.SchemaVersion,
                    });
                    await db.SaveChangesAsync();
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
            queue: "ledger.transaction.imported",
            autoAck: false,
            consumer: consumer,
            cancellationToken: stoppingToken);

        await Task.Delay(Timeout.Infinite, stoppingToken);
    }
}