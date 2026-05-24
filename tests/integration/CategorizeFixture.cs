using Aspire.Hosting;
using Aspire.Hosting.ApplicationModel;
using Aspire.Hosting.Testing;
using RabbitMQ.Client;

namespace Wyb.Integration.Tests;

/// <summary>
/// Boots the full AppHost once and shares it across all tests in the
/// "Categorize" collection, avoiding a 60-second startup per test class.
/// </summary>
public sealed class CategorizeFixture : IAsyncLifetime
{
    public DistributedApplication App { get; private set; } = null!;
    public IConnection Rabbit { get; private set; } = null!;
    public HttpClient CategorizeHttp { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        var appHost = await DistributedApplicationTestingBuilder
            .CreateAsync<Projects.Wyb_AppHost>();

        App = await appHost
            .WithContainersLifetime(ContainerLifetime.Session)
            .BuildAsync();

        await App.StartAsync();

        await App.ResourceNotifications
            .WaitForResourceHealthyAsync("rabbit")
            .WaitAsync(TimeSpan.FromSeconds(90));
        await App.ResourceNotifications
            .WaitForResourceHealthyAsync("ledger")
            .WaitAsync(TimeSpan.FromSeconds(90));

        // Categorize is a Python/uvicorn process — it doesn't register health
        // checks with Aspire, so we poll its /rules endpoint until it responds.
        CategorizeHttp = App.CreateHttpClient("categorize");
        await WaitForCategorizeAsync();
    }

    public async Task DisposeAsync()
    {
        CategorizeHttp.Dispose();
        if (Rabbit is not null) await Rabbit.CloseAsync();
        await App.DisposeAsync();
    }

    private async Task WaitForCategorizeAsync()
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        while (true)
        {
            try
            {
                var res = await CategorizeHttp.GetAsync("/rules", cts.Token);
                if (res.IsSuccessStatusCode)
                {
                    // Give the RabbitMQ consumer inside categorize a moment to bind its queues.
                    await Task.Delay(TimeSpan.FromSeconds(3), cts.Token);

                    var connString = await App.GetConnectionStringAsync("rabbit");
                    var factory = new ConnectionFactory { Uri = new Uri(connString!) };
                    Rabbit = await factory.CreateConnectionAsync();
                    return;
                }
            }
            catch (Exception) when (!cts.IsCancellationRequested) { }

            await Task.Delay(TimeSpan.FromMilliseconds(500), cts.Token);
        }
    }
}

[CollectionDefinition("Categorize")]
public class CategorizeCollection : ICollectionFixture<CategorizeFixture>;
