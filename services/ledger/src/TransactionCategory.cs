using System.Text.Json.Serialization;

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum TransactionCategory
{
    Uncategorized,
    Income,
    Expense,
    Transfer,
    Investment,
    Beer,
    Groceries,
    Dining,
    Transport,
    Shopping,
    Entertainment,
    Utilities,
    Housing,
    Health,
    Home,
    Auto,
    Subscriptions,
    ATM,
    Travel,
}
