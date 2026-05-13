namespace Wyb.Ledger.Data;

public class Transaction
{
    public Guid Id { get; set; }                    // app-generated UUID
    public string DedupKey { get; set; } = "";      // sha256 hex, indexed unique
    public DateOnly Date { get; set; }
    public long AmountMinor { get; set; }           // øre
    public string Currency { get; set; } = "DKK";
    public string RawDescription { get; set; } = "";
    public string AccountId { get; set; } = "";
    public DateTimeOffset ImportedAt { get; set; }
    public int SchemaVersion { get; set; } = 1;
}