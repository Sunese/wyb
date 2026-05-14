using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.EntityFrameworkCore;
using RabbitMQ.Client;
using Wyb.Ledger;
using Wyb.Ledger.Data;

var builder = WebApplication.CreateBuilder(args);

builder.AddServiceDefaults();
builder.AddRabbitMQClient(connectionName: "rabbit");
builder.AddNpgsqlDbContext<LedgerDbContext>("ledger-db");
builder.Services.AddHostedService<TransactionConsumer>();

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    using var scope = app.Services.CreateScope();
    var dbContext = scope.ServiceProvider.GetRequiredService<LedgerDbContext>();
    await dbContext.Database.MigrateAsync();
}

app.MapDefaultEndpoints();

app.MapPost("/transactions", async (ImportTransactionRequest req, LedgerDbContext db) =>
{
    var (dedupKey, hashInput) = DedupKey.Compute(req.AccountId, req.Date, req.AmountMinor, req.Currency, req.RawDescription);

    var existing = await db.Transactions.FirstOrDefaultAsync(t => t.DedupKey == dedupKey);
    if (existing is not null)
        return Results.Ok(existing);

    var transaction = new Transaction
    {
        DedupKey = dedupKey,
        Date = req.Date,
        AmountMinor = req.AmountMinor,
        Currency = req.Currency,
        RawDescription = req.RawDescription,
        AccountId = req.AccountId,
        ImportedAt = DateTimeOffset.UtcNow,
        SchemaVersion = req.SchemaVersion,
        Category = req.Category,
    };

    db.Transactions.Add(transaction);
    await db.SaveChangesAsync();
    return Results.Created($"/transactions/{transaction.Id}", transaction);
});

app.MapGet("/transactions", async (
    LedgerDbContext db,
    DateOnly? from,
    DateOnly? to,
    int limit = 100,
    int offset = 0) =>
{
    var query = db.Transactions.AsQueryable();

    if (from.HasValue) query = query.Where(t => t.Date >= from.Value);
    if (to.HasValue) query = query.Where(t => t.Date <= to.Value);

    var transactions = await query
        .OrderByDescending(t => t.Date)
        .Skip(offset)
        .Take(Math.Min(limit, 1000))
        .ToListAsync();

    return Results.Ok(transactions);
});

app.Run();

record ImportTransactionRequest(
    string AccountId,
    DateOnly Date,
    long AmountMinor,
    string Currency,
    string RawDescription,
    int SchemaVersion = 1,
    TransactionCategory Category = TransactionCategory.Uncategorized);

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum TransactionCategory
{
    Uncategorized,
    Income,
    Expense,
    Transfer,
    Investment,
    Beer
}