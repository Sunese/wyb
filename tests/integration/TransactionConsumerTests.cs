using System.Text;
using Aspire.Hosting;
using Aspire.Hosting.Testing;
using RabbitMQ.Client;

namespace Wyb.Integration.Tests;

public class TransactionConsumerTests : IAsyncLifetime
{
    private DistributedApplication _app = null!;
    private IConnection _rabbit = null!;

    public async Task InitializeAsync()
    {
        var appHost = await DistributedApplicationTestingBuilder.CreateAsync<Projects.Wyb_AppHost>();
        _app = await appHost.BuildAsync();
        await _app.StartAsync();

        await _app.ResourceNotifications
            .WaitForResourceHealthyAsync("rabbit")
            .WaitAsync(TimeSpan.FromSeconds(60));
        await _app.ResourceNotifications
            .WaitForResourceHealthyAsync("ledger")
            .WaitAsync(TimeSpan.FromSeconds(60));

        // Give the consumer time to connect and declare its queues.
        await Task.Delay(TimeSpan.FromSeconds(5));

        var connString = await _app.GetConnectionStringAsync("rabbit");
        var factory = new ConnectionFactory { Uri = new Uri(connString!) };
        _rabbit = await factory.CreateConnectionAsync();
    }

    public async Task DisposeAsync()
    {
        await _rabbit.CloseAsync();
        await _app.DisposeAsync();
    }

    [Fact]
    public async Task PoisonMessage_IsRoutedToDlq_NotRequeued()
    {
        using var channel = await _rabbit.CreateChannelAsync();

        await channel.BasicPublishAsync(
            exchange: "transaction.imported",
            routingKey: "",
            body: Encoding.UTF8.GetBytes("not valid json {{{{"));

        // Poll DLQ until message arrives (max 10 s).
        QueueDeclareOk dlq = null!;
        for (int i = 0; i < 20; i++)
        {
            await Task.Delay(500);
            dlq = await channel.QueueDeclarePassiveAsync("ledger.transaction.imported.dlq");
            if (dlq.MessageCount > 0) break;
        }

        Assert.Equal(1u, dlq.MessageCount);

        var main = await channel.QueueDeclarePassiveAsync("ledger.transaction.imported");
        Assert.Equal(0u, main.MessageCount);
    }
}
