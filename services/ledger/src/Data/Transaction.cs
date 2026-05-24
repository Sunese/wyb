namespace Wyb.Ledger.Data;

public class Transaction
{
    public Guid Id { get; private set; } = Guid.NewGuid();
    public required string DedupKey { get; init; }      // sha256 hex, indexed unique
    public required DateOnly Date { get; init; }
    public required long AmountMinor { get; init; }           // amount in minor units (e.g. 2500 which would represent 25.00)
    public required string Currency { get; init; }
    public required string RawDescription { get; init; }
    public required DateTimeOffset ImportedAt { get; init; }
    public required TransactionCategory Category { get; set; }
    public required int SchemaVersion { get; init; }

    /// <summary>
    /// Optional account ID. Not necessarily known, therefore nullable.
    /// </summary>
    public string? AccountId { get; init; }

    /// <summary>
    /// Resolved canonical merchant name, e.g. "MENY" for "MENY VESTERBRO 1234".
    /// Null when no alias matches.
    /// </summary>
    public string? MerchantName { get; set; }

    /// <summary>
    /// When true, retroactive recategorization will not overwrite this transaction's category.
    /// </summary>
    public bool CategoryOverridden { get; set; }
}