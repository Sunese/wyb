using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Wyb.Integration.Tests;

[Collection("Categorize")]
public class CategorizeApiTests(CategorizeFixture fixture)
{
    private readonly HttpClient _http = fixture.CategorizeHttp;

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

    // ── Rules ─────────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetRules_ReturnsJsonArray()
    {
        var res = await _http.GetAsync("/rules");
        res.EnsureSuccessStatusCode();
        var rules = await res.Content.ReadFromJsonAsync<JsonElement[]>(Json);
        Assert.NotNull(rules);
    }

    [Fact]
    public async Task PostRule_CreatesIt_AndGetReturnsIt()
    {
        var post = await _http.PostAsJsonAsync("/rules", new
        {
            name = "Live test grocery rule",
            pattern = $"INTEGRATION_RULE_{Guid.NewGuid():N}",
            matchType = "Contains",
            category = "Groceries",
            priority = 50,
        }, Json);

        Assert.Equal(HttpStatusCode.Created, post.StatusCode);
        var created = await post.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.Equal("Groceries", created.GetProperty("category").GetString());
        Assert.Equal(50, created.GetProperty("priority").GetInt32());

        var ruleId = created.GetProperty("id").GetString();

        // Verify it appears in GET /rules
        var all = await _http.GetFromJsonAsync<JsonElement[]>("/rules", Json);
        Assert.Contains(all!, r => r.GetProperty("id").GetString() == ruleId);

        // Clean up
        await _http.DeleteAsync($"/rules/{ruleId}");
    }

    [Fact]
    public async Task DeleteRule_RemovesIt()
    {
        var post = await _http.PostAsJsonAsync("/rules", new
        {
            name = "To delete",
            pattern = $"DELETE_ME_{Guid.NewGuid():N}",
            matchType = "Exact",
            category = "Uncategorized",
            priority = 99,
        }, Json);
        var id = (await post.Content.ReadFromJsonAsync<JsonElement>(Json)).GetProperty("id").GetString();

        var del = await _http.DeleteAsync($"/rules/{id}");
        Assert.Equal(HttpStatusCode.NoContent, del.StatusCode);

        var all = await _http.GetFromJsonAsync<JsonElement[]>("/rules", Json);
        Assert.DoesNotContain(all!, r => r.GetProperty("id").GetString() == id);
    }

    [Fact]
    public async Task DeleteRule_ReturnsNotFound_ForUnknownId()
    {
        var res = await _http.DeleteAsync($"/rules/{Guid.NewGuid()}");
        Assert.Equal(HttpStatusCode.NotFound, res.StatusCode);
    }

    // ── Merchants ─────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetMerchants_ReturnsJsonArray()
    {
        var res = await _http.GetAsync("/merchants");
        res.EnsureSuccessStatusCode();
        var merchants = await res.Content.ReadFromJsonAsync<JsonElement[]>(Json);
        Assert.NotNull(merchants);
    }

    [Fact]
    public async Task PostMerchant_CreatesIt_WithNoDefaultCategory()
    {
        var post = await _http.PostAsJsonAsync("/merchants",
            new { canonicalName = $"TESTMERCHANT_{Guid.NewGuid():N}" }, Json);
        Assert.Equal(HttpStatusCode.Created, post.StatusCode);
        var body = await post.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.Equal(JsonValueKind.Null, body.GetProperty("defaultCategory").ValueKind);
        Assert.Equal(0, body.GetProperty("aliases").GetArrayLength());

        await _http.DeleteAsync($"/merchants/{body.GetProperty("id").GetString()}");
    }

    [Fact]
    public async Task PostMerchant_WithDefaultCategory_IsReturnedCorrectly()
    {
        var post = await _http.PostAsJsonAsync("/merchants",
            new { canonicalName = $"MOBILEPAY_{Guid.NewGuid():N}", defaultCategory = "Transfer" }, Json);
        Assert.Equal(HttpStatusCode.Created, post.StatusCode);
        var body = await post.Content.ReadFromJsonAsync<JsonElement>(Json);
        Assert.Equal("Transfer", body.GetProperty("defaultCategory").GetString());

        await _http.DeleteAsync($"/merchants/{body.GetProperty("id").GetString()}");
    }

    [Fact]
    public async Task PostAlias_AppearsInGetMerchants()
    {
        var merchantId = (await (await _http.PostAsJsonAsync("/merchants",
            new { canonicalName = $"ALIAS_TEST_{Guid.NewGuid():N}" }, Json))
            .Content.ReadFromJsonAsync<JsonElement>(Json)).GetProperty("id").GetString();

        var aliasPost = await _http.PostAsJsonAsync(
            $"/merchants/{merchantId}/aliases",
            new { pattern = "ALIASPATTERN", matchType = "StartsWith" }, Json);
        Assert.Equal(HttpStatusCode.Created, aliasPost.StatusCode);

        var merchants = await _http.GetFromJsonAsync<JsonElement[]>("/merchants", Json);
        var merchant = merchants!.First(m => m.GetProperty("id").GetString() == merchantId);
        Assert.Equal(1, merchant.GetProperty("aliases").GetArrayLength());

        await _http.DeleteAsync($"/merchants/{merchantId}");
    }

    [Fact]
    public async Task DeleteMerchant_CascadesAliases()
    {
        var merchantId = (await (await _http.PostAsJsonAsync("/merchants",
            new { canonicalName = $"CASCADE_{Guid.NewGuid():N}" }, Json))
            .Content.ReadFromJsonAsync<JsonElement>(Json)).GetProperty("id").GetString();

        var alias = await (await _http.PostAsJsonAsync(
            $"/merchants/{merchantId}/aliases",
            new { pattern = "CASCADE", matchType = "Contains" }, Json))
            .Content.ReadFromJsonAsync<JsonElement>(Json);
        var aliasId = alias.GetProperty("id").GetString();

        await _http.DeleteAsync($"/merchants/{merchantId}");

        // Alias should be gone too
        var del = await _http.DeleteAsync($"/aliases/{aliasId}");
        Assert.Equal(HttpStatusCode.NotFound, del.StatusCode);
    }

    [Fact]
    public async Task PostAlias_ReturnsNotFound_ForUnknownMerchant()
    {
        var res = await _http.PostAsJsonAsync(
            $"/merchants/{Guid.NewGuid()}/aliases",
            new { pattern = "X", matchType = "Contains" }, Json);
        Assert.Equal(HttpStatusCode.NotFound, res.StatusCode);
    }
}
