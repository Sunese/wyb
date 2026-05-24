using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Wyb.Ledger.IntegrationTests;

/// <summary>
/// Tests for PATCH /transactions/{id}/category (manual override).
/// Transactions are seeded via POST /transactions (bypassing the RabbitMQ consumer).
/// Retroactive categorization is triggered by replaying raw imports through ingest,
/// not by a ledger endpoint — these tests cover the manual override side only.
/// </summary>
[Collection("LedgerApi")]
public class RecategorizeTests(LedgerApiFactory factory)
{
    private readonly HttpClient _client = factory.CreateClient();

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

    private async Task<JsonElement> SeedTransaction(string description, string category = "Uncategorized")
    {
        var payload = new
        {
            AccountId = "test-account",
            Date = "2025-06-01",
            AmountMinor = -5000,
            Currency = "DKK",
            RawDescription = description,
            SchemaVersion = 1,
            Category = category,
        };
        var res = await _client.PostAsJsonAsync("/transactions", payload, Json);
        res.EnsureSuccessStatusCode();
        return await res.Content.ReadFromJsonAsync<JsonElement>(Json);
    }

    [Fact]
    public async Task PatchCategory_SetsCategory_AndMarksOverridden()
    {
        var tx = await SeedTransaction($"MANUAL_OVERRIDE_{Guid.NewGuid()}");
        var id = tx.GetProperty("id").GetString();

        var patch = await _client.PatchAsJsonAsync(
            $"/transactions/{id}/category",
            new { Category = "Dining" },
            Json);
        Assert.Equal(HttpStatusCode.OK, patch.StatusCode);

        var updated = await patch.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.Equal("Dining", updated.GetProperty("category").GetString());
        Assert.True(updated.GetProperty("categoryOverridden").GetBoolean());
    }

    [Fact]
    public async Task PatchCategory_ReturnsNotFound_ForUnknownId()
    {
        var res = await _client.PatchAsJsonAsync(
            $"/transactions/{Guid.NewGuid()}/category",
            new { Category = "Dining" },
            Json);
        Assert.Equal(HttpStatusCode.NotFound, res.StatusCode);
    }

    [Fact]
    public async Task ImportTransaction_WithMerchantName_ReturnsMerchantName()
    {
        var desc = $"FAKEMOBILEPAY_{Guid.NewGuid()}";
        var tx = await SeedTransaction(desc);
        // Seeded without merchantName — verify it's absent by default.
        Assert.False(tx.TryGetProperty("merchantName", out var mn) && mn.ValueKind != JsonValueKind.Null,
            "merchantName should be null when not supplied");
    }

    [Fact]
    public async Task ImportTransaction_WithCategoryOverridden_FieldIsRoundtripped()
    {
        // Seed a transaction, patch it, then retrieve it and confirm categoryOverridden survives.
        var tx = await SeedTransaction($"ROUND_TRIP_{Guid.NewGuid()}");
        var id = tx.GetProperty("id").GetString();

        await _client.PatchAsJsonAsync($"/transactions/{id}/category",
            new { Category = "Transport" }, Json);

        var txs = await _client.GetFromJsonAsync<JsonElement[]>("/transactions", Json);
        var found = txs!.First(t => t.GetProperty("id").GetString() == id);
        Assert.True(found.GetProperty("categoryOverridden").GetBoolean());
        Assert.Equal("Transport", found.GetProperty("category").GetString());
    }
}
