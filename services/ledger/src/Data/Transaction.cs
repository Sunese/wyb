using Wyb.Ledger.Events;

namespace Wyb.Ledger.Data;

/// <param name="Id">Identifier. De-duplication key. Is a SHA-256 hash of the transaction data. </param>
/// <param name="Date"></param>
/// <param name="AmountMinor"></param>
/// <param name="Currency"></param>
/// <param name="RawDescription"></param>
/// <param name="ImportedAt"></param>
/// <param name="Category"></param>
/// <param name="SchemaVersion"></param>
/// <param name="AccountId"> Optional account ID. Not necessarily known, therefore nullable. </param>
/// <param name="MerchantName"> Resolved canonical merchant name, e.g. "MENY" for "MENY VESTERBRO 1234". Null when no alias matches. </param>
/// <param name="CategoryOverridden"> When true, retroactive recategorization will not overwrite this transaction's category. </param>
public sealed record Transaction(string Id,
                                 DateOnly Date,
                                 long AmountMinor,
                                 string Currency,
                                 string RawDescription,
                                 DateTimeOffset ImportedAt,
                                 TransactionCategory Category,
                                 int SchemaVersion,
                                 string? AccountId = null,
                                 string? MerchantName = null,
                                 bool CategoryOverridden = false)
{
    public static Transaction Create(TransactionRecorded recorded) => new(recorded.DedupKey,
                                                              recorded.Date,
                                                              recorded.AmountMinor,
                                                              recorded.Currency,
                                                              recorded.RawDescription,
                                                              recorded.ImportedAt,
                                                              recorded.Category,
                                                              recorded.SchemaVersion,
                                                              AccountId: recorded.AccountId,
                                                              MerchantName: recorded.MerchantName);

    public static Transaction Apply(Transaction current, CategoryOverridden @event) =>
        current with { Category = @event.Category, CategoryOverridden = true };
}