using System.Text.Json;
using Aspire.Hosting;
using Aspire.Hosting.ApplicationModel;
using Aspire.Hosting.Testing;

namespace Wyb.Integration.Tests;

/// <summary>
/// Boots the full AppHost once and shares it across every test in the "Stack"
/// collection, avoiding a ~60-second startup per test class.
///
/// Exposes the Kafka bootstrap servers plus HTTP clients for each service so the
/// tests can drive the real, wired-up stack: ingest publishes to <c>my-topic</c>,
/// categorize enriches into <c>transaction.categorized</c>, ledger and detect consume.
/// </summary>
public sealed class StackFixture : IAsyncLifetime
{
    public DistributedApplication App { get; private set; } = null!;
    public string Bootstrap { get; private set; } = null!;

    public HttpClient Rules { get; private set; } = null!;
    public HttpClient Categorize { get; private set; } = null!;
    public HttpClient Detect { get; private set; } = null!;
    public HttpClient Ingest { get; private set; } = null!;

    public async Task InitializeAsync()
    {
        var appHost = await DistributedApplicationTestingBuilder
            .CreateAsync<Projects.Wyb_AppHost>();

        App = await appHost
            .WithContainersLifetime(ContainerLifetime.Session)
            .BuildAsync();

        await App.StartAsync();

        // .NET resources (kafka container, ledger) register Aspire health checks.
        await App.ResourceNotifications
            .WaitForResourceHealthyAsync("kafka")
            .WaitAsync(TimeSpan.FromSeconds(120));
        await App.ResourceNotifications
            .WaitForResourceHealthyAsync("ledger")
            .WaitAsync(TimeSpan.FromSeconds(120));

        Bootstrap = (await App.GetConnectionStringAsync("kafka"))
            ?? throw new InvalidOperationException("kafka connection string not available");

        Rules = App.CreateHttpClient("rules");
        Categorize = App.CreateHttpClient("categorize");
        Detect = App.CreateHttpClient("detect");
        Ingest = App.CreateHttpClient("ingest");

        // The Go/Python services don't register Aspire health checks — poll them.
        await WaitForHttpAsync(Rules, "/rules");
        await WaitForHttpAsync(Categorize, "/health");
        await WaitForHttpAsync(Detect, "/health");
        await WaitForHttpAsync(Ingest, "/health");

        // Background Kafka consumers (categorize, detect, ledger) join their groups
        // asynchronously after the HTTP server is up. Push a sentinel through the
        // whole pipeline and block until every stage has consumed it, so per-test
        // assertions don't race a cold consumer.
        await WarmUpPipelineAsync();
    }

    private async Task WarmUpPipelineAsync()
    {
        var timeout = TimeSpan.FromSeconds(120);
        var description = $"WARMUP_{Guid.NewGuid():N}";
        var sentinel = JsonSerializer.Serialize(new
        {
            schema_version = 1,
            source_file = "warmup.csv",
            row_index = 0,
            account_id = "warmup",
            date = "2025-01-01",
            amount_minor = 0,
            currency = "DKK",
            raw_description = description,
        });

        await KafkaTestClient.ProduceAsync(Bootstrap, "my-topic", sentinel);

        // categorize consumed my-topic and republished to transaction.categorized.
        var enriched = await KafkaTestClient.ConsumeMatchingAsync(
            Bootstrap, "transaction.categorized",
            json => json.TryGetProperty("raw_description", out var d) && d.GetString() == description,
            timeout);
        if (enriched is null)
            throw new InvalidOperationException("categorize did not enrich the warmup message in time");

        // detect drained my-topic; ledger drained transaction.categorized.
        if (!await KafkaTestClient.WaitForGroupCaughtUpAsync(Bootstrap, "detect", "my-topic", timeout))
            throw new InvalidOperationException("detect did not catch up during warmup");
        if (!await KafkaTestClient.WaitForGroupCaughtUpAsync(Bootstrap, "my-group", "transaction.categorized", timeout))
            throw new InvalidOperationException("ledger did not catch up during warmup");
    }

    public async Task DisposeAsync()
    {
        Rules.Dispose();
        Categorize.Dispose();
        Detect.Dispose();
        Ingest.Dispose();
        await App.DisposeAsync();
    }

    private static async Task WaitForHttpAsync(HttpClient client, string path)
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(120));
        while (true)
        {
            try
            {
                var res = await client.GetAsync(path, cts.Token);
                if (res.IsSuccessStatusCode) return;
            }
            catch (Exception) when (!cts.IsCancellationRequested) { }

            await Task.Delay(TimeSpan.FromMilliseconds(500), cts.Token);
        }
    }
}

[CollectionDefinition("Stack")]
public class StackCollection : ICollectionFixture<StackFixture>;
