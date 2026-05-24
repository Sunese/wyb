using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Testcontainers.PostgreSql;
using Wyb.Ledger.Data;

namespace Wyb.Ledger.IntegrationTests;

public class LedgerApiFactory : WebApplicationFactory<Program>, IAsyncLifetime
{
    private readonly PostgreSqlContainer _postgres = new PostgreSqlBuilder()
        .WithImage("postgres:17-alpine")
        .WithDatabase("ledger_test")
        .WithUsername("test")
        .WithPassword("test")
        .Build();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        // "Testing" skips the auto-migrate block in Program.cs (guarded by IsDevelopment).
        // Migration is run manually in InitializeAsync after the test container is up.
        builder.UseEnvironment("Testing");

        // Remove all hosted services so IConnection (RabbitMQ) is never resolved.
        builder.ConfigureServices(services => services.RemoveAll<IHostedService>());
    }

    async Task IAsyncLifetime.InitializeAsync()
    {
        await _postgres.StartAsync();

        // Inject connection strings as env vars so they are picked up by the config pipeline
        // before Aspire validates them. Must be set before Services is first accessed.
        Environment.SetEnvironmentVariable("ConnectionStrings__ledger-db", _postgres.GetConnectionString());
        Environment.SetEnvironmentVariable("ConnectionStrings__rabbit", "amqp://guest:guest@localhost:5672/");

        using var scope = Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<LedgerDbContext>();
        await db.Database.MigrateAsync();
    }

    async Task IAsyncLifetime.DisposeAsync()
    {
        Environment.SetEnvironmentVariable("ConnectionStrings__ledger-db", null);
        Environment.SetEnvironmentVariable("ConnectionStrings__rabbit", null);
        await _postgres.DisposeAsync();
    }
}
