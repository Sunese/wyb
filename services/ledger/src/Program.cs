using System.Text.Json.Serialization;
using JasperFx;
using JasperFx.Events;
using Marten;
using Microsoft.EntityFrameworkCore;
using Weasel.Core;
using Wyb.Ledger;
using Wyb.Ledger.Data;

var builder = WebApplication.CreateBuilder(args);

builder.AddServiceDefaults();
builder.AddNpgsqlDbContext<LedgerDbContext>("ledger-db");
var connectionString = builder.Configuration.GetConnectionString("ledger-db")
    ?? throw new InvalidOperationException("Connection string 'ledger-db' not found.");
builder.AddKafkaProducer<string, string>(connectionName: "kafka");
builder.AddKafkaConsumer<string, string>(connectionName: "kafka", opts => opts.DisableTracing = true); // We prefer to do this manually
builder.Services.AddHostedService<TransactionConsumer>();
builder.Services.ConfigureHttpJsonOptions(opts =>
    opts.SerializerOptions.Converters.Add(new JsonStringEnumConverter()));
var martenBuilder = builder.Services.AddMarten(options =>
    {
        options.UseSystemTextJsonForSerialization(enumStorage: EnumStorage.AsString);
        options.Events.StreamIdentity = StreamIdentity.AsString;
        options.Connection(connectionString);
        options.DatabaseSchemaName = "events";
    })
    .UseLightweightSessions();

if (builder.Environment.IsDevelopment())
{
    martenBuilder.ApplyAllDatabaseChangesOnStartup();
}

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    using var scope = app.Services.CreateScope();
    var dbContext = scope.ServiceProvider.GetRequiredService<LedgerDbContext>();
    await dbContext.Database.MigrateAsync();
}

app.MapDefaultEndpoints();

app.Run();
