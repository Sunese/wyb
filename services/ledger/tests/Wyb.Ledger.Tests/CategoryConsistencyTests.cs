using System.Text.Json;

namespace Wyb.Ledger.Tests;

public class CategoryConsistencyTests
{
    [Fact]
    public void TransactionCategory_enum_matches_shared_categories_json()
    {
        var json = File.ReadAllText("categories.json");
        var canonical = JsonSerializer.Deserialize<string[]>(json)!;

        var enumValues = Enum.GetNames<TransactionCategory>();

        Assert.Equal(
            canonical.OrderBy(x => x),
            enumValues.OrderBy(x => x));
    }
}
